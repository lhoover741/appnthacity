import os
import json
import random
import smtplib
import logging
import secrets
import uuid
import time
import urllib.request
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from flask import Flask, request, jsonify, send_from_directory, session, redirect, abort, g
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_migrate import Migrate
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from sqlalchemy import text, or_, func
from security_service import (
    admin_required,
    police_required,
    dispatch_required,
    judge_required,
    dmv_required,
    require_auth,
    verify_password,
    hash_password,
    ROLES
)
from performance_service import cache, paginate_query
from platform_config import (
    PLATFORM_NAME,
    PLATFORM_DOMAIN,
    PLATFORM_TAGLINE,
    PLATFORM_CTA,
    DEFAULT_COMMUNITY_ID,
    DEFAULT_COMMUNITY_NAME,
    DEFAULT_COMMUNITY_SLUG,
    DEFAULT_COMMUNITY_CAD_NAME,
    DEFAULT_COMMUNITY_DEPARTMENTS,
)

# Force clear SQLAlchemy metadata cache to ensure fresh schema detection
import sqlalchemy
from sqlalchemy import inspect as sa_inspect

# This ensures we don't use cached metadata
if hasattr(sqlalchemy, '_sa_registry'):
    sqlalchemy._sa_registry.clear()

# Import database and models FIRST
from database import db, configure_database
from models import (
    User, Config, Complaint, Application, Civilian, Vehicle, License,
    Warrant, Arrest, Incident, Evidence, TrafficStop, Call911,
    ActivityLog, Bolo, OfficerSession, Alert, RadioLog,
    ServerStatus, Inmate, Hearing, DispatchCall,
    KnownAssociate, Business, Citation, JailBooking,
    UseOfForceReport, OfficerNote, CaseFile,
    AIGenerationLog, AuditLog,
    Community, CommunityMember, CommunityInvite,
    PlatformAdminLog, PlatformActivityLog, PasswordResetToken, CommunityStatus, UserSession
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
PROCESS_START_TIME = time.time()
ACTIVE_SOCKET_CONNECTIONS = {}
SOCKET_RATE_LIMITS = {}
WEBSOCKET_EVENTS_PER_MINUTE = 120


def _safe_json_error(message, code, status=400, details=None):
    return jsonify({
        'success': False,
        'error': message,
        'code': code,
        'request_id': getattr(g, 'request_id', None),
        'details': details or {}
    }), status

def _user_field(user, field_name, default=None):
    """Read a user field safely to tolerate optional/nullable columns."""
    try:
        value = getattr(user, field_name)
    except Exception:
        return default
    return default if value is None else value


def _session_hydrate_user(user):
    """Hydrate auth session with required user fields and defensive fallbacks."""
    user_id = _user_field(user, 'id')
    username = _user_field(user, 'username', '') or ''
    email = _user_field(user, 'email', None)
    role = (_user_field(user, 'role', 'Civilian') or 'Civilian').strip() or 'Civilian'
    platform_role = (_user_field(user, 'platform_role', None) or role).strip() or role

    owner_email = (os.getenv('PLATFORM_OWNER_EMAIL') or '').strip().lower()
    is_owner_by_email = bool(owner_email and (email or '').strip().lower() == owner_email)
    is_platform_owner = role == 'PlatformOwner' or platform_role == 'PlatformOwner' or is_owner_by_email

    if is_platform_owner:
        platform_role = 'PlatformOwner'

    session['user_id'] = user_id
    session['username'] = username
    session['email'] = email
    session['role'] = role
    session['platform_role'] = platform_role
    session['is_platform_owner'] = is_platform_owner
    session['active_community_id'] = session.get('selected_community_id')

    missing = [k for k in ('user_id', 'username', 'role', 'platform_role', 'is_platform_owner') if session.get(k) in (None, '')]
    if missing:
        logger.warning("Session hydration missing required fields user_id=%s missing=%s", user_id, missing)

    session.modified = True
    logger.info("Session created user_id=%s username=%s role=%s platform_role=%s is_platform_owner=%s",
                user_id, username, role, platform_role, is_platform_owner)

    return is_platform_owner

# Production logging configuration
if os.environ.get('FLASK_ENV') == 'production':
    logging.getLogger('werkzeug').setLevel(logging.WARNING)  # Reduce Flask request logging
    logger.info('🔒 Production mode: Reduced logging verbosity')

app = Flask(__name__, static_folder='.', static_url_path='')
if not os.environ.get('SECRET_KEY'):
    raise RuntimeError('SECRET_KEY environment variable is required')

app.config['SECRET_KEY'] = os.environ['SECRET_KEY']
app.secret_key = app.config['SECRET_KEY']
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Configure secure session cookies
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') == 'production'
app.config['SESSION_COOKIE_DOMAIN'] = None
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)


configure_database(app)


# Bootstrap and validation
def bootstrap_system():
    """Perform system bootstrap and validation on startup."""
    logger.info('🔧 Starting system bootstrap...')

    # Validate required environment variables
    required_vars = ['DATABASE_URL']
    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    if missing_vars:
        logger.error(f'❌ Missing required environment variables: {", ".join(missing_vars)}')
        logger.error('Please set these variables and restart the application.')
        return False

    # Check for weak secrets
    flask_secret = os.environ.get('FLASK_SECRET')
    if flask_secret and len(flask_secret) < 32:
        logger.warning('⚠️  FLASK_SECRET is shorter than 32 characters. Consider using a longer secret for better security.')

    admin_password_hash = os.environ.get('ADMIN_PASSWORD_HASH')
    if admin_password_hash and len(admin_password_hash) < 60:  # bcrypt hashes are ~60 chars
        logger.warning('⚠️  ADMIN_PASSWORD_HASH appears to be weak or incorrectly set.')

    # Check database connection
    try:
        db.engine.execute(text('SELECT 1'))
        logger.info('✅ Database connection successful')
    except Exception as e:
        logger.error(f'❌ Database connection failed: {e}')
        return False

    # Check and run pending migrations
    try:
        from flask_migrate import upgrade
        with app.app_context():
            # Check if alembic_version table exists
            inspector = sa_inspect(db.engine)
            if 'alembic_version' in inspector.get_table_names():
                logger.info('✅ Migration system initialized')
            else:
                logger.warning('⚠️  Migration system not initialized. Run `flask db upgrade` to apply migrations.')
    except Exception as e:
        logger.error(f'❌ Migration check failed: {e}')

    # Check if users table exists and has admin
    try:
        inspector = sa_inspect(db.engine)
        if 'users' in inspector.get_table_names():
            admin_count = User.query.filter_by(role='Admin', active=True).count()
            if admin_count == 0:
                logger.warning('⚠️  No active admin users found. System will run in setup mode.')
                logger.info('To create the first admin user, use the bootstrap endpoint or create manually.')
            else:
                logger.info(f'✅ Found {admin_count} active admin user(s)')
        else:
            logger.warning('⚠️  Users table not found. Run migrations or create tables.')
    except Exception as e:
        logger.error(f'❌ Error checking admin users: {e}')

    # Check if users table exists and has admin
    try:
        inspector = sa_inspect(db.engine)
        if 'users' in inspector.get_table_names():
            admin_count = User.query.filter_by(role='Admin', active=True).count()
            if admin_count == 0:
                logger.warning('⚠️  No active admin users found. System will run in setup mode.')
                logger.info('To create the first admin user, use the bootstrap endpoint or create manually.')
            else:
                logger.info(f'✅ Found {admin_count} active admin user(s)')
        else:
            logger.warning('⚠️  Users table not found. Run migrations or create tables.')

        # Initialize default config if config table exists
        if 'config' in inspector.get_table_names():
            initialize_default_config()
            logger.info('✅ Config initialized')
    except Exception as e:
        logger.error(f'❌ Error checking admin users: {e}')

    logger.info('✅ System bootstrap completed')
    return True


def initialize_default_config():
    """Initialize default configuration values."""
    defaults = {
        'platform_name': (PLATFORM_NAME, 'Global platform name'),
        'platform_domain': (PLATFORM_DOMAIN, 'Global platform domain'),
        'platform_tagline': (PLATFORM_TAGLINE, 'Global platform positioning'),
        'platform_cta': (PLATFORM_CTA, 'Global onboarding call to action'),
        'server_name': (PLATFORM_NAME, 'Legacy public alias for the platform name'),
        'server_id': ('platform', 'Unique identifier for this platform instance'),
        'departments': (DEFAULT_COMMUNITY_DEPARTMENTS, 'Available police departments for the default tenant'),
        'officer_ranks': (['Officer', 'Sergeant', 'Lieutenant', 'Captain', 'Chief'], 'Available officer ranks'),
        'penal_codes': ({
            '1.01': 'Reckless Driving',
            '1.02': 'Speeding',
            '2.01': 'Assault',
            '2.02': 'Battery',
            '3.01': 'Theft',
            '3.02': 'Burglary'
        }, 'Penal code definitions'),
        'call_types': (['Emergency', 'Non-Emergency', 'Traffic', 'Medical', 'Fire'], 'Available call types'),
        'vehicle_categories': (['Sedan', 'SUV', 'Truck', 'Motorcycle', 'Commercial'], 'Vehicle categories'),
        'evidence_categories': (['Physical', 'Digital', 'Witness', 'Surveillance'], 'Evidence categories'),
        'agency_names': ({
            'LSPD': 'Los Santos Police Department',
            'BCSO': 'Blaine County Sheriff\'s Office',
            'SWAT': 'Special Weapons and Tactics'
        }, 'Agency name mappings'),
        'default_officers': ([
            {'id': '1L-01', 'name': 'Chief Unit', 'status': 'Available', 'department': 'LSPD'},
            {'id': '2L-12', 'name': 'Patrol Unit', 'status': 'En Route', 'department': 'LSPD'},
            {'id': '3L-22', 'name': 'Traffic Unit', 'status': 'On Scene', 'department': 'Traffic Division'},
            {'id': 'D-04', 'name': 'Dispatch', 'status': 'Active', 'department': 'Dispatch'},
            {'id': 'K9-02', 'name': 'K9 Unit', 'status': 'Available', 'department': 'K9 Unit'},
            {'id': 'GU-01', 'name': 'Gang Unit 1', 'status': 'Available', 'department': 'Gang Enforcement'},
            {'id': 'GU-02', 'name': 'Gang Unit 2', 'status': 'Available', 'department': 'Gang Enforcement'},
            {'id': 'BCSO-1', 'name': 'BCSO Deputy 1', 'status': 'Available', 'department': 'BCSO'},
            {'id': 'BCSO-2', 'name': 'BCSO Deputy 2', 'status': 'Off Duty', 'department': 'BCSO'},
            {'id': 'SWT-1', 'name': 'SWAT Unit', 'status': 'Off Duty', 'department': 'SWAT'}
        ], 'Default officer units')
    }

    import json
    for key, (value, description) in defaults.items():
        config = Config.query.filter_by(key=key, community_id=None).first()
        serialized_value = json.dumps(value)
        if config:
            if config.value != serialized_value or config.description != description:
                config.value = serialized_value
                config.description = description
        else:
            config = Config(
                key=key,
                community_id=None,
                value=serialized_value,
                description=description
            )
            db.session.add(config)
    db.session.commit()


def get_config(key, default=None, community_id=None):
    """Get configuration value by key, preferring tenant config when supplied."""
    config = None
    if community_id:
        config = Config.query.filter_by(key=key, community_id=community_id).first()
    if not config:
        config = Config.query.filter_by(key=key, community_id=None).first()
    if config and config.value:
        import json
        try:
            return json.loads(config.value)
        except:
            return config.value
    return default

# Run bootstrap
if not bootstrap_system():
    logger.error('❌ Bootstrap failed. Application may not function correctly.')

# Initialize rate limiter
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

# Initialize cache
cache.init_app(app)

# Initialize Flask-Migrate
migrate = Migrate(app, db)

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode=os.environ.get('SOCKETIO_ASYNC_MODE', 'eventlet'),
    ping_interval=25,
    ping_timeout=60,
    manage_session=True,
)


def community_room_name(community_slug):
    return f"community:{community_slug}"


def get_user_room_context():
    user_id = session.get('user_id')
    community_id = get_current_community_id()
    if not user_id or not community_id:
        return None, None, None
    community = Community.query.filter_by(id=community_id).first()
    if not community:
        return None, None, None
    return user_id, community_id, community_room_name(community.slug)


def emit_community_event(event_name, payload, community_id=None):
    target_community_id = community_id or get_current_community_id()
    if not target_community_id:
        return
    community = Community.query.filter_by(id=target_community_id).first()
    if not community:
        return
    socketio.emit(event_name, payload, room=community_room_name(community.slug))


@socketio.on('connect')
def socket_connect(auth=None):
    sid = getattr(request, 'sid', None)
    user_id, community_id, room_name = get_user_room_context()
    if not user_id or not community_id or not room_name:
        logger.warning('Socket auth failed: missing user/session context')
        return False
    membership = CommunityMember.query.filter_by(user_id=user_id, community_id=community_id, is_active=True).first()
    if not membership:
        logger.warning(f'Socket auth failed: user {user_id} is not active in community {community_id}')
        return False
    existing_sid = ACTIVE_SOCKET_CONNECTIONS.get(user_id)
    if existing_sid and sid and existing_sid != sid:
        emit('socket:warning', {'message': 'Duplicate session detected; replacing older socket.'})
    if sid:
        ACTIVE_SOCKET_CONNECTIONS[user_id] = sid
    join_room(room_name)
    from cad_helpers import log_audit
    log_audit(str(user_id), 'websocket_join', 'Socket', sid or 'unknown', actor_role=session.get('role'), ip_address=request.remote_addr)
    emit('socket:ready', {'success': True, 'room': room_name, 'community_id': community_id})
    emit_community_event('presence:update', {'user_id': user_id, 'state': 'ONLINE', 'community_id': community_id}, community_id=community_id)


@socketio.on('disconnect')
def socket_disconnect():
    sid = getattr(request, 'sid', None)
    user_id, community_id, room_name = get_user_room_context()
    if room_name:
        leave_room(room_name)
    if user_id in ACTIVE_SOCKET_CONNECTIONS and ACTIVE_SOCKET_CONNECTIONS.get(user_id) == sid:
        ACTIVE_SOCKET_CONNECTIONS.pop(user_id, None)
    if user_id and community_id:
        from cad_helpers import log_audit
        log_audit(str(user_id), 'websocket_leave', 'Socket', sid or 'unknown', actor_role=session.get('role'), ip_address=request.remote_addr)
        emit_community_event('presence:update', {'user_id': user_id, 'state': 'OFFLINE', 'community_id': community_id}, community_id=community_id)


@socketio.on('community:join')
def socket_join_community(data):
    try:
        sid = getattr(request, 'sid', 'unknown')
        rate_key = f'{sid}:community:join'
        bucket = SOCKET_RATE_LIMITS.setdefault(rate_key, {'window': time.time(), 'count': 0})
        if time.time() - bucket['window'] > 60:
            bucket['window'] = time.time()
            bucket['count'] = 0
        bucket['count'] += 1
        if bucket['count'] > 30:
            return emit('socket:error', {'error': 'Rate limit exceeded'})

        if not isinstance(data, dict):
            return emit('socket:error', {'error': 'Invalid payload'})

        user_id, community_id, room_name = get_user_room_context()
        requested_slug = (data or {}).get('community_slug', '')
        if not user_id or not room_name:
            return emit('socket:error', {'error': 'Unauthorized'})
        if room_name != community_room_name(requested_slug):
            logger.warning(f"Tenant spoof attempt by user {user_id}: requested_slug={requested_slug}")
            return emit('socket:error', {'error': 'Invalid tenant room'})
        join_room(room_name)
        emit('community:joined', {'room': room_name, 'community_id': community_id, 'request_id': getattr(g, 'request_id', None)})
    except Exception as e:
        logger.exception(f'Websocket join failed: {e}')
        emit('socket:error', {'error': 'Unable to join room right now'})

from community_service import community_context_middleware, get_current_community_id, scoped_query
from community_routes import register_community_routes

@app.before_request
def inject_community_context():
    """Attach tenant context for /c/<slug> routes and selected community sessions."""
    g.request_id = request.headers.get('X-Request-ID') or str(uuid.uuid4())
    g.request_started_at = time.time()
    g.client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if request.path.startswith('/static/') or request.path.startswith('/assets/'):
        return None
    community_context_middleware()
    return None


@app.after_request
def enrich_response_metadata(response):
    response.headers['X-Request-ID'] = getattr(g, 'request_id', 'unknown')
    duration_ms = int((time.time() - getattr(g, 'request_started_at', time.time())) * 1000)
    if request.path.startswith('/api/'):
        logger.info(json.dumps({
            'event': 'api_request',
            'request_id': getattr(g, 'request_id', None),
            'path': request.path,
            'method': request.method,
            'status': response.status_code,
            'duration_ms': duration_ms,
            'ip': getattr(g, 'client_ip', request.remote_addr),
            'user_id': session.get('user_id'),
            'community_id': get_current_community_id(),
        }))
    return response

register_community_routes(app)
logger.info("✓ Community routes registered")


def current_role_allows_police_cad():
    """True when the active community role may access police CAD data/tools."""
    role = getattr(g, 'current_role', None) or session.get('role', 'Civilian')
    return role in {'Owner', 'Admin', 'Police', 'EMS', 'Dispatch', 'DOJ', 'Staff', 'LEO'}


def require_police_cad_access():
    if not current_role_allows_police_cad():
        return jsonify({'success': False, 'error': 'Police CAD access required'}), 403
    return None


@app.errorhandler(500)
def internal_error(error):
    """Handle internal server errors without exposing stack traces."""
    logger.error(f'Internal server error: {error}')
    return jsonify({
        'success': False,
        'error': 'Internal server error',
        'code': 'INTERNAL_ERROR'
    }), 500


@app.errorhandler(404)
def not_found_error(error):
    """Return JSON 404s only for API requests; let frontend paths render HTML."""
    if request.path.startswith('/api/'):
        return jsonify({
            'success': False,
            'error': 'Endpoint not found',
            'code': 'NOT_FOUND'
        }), 404

    requested_path = request.path.lstrip('/')
    if requested_path and requested_path.endswith('.html') and os.path.exists(os.path.join('.', requested_path)):
        return send_from_directory('.', requested_path)

    return send_from_directory('.', 'index.html')


@app.errorhandler(403)
def forbidden_error(error):
    """Handle 403 errors."""
    return jsonify({
        'success': False,
        'error': 'Forbidden',
        'code': 'FORBIDDEN'
    }), 403


@app.errorhandler(401)
def unauthorized_error(error):
    """Handle 401 errors."""
    return jsonify({
        'success': False,
        'error': 'Unauthorized',
        'code': 'UNAUTHORIZED'
    }), 401


@app.errorhandler(Exception)
def unhandled_exception(error):
    logger.exception(json.dumps({
        'event': 'unhandled_exception',
        'request_id': getattr(g, 'request_id', None),
        'path': request.path if request else None,
        'method': request.method if request else None,
        'user_id': session.get('user_id') if session else None,
        'community_id': get_current_community_id() if request else None,
        'error': str(error),
    }))
    if request.path.startswith('/api/'):
        return _safe_json_error('An unexpected error occurred.', 'UNEXPECTED_ERROR', 500)
    return send_from_directory('.', 'index.html')


def ensure_arrest_automation_schema():
    """Add columns needed by arrest-to-court automation on existing databases."""
    inspector = sa_inspect(db.engine)
    dialect = db.engine.dialect.name
    column_specs = {
        'arrests': {
            'arrest_id': 'VARCHAR(64)',
            'civilian_id': 'VARCHAR(64)',
            'suspect_name': 'VARCHAR(255)',
            'charges': 'TEXT',
            'arresting_officer': 'VARCHAR(255)',
            'arrest_location': 'VARCHAR(255)',
            'evidence_attached': 'TEXT',
            'penalty': 'VARCHAR(255)',
            'report_notes': 'TEXT',
            'narrative': 'TEXT',
            'status': 'VARCHAR(64)',
            'created_at': 'TIMESTAMP',
            'updated_at': 'TIMESTAMP',
        },
        'jail_bookings': {
            'booking_id': 'VARCHAR(64)',
            'civilian_id': 'VARCHAR(64)',
            'arrest_id': 'VARCHAR(64)',
            'suspect_name': 'VARCHAR(255)',
            'charges': 'TEXT',
            'booking_officer': 'VARCHAR(255)',
            'cell_assignment': 'VARCHAR(64)',
            'bond_amount': 'FLOAT',
            'sentence_length': 'VARCHAR(255)',
            'status': 'VARCHAR(64)',
            'release_date': 'TIMESTAMP',
            'released_by': 'VARCHAR(255)',
            'release_reason': 'TEXT',
            'notes': 'TEXT',
            'created_at': 'TIMESTAMP',
            'updated_at': 'TIMESTAMP',
        },
        'hearings': {
            'hearing_id': 'VARCHAR(64)',
            'civilian_id': 'VARCHAR(64)',
            'arrest_id': 'VARCHAR(64)',
            'suspect_name': 'VARCHAR(255)',
            'charges': 'TEXT',
            'hearing_type': 'VARCHAR(64)',
            'status': 'VARCHAR(64)',
            'filing_officer': 'VARCHAR(255)',
            'scheduled_at': 'VARCHAR(64)',
            'judge': 'VARCHAR(255)',
            'notes': 'TEXT',
            'outcome': 'TEXT',
            'sentence_length': 'VARCHAR(255)',
            'fine_amount': 'VARCHAR(255)',
            'outcome_notes': 'TEXT',
            'created_at': 'TIMESTAMP',
            'updated_at': 'TIMESTAMP',
        },
        'inmates': {
            'civilian_id': 'VARCHAR(64)',
        },
    }
    for table, columns in column_specs.items():
        try:
            existing = {col['name'] for col in inspector.get_columns(table)}
        except Exception:
            continue
        for column, col_type in columns.items():
            if column in existing:
                continue
            if dialect == 'postgresql':
                db.session.execute(text(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {col_type}'))
            else:
                db.session.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {col_type}'))
    db.session.commit()


def backfill_criminal_record_links():
    """Safely link legacy arrest/custody/court rows to civilians by arrest ID or full name."""
    dialect = db.engine.dialect.name
    try:
        if dialect == 'postgresql':
            statements = [
                """
                UPDATE arrests AS a
                SET civilian_id = c.civilian_id, updated_at = CURRENT_TIMESTAMP
                FROM civilians AS c
                WHERE COALESCE(NULLIF(TRIM(a.civilian_id), ''), '') = ''
                  AND LOWER(TRIM(a.suspect_name)) = LOWER(TRIM(CONCAT(c.first_name, ' ', c.last_name)))
                """,
                """
                UPDATE jail_bookings AS j
                SET civilian_id = a.civilian_id,
                    suspect_name = COALESCE(NULLIF(j.suspect_name, ''), a.suspect_name),
                    updated_at = CURRENT_TIMESTAMP
                FROM arrests AS a
                WHERE COALESCE(NULLIF(TRIM(j.civilian_id), ''), '') = ''
                  AND j.arrest_id = a.arrest_id
                  AND COALESCE(NULLIF(TRIM(a.civilian_id), ''), '') <> ''
                """,
                """
                UPDATE hearings AS h
                SET civilian_id = a.civilian_id,
                    suspect_name = COALESCE(NULLIF(h.suspect_name, ''), a.suspect_name),
                    updated_at = CURRENT_TIMESTAMP
                FROM arrests AS a
                WHERE COALESCE(NULLIF(TRIM(h.civilian_id), ''), '') = ''
                  AND h.arrest_id = a.arrest_id
                  AND COALESCE(NULLIF(TRIM(a.civilian_id), ''), '') <> ''
                """,
                """
                UPDATE jail_bookings AS j
                SET civilian_id = c.civilian_id, updated_at = CURRENT_TIMESTAMP
                FROM civilians AS c
                WHERE COALESCE(NULLIF(TRIM(j.civilian_id), ''), '') = ''
                  AND LOWER(TRIM(j.suspect_name)) = LOWER(TRIM(CONCAT(c.first_name, ' ', c.last_name)))
                """,
                """
                UPDATE hearings AS h
                SET civilian_id = c.civilian_id, updated_at = CURRENT_TIMESTAMP
                FROM civilians AS c
                WHERE COALESCE(NULLIF(TRIM(h.civilian_id), ''), '') = ''
                  AND LOWER(TRIM(h.suspect_name)) = LOWER(TRIM(CONCAT(c.first_name, ' ', c.last_name)))
                """,
                "UPDATE jail_bookings SET bond_amount = NULL WHERE bond_amount::text = 'Pending'",
            ]
        else:
            statements = [
                """
                UPDATE arrests
                SET civilian_id = (
                    SELECT civilians.civilian_id FROM civilians
                    WHERE LOWER(TRIM(arrests.suspect_name)) = LOWER(TRIM(civilians.first_name || ' ' || civilians.last_name))
                    LIMIT 1
                ), updated_at = CURRENT_TIMESTAMP
                WHERE COALESCE(TRIM(civilian_id), '') = ''
                  AND EXISTS (
                    SELECT 1 FROM civilians
                    WHERE LOWER(TRIM(arrests.suspect_name)) = LOWER(TRIM(civilians.first_name || ' ' || civilians.last_name))
                  )
                """,
                """
                UPDATE jail_bookings
                SET civilian_id = (
                    SELECT arrests.civilian_id FROM arrests
                    WHERE arrests.arrest_id = jail_bookings.arrest_id AND COALESCE(TRIM(arrests.civilian_id), '') <> ''
                    LIMIT 1
                ), updated_at = CURRENT_TIMESTAMP
                WHERE COALESCE(TRIM(civilian_id), '') = ''
                  AND EXISTS (SELECT 1 FROM arrests WHERE arrests.arrest_id = jail_bookings.arrest_id AND COALESCE(TRIM(arrests.civilian_id), '') <> '')
                """,
                """
                UPDATE hearings
                SET civilian_id = (
                    SELECT arrests.civilian_id FROM arrests
                    WHERE arrests.arrest_id = hearings.arrest_id AND COALESCE(TRIM(arrests.civilian_id), '') <> ''
                    LIMIT 1
                ), updated_at = CURRENT_TIMESTAMP
                WHERE COALESCE(TRIM(civilian_id), '') = ''
                  AND EXISTS (SELECT 1 FROM arrests WHERE arrests.arrest_id = hearings.arrest_id AND COALESCE(TRIM(arrests.civilian_id), '') <> '')
                """,
            ]
        for statement in statements:
            db.session.execute(text(statement))
        db.session.commit()
        logger.info('✓ Criminal record link backfill completed')
    except Exception as e:
        db.session.rollback()
        logger.warning(f'Criminal record link backfill skipped: {e}')

# Initialize database on startup
with app.app_context():
    try:
        db.create_all()
        ensure_arrest_automation_schema()
        backfill_criminal_record_links()
        logger.info('✓ Database tables verified on startup')
    except Exception as e:
        logger.error(f'Database initialization error: {e}')

# Ensure schema is synced on startup
try:
    from database import verify_schema
    verify_schema(app)
except Exception as e:
    logger.warning(f'Schema verification on startup: {e}')

DEFAULT_OFFICERS = [
    {'id': '1L-01',  'name': 'Chief Unit',      'status': 'Available', 'department': 'LSPD'},
    {'id': '2L-12',  'name': 'Patrol Unit',     'status': 'En Route',  'department': 'LSPD'},
    {'id': '3L-22',  'name': 'Traffic Unit',    'status': 'On Scene',  'department': 'Traffic Division'},
    {'id': 'D-04',   'name': 'Dispatch',        'status': 'Active',    'department': 'Dispatch'},
    {'id': 'K9-02',  'name': 'K9 Unit',         'status': 'Available', 'department': 'K9 Unit'},
    {'id': 'GU-01',  'name': 'Gang Unit 1',     'status': 'Available', 'department': 'Gang Enforcement'},
    {'id': 'GU-02',  'name': 'Gang Unit 2',     'status': 'Available', 'department': 'Gang Enforcement'},
    {'id': 'BCSO-1', 'name': 'BCSO Deputy 1',   'status': 'Available', 'department': 'BCSO'},
    {'id': 'BCSO-2', 'name': 'BCSO Deputy 2',   'status': 'Off Duty',  'department': 'BCSO'},
    {'id': 'SWT-1',  'name': 'SWAT Unit',       'status': 'Off Duty',  'department': 'SWAT'},
]


# ---------------------------------------------------------------------------
# Helper: convert model instances to dicts matching the original JSON shape
# ---------------------------------------------------------------------------

def bolo_to_dict(b):
    return {
        'id': b.bolo_id,
        'suspectName': b.suspect_name,
        'description': b.description,
        'lastLocation': b.last_location,
        'vehicle': b.vehicle or '',
        'charges': b.charges or '',
        'threatLevel': b.threat_level,
        'issuedBy': b.issued_by,
        'issuedAt': b.created_at.isoformat() if b.created_at else None,
        'status': b.status,
        'autoGenerated': b.auto_generated or False,
    }


def complaint_to_dict(c):
    return {
        'id': c.complaint_id,
        'complaintDiscord': c.complaint_discord,
        'reportedName': c.reported_name,
        'complaintType': c.complaint_type,
        'incidentDate': c.incident_date,
        'incidentLocation': c.incident_location,
        'witnesses': c.witnesses,
        'evidenceLink': c.evidence_link,
        'description': c.description,
        'resolution': c.resolution,
        'status': c.status,
        'staffNotes': c.staff_notes or '',
        'submittedAt': c.submitted_at.isoformat() if c.submitted_at else None,
        'updatedAt': c.updated_at.isoformat() if c.updated_at else None,
    }


def application_to_dict(a):
    return {
        'id': a.application_id,
        'appDiscord': a.app_discord,
        'appCharacter': a.app_character,
        'applicationType': a.application_type,
        'ageConfirmation': a.age_confirmation,
        'experience': a.experience,
        'roleReason': a.role_reason,
        'availability': a.availability,
        'status': a.status,
        'staffNotes': a.staff_notes or '',
        'submittedAt': a.submitted_at.isoformat() if a.submitted_at else None,
        'updatedAt': a.updated_at.isoformat() if a.updated_at else None,
    }


def session_to_dict(s):
    officer_name = s.officer_name or ''
    return {
        'callsign': s.callsign,
        'name': officer_name,
        'officerName': officer_name,
        'department': s.department or 'LSPD',
        'loggedInAt': s.logged_in_at.isoformat() if s.logged_in_at else None,
        'updatedAt': s.updated_at.isoformat() if s.updated_at else None,
        'status': s.status or 'On Duty',
    }


def officer_session_response(s):
    return {
        'callsign': s.callsign,
        'officerName': s.officer_name or '',
        'department': s.department or '',
        'status': s.status or 'On Duty',
    }


def ensure_officer_sessions_schema():
    """Safely add any missing officer session columns before CAD login queries."""
    if db.engine.dialect.name != 'postgresql':
        db.create_all()
        return

    statements = [
        """
        CREATE TABLE IF NOT EXISTS officer_sessions (
            id SERIAL PRIMARY KEY,
            callsign VARCHAR(64) UNIQUE NOT NULL,
            officer_name VARCHAR(255),
            department VARCHAR(255) DEFAULT 'LSPD',
            status VARCHAR(64) DEFAULT 'On Duty',
            logged_in_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        "ALTER TABLE officer_sessions ADD COLUMN IF NOT EXISTS id SERIAL",
        "ALTER TABLE officer_sessions ADD COLUMN IF NOT EXISTS callsign VARCHAR(64)",
        "ALTER TABLE officer_sessions ADD COLUMN IF NOT EXISTS officer_name VARCHAR(255)",
        "ALTER TABLE officer_sessions ADD COLUMN IF NOT EXISTS department VARCHAR(255) DEFAULT 'LSPD'",
        "ALTER TABLE officer_sessions ADD COLUMN IF NOT EXISTS status VARCHAR(64) DEFAULT 'On Duty'",
        "ALTER TABLE officer_sessions ADD COLUMN IF NOT EXISTS logged_in_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE officer_sessions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    ]

    try:
        with db.engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))
    except Exception as e:
        logger.error(f'officer_sessions schema sync failed: {e}')
        raise


def alert_to_dict(a):
    return {
        'id': a.alert_id,
        'type': a.alert_type,
        'message': a.message,
        'issuedBy': a.issued_by,
        'issuedAt': a.created_at.isoformat() if a.created_at else None,
    }


def radio_to_dict(r):
    return {
        'id': r.log_id,
        'unit': r.unit,
        'channel': r.channel,
        'message': r.message,
        'timestamp': r.created_at.isoformat() if r.created_at else None,
    }


def status_to_dict(s):
    return {
        'cityStatus': s.city_status,
        'playerCount': s.player_count,
        'maxPlayers': s.max_players,
        'customMessage': s.custom_message,
        'lastUpdated': s.last_updated.isoformat() if s.last_updated else None,
    }



PENDING_SENTENCE = 'Pending Court Hearing'
PENDING_FINE = 'Pending'
AUTO_HEARING_NOTE = 'Automatically scheduled after arrest booking.'


def _default_hearing_time():
    """Return a deterministic default arraignment time for arrest automation."""
    scheduled = datetime.utcnow() + timedelta(days=1)
    scheduled = scheduled.replace(hour=9, minute=0, second=0, microsecond=0)
    return scheduled.isoformat()


def _parse_fine_amount(value):
    if value in (None, ''):
        return None
    try:
        return float(str(value).replace('$', '').replace(',', '').strip())
    except (TypeError, ValueError):
        return None


def _normalize_name(value):
    return ' '.join(str(value or '').strip().lower().split())


def _civilian_full_name(civilian):
    return f'{civilian.first_name or ""} {civilian.last_name or ""}'.strip()


def _same_person_name_filter(column, civilian):
    full_name = _civilian_full_name(civilian)
    first = (civilian.first_name or '').strip()
    last = (civilian.last_name or '').strip()
    filters = []
    if full_name:
        filters.append(column == full_name)
        filters.append(sqlalchemy.func.lower(column) == full_name.lower())
    if first and last:
        filters.append(sqlalchemy.and_(column.ilike(f'%{first}%'), column.ilike(f'%{last}%')))
    return sqlalchemy.or_(*filters) if filters else sqlalchemy.false()


def _civilian_related_history_exists(civilian):
    """Fast profile-card check for any criminal/CAD history tied to a civilian."""
    if not civilian:
        return False

    civilian_id = civilian.civilian_id or ''
    name_filter = _same_person_name_filter
    full_name = _civilian_full_name(civilian)
    first = (civilian.first_name or '').strip()
    last = (civilian.last_name or '').strip()

    community_id = civilian.community_id or get_current_community_id()
    arrest_query = scoped_query(Arrest, community_id).filter(sqlalchemy.or_(
        Arrest.civilian_id == civilian_id,
        name_filter(Arrest.suspect_name, civilian),
    ))
    if arrest_query.first():
        return True

    arrest_ids = [row[0] for row in arrest_query.with_entities(Arrest.arrest_id).all() if row[0]]
    if scoped_query(JailBooking, community_id).filter(sqlalchemy.or_(
        JailBooking.civilian_id == civilian_id,
        JailBooking.arrest_id.in_(arrest_ids) if arrest_ids else sqlalchemy.false(),
        name_filter(JailBooking.suspect_name, civilian),
    )).first():
        return True
    if scoped_query(Hearing, community_id).filter(sqlalchemy.or_(
        Hearing.civilian_id == civilian_id,
        Hearing.arrest_id.in_(arrest_ids) if arrest_ids else sqlalchemy.false(),
        name_filter(Hearing.suspect_name, civilian),
    )).first():
        return True
    if scoped_query(Warrant, community_id).filter(sqlalchemy.or_(
        Warrant.civilian_id == civilian_id,
        name_filter(Warrant.warrant_name, civilian),
    )).first():
        return True
    if scoped_query(Citation, community_id).filter(Citation.civilian_id == civilian_id).first():
        return True

    traffic_filters = []
    if full_name:
        traffic_filters.extend([TrafficStop.driver_name == full_name, sqlalchemy.func.lower(TrafficStop.driver_name) == full_name.lower()])
    if first and last:
        traffic_filters.append(sqlalchemy.and_(TrafficStop.driver_name.ilike(f'%{first}%'), TrafficStop.driver_name.ilike(f'%{last}%')))
    if civilian.plate_number:
        traffic_filters.append(TrafficStop.plate.ilike(civilian.plate_number))
    return scoped_query(TrafficStop, community_id).filter(sqlalchemy.or_(*traffic_filters) if traffic_filters else sqlalchemy.false()).first() is not None


def _find_civilian_for_arrest(civilian_id='', suspect_name=''):
    """Resolve an arrest to a civilian by explicit ID first, then case-insensitive full name."""
    civilian_id = (civilian_id or '').strip()
    if civilian_id:
        match = scoped_query(Civilian).filter(Civilian.civilian_id == civilian_id).first()
        if match:
            return match

    normalized_name = _normalize_name(suspect_name)
    if not normalized_name:
        return None

    for civilian in scoped_query(Civilian).all():
        full_name = _normalize_name(f'{civilian.first_name or ""} {civilian.last_name or ""}')
        if full_name == normalized_name:
            return civilian
    return None


def _apply_arrest_payload(arrest, data):
    civilian = _find_civilian_for_arrest(
        data.get('civilianId') or data.get('civilian_id') or arrest.civilian_id,
        data.get('suspectName') or data.get('suspect_name') or arrest.suspect_name,
    )
    arrest.civilian_id = civilian.civilian_id if civilian else (data.get('civilianId') or data.get('civilian_id') or arrest.civilian_id or '')
    arrest.suspect_name = (data.get('suspectName') or data.get('suspect_name') or arrest.suspect_name or '').strip()
    arrest.charges = (data.get('charges') or arrest.charges or '').strip()
    arrest.arresting_officer = (data.get('arrestingOfficer') or data.get('arresting_officer') or arrest.arresting_officer or '').strip()
    arrest.arrest_location = (data.get('arrestLocation') or data.get('arrest_location') or arrest.arrest_location or '').strip()
    arrest.evidence_attached = (data.get('evidenceAttached') or data.get('evidence_attached') or arrest.evidence_attached or '').strip()
    arrest.penalty = (data.get('penalty') or arrest.penalty or '').strip()
    arrest.report_notes = (data.get('reportNotes') or data.get('report_notes') or arrest.report_notes or '').strip()
    arrest.narrative = (data.get('narrative') or arrest.narrative or '').strip()
    arrest.status = (data.get('status') or arrest.status or 'Active').strip()
    arrest.updated_at = datetime.utcnow()
    return civilian


def _compose_arrest_notes(arrest):
    summary = (arrest.report_notes or arrest.narrative or '').strip()
    if not summary:
        return 'Automatically booked after arrest submission.'
    return f'Automatically booked after arrest submission. Arrest summary: {summary}'


def _ensure_arrest_custody_and_hearing(arrest):
    """Create the linked custody booking and court hearing for a new arrest once."""
    if not arrest or not arrest.arrest_id:
        return None, None, None

    if not arrest.civilian_id:
        civilian = _find_civilian_for_arrest('', arrest.suspect_name)
        if civilian:
            arrest.civilian_id = civilian.civilian_id
            logger.info(f'Arrest {arrest.arrest_id} linked to civilian {civilian.civilian_id} by suspect name')

    community_id = arrest.community_id or get_current_community_id()
    inmate = scoped_query(Inmate, community_id).filter_by(arrest_id=arrest.arrest_id).first()
    if inmate is None:
        ts = int(datetime.utcnow().timestamp() * 1000)
        inmate = Inmate(
            community_id=community_id,
            inmate_id=f'inmate-{ts}-{secrets.token_hex(4)}',
            civilian_id=arrest.civilian_id or '',
            suspect_name=arrest.suspect_name or '',
            charges=arrest.charges or '',
            penalty=PENDING_SENTENCE,
            cell='',
            booked_by=arrest.arresting_officer or 'Unknown',
            arrest_id=arrest.arrest_id,
            estimated_release='',
            notes=f'{_compose_arrest_notes(arrest)} Fine: {PENDING_FINE}. Court Hearing: Scheduled.',
            status='In Custody',
            booked_at=datetime.utcnow(),
        )
        db.session.add(inmate)
        logger.info(f'Jail tracker inmate auto-created for arrest {arrest.arrest_id}')
    else:
        if not inmate.civilian_id and arrest.civilian_id:
            inmate.civilian_id = arrest.civilian_id
        if not inmate.suspect_name and arrest.suspect_name:
            inmate.suspect_name = arrest.suspect_name
        if not inmate.charges and arrest.charges:
            inmate.charges = arrest.charges
        logger.info(f'Duplicate inmate booking prevented for arrest {arrest.arrest_id}')

    booking = scoped_query(JailBooking, community_id).filter_by(arrest_id=arrest.arrest_id).first()
    if booking is None:
        ts = int(datetime.utcnow().timestamp() * 1000)
        booking = JailBooking(
            community_id=community_id,
            booking_id=f'booking-{ts}-{secrets.token_hex(4)}',
            civilian_id=arrest.civilian_id or '',
            arrest_id=arrest.arrest_id,
            suspect_name=arrest.suspect_name or '',
            charges=arrest.charges or '',
            booking_officer=arrest.arresting_officer or 'Unknown',
            cell_assignment='',
            bond_amount=None,
            sentence_length=PENDING_SENTENCE,
            status='In Custody',
            notes=f'{_compose_arrest_notes(arrest)} Fine: {PENDING_FINE}. Court Hearing: Scheduled.',
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.session.add(booking)
        logger.info(f'Jail booking auto-created for arrest {arrest.arrest_id}')
    else:
        if not booking.civilian_id and arrest.civilian_id:
            booking.civilian_id = arrest.civilian_id
        if not booking.suspect_name and arrest.suspect_name:
            booking.suspect_name = arrest.suspect_name
        if not booking.charges and arrest.charges:
            booking.charges = arrest.charges
        if not booking.arrest_id and arrest.arrest_id:
            booking.arrest_id = arrest.arrest_id
        if booking.bond_amount == 'Pending':
            booking.bond_amount = None
        booking.updated_at = datetime.utcnow()
        logger.info(f'Duplicate jail booking prevented for arrest {arrest.arrest_id}')

    hearing = scoped_query(Hearing, community_id).filter_by(arrest_id=arrest.arrest_id).first()
    if hearing is None:
        ts = int(datetime.utcnow().timestamp() * 1000)
        hearing = Hearing(
            community_id=community_id,
            hearing_id=f'hearing-{ts}-{secrets.token_hex(5)}',
            civilian_id=arrest.civilian_id or '',
            suspect_name=arrest.suspect_name or '',
            charges=arrest.charges or '',
            hearing_type='Arraignment',
            scheduled_at=_default_hearing_time(),
            judge='',
            notes=AUTO_HEARING_NOTE,
            arrest_id=arrest.arrest_id,
            filing_officer=arrest.arresting_officer or 'Unknown',
            outcome='',
            sentence_length='',
            fine_amount='',
            outcome_notes='',
            status='Scheduled',
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.session.add(hearing)
        logger.info(f'Court hearing auto-created for arrest {arrest.arrest_id}')
    else:
        if not hearing.civilian_id and arrest.civilian_id:
            hearing.civilian_id = arrest.civilian_id
        if not hearing.suspect_name and arrest.suspect_name:
            hearing.suspect_name = arrest.suspect_name
        if not hearing.charges and arrest.charges:
            hearing.charges = arrest.charges
        if not hearing.arrest_id and arrest.arrest_id:
            hearing.arrest_id = arrest.arrest_id
        hearing.updated_at = datetime.utcnow()
        logger.info(f'Duplicate court hearing prevented for arrest {arrest.arrest_id}')

    return inmate, booking, hearing

def _sync_custody_from_completed_hearing(hearing):
    """Apply a completed/continued hearing result to linked jail records."""
    if not hearing or not hearing.arrest_id:
        return
    normalized = (hearing.outcome or '').strip().lower()
    completed = (hearing.status or '').strip().lower() in {'completed', 'dismissed', 'continued'}
    if not completed and normalized not in {'dismissed', 'not guilty', 'continued'}:
        return

    community_id = hearing.community_id or get_current_community_id()
    booking = scoped_query(JailBooking, community_id).filter_by(arrest_id=hearing.arrest_id).first()
    inmate = scoped_query(Inmate, community_id).filter_by(arrest_id=hearing.arrest_id).first()
    arrest = scoped_query(Arrest, community_id).filter_by(arrest_id=hearing.arrest_id).first()

    if normalized in {'dismissed', 'not guilty'}:
        if booking:
            booking.status = 'Released'
            booking.sentence_length = 'Dismissed'
            booking.bond_amount = None
            booking.release_date = datetime.utcnow()
            booking.release_reason = f'Hearing outcome: {hearing.outcome}'
            booking.updated_at = datetime.utcnow()
        if inmate:
            inmate.status = 'Released'
            inmate.penalty = 'Dismissed'
            inmate.released_at = datetime.utcnow()
            inmate.released_by = 'Court System'
            inmate.release_reason = f'Hearing outcome: {hearing.outcome}'
            inmate.updated_at = datetime.utcnow()
        if arrest:
            arrest.status = 'Closed - Released'
            arrest.penalty = hearing.outcome or 'Dismissed'
            arrest.updated_at = datetime.utcnow()
        logger.info(f'Court completion released custody for arrest {hearing.arrest_id}')
        return

    if normalized == 'continued':
        if booking:
            booking.status = 'In Custody'
            booking.sentence_length = PENDING_SENTENCE
            booking.bond_amount = None
            booking.updated_at = datetime.utcnow()
        if inmate:
            inmate.status = 'In Custody'
            inmate.penalty = PENDING_SENTENCE
            inmate.updated_at = datetime.utcnow()
        if arrest:
            arrest.status = 'Continued'
            arrest.updated_at = datetime.utcnow()
        logger.info(f'Court completion continued pending custody for arrest {hearing.arrest_id}')
        return

    if normalized in {'guilty', 'sentenced', 'no contest'} or completed:
        sentence = (hearing.sentence_length or '').strip() or PENDING_SENTENCE
        fine = _parse_fine_amount(hearing.fine_amount)
        if booking:
            booking.status = 'In Custody'
            booking.sentence_length = sentence
            booking.bond_amount = fine
            booking.updated_at = datetime.utcnow()
        if inmate:
            inmate.status = 'In Custody'
            inmate.penalty = sentence
            inmate.updated_at = datetime.utcnow()
        if arrest:
            arrest.status = 'Sentenced'
            arrest.penalty = sentence
            arrest.updated_at = datetime.utcnow()
        logger.info(f'Court completion applied sentence for arrest {hearing.arrest_id}')

def inmate_to_dict(i):
    return {
        'id': i.inmate_id,
        'civilianId': i.civilian_id or '',
        'suspectName': i.suspect_name,
        'charges': i.charges or '',
        'penalty': i.penalty or '',
        'sentenceLength': i.penalty or '',
        'fineAmount': PENDING_FINE if (i.penalty == PENDING_SENTENCE and i.status == 'In Custody') else '',
        'courtHearingStatus': 'Scheduled' if (i.penalty == PENDING_SENTENCE and i.status == 'In Custody') else '',
        'cell': i.cell or '',
        'bookedBy': i.booked_by,
        'arrestId': i.arrest_id or '',
        'estimatedRelease': i.estimated_release or '',
        'notes': i.notes or '',
        'status': i.status,
        'bookedAt': (i.booked_at.isoformat() + 'Z') if i.booked_at else None,
        'releasedAt': (i.released_at.isoformat() + 'Z') if i.released_at else None,
        'releasedBy': i.released_by or '',
        'releaseReason': i.release_reason or '',
        'updatedAt': (i.updated_at.isoformat() + 'Z') if i.updated_at else None,
    }


def _display_hearing_type(value):
    hearing_type = (value or 'Arraignment').strip()
    if hearing_type.lower() == 'arrigment':
        return 'Arraignment'
    return hearing_type


def hearing_to_dict(h):
    return {
        'id': h.hearing_id,
        'civilianId': h.civilian_id or '',
        'suspectName': h.suspect_name,
        'charges': h.charges or '',
        'hearingType': _display_hearing_type(h.hearing_type),
        'scheduledAt': h.scheduled_at or '',
        'judge': h.judge or '',
        'notes': h.notes or '',
        'arrestId': h.arrest_id or '',
        'filingOfficer': h.filing_officer or '',
        'outcome': h.outcome or '',
        'sentenceLength': h.sentence_length or '',
        'fineAmount': h.fine_amount or '',
        'outcomeNotes': h.outcome_notes or '',
        'status': h.status,
        'createdAt': (h.created_at.isoformat() + 'Z') if h.created_at else None,
        'updatedAt': (h.updated_at.isoformat() + 'Z') if h.updated_at else None,
    }


def civilian_to_dict(c):
    return _civilian_response(c)


def vehicle_to_dict(v):
    return {
        'plate': v.plate,
        'ownerName': v.owner_name or '',
        'model': v.model or '',
        'color': v.color or '',
        'registrationStatus': v.registration_status or 'Valid',
    }


def license_to_dict(l):
    return {
        'id': l.license_id,
        'ownerName': l.owner_name or '',
        'licenseType': l.license_type or '',
        'status': l.status or 'Valid',
        'issuedDate': l.issued_date or '',
        'expiryDate': l.expiry_date or '',
        'notes': l.notes or '',
    }

  
def warrant_to_dict(w):
    return {
        'id': w.warrant_id,
        'warrantName': w.warrant_name or '',
        'warrantCharges': w.warrant_charges or '',
        'warrantIssuer': w.warrant_issuer or '',
        'warrantNotes': w.warrant_notes or '',
        'warrantStatus': w.warrant_status or 'Active',
        'expirationDate': w.expiration_date or '',
        'justification': w.justification or '',
        'createdAt': w.created_at.isoformat() if w.created_at else None,
    }


def arrest_to_dict(a):
    return {
        'id': a.arrest_id,
        'civilianId': a.civilian_id or '',
        'suspectName': a.suspect_name or '',
        'charges': a.charges or '',
        'arrestingOfficer': a.arresting_officer or '',
        'arrestLocation': a.arrest_location or '',
        'evidenceAttached': a.evidence_attached or '',
        'penalty': a.penalty or '',
        'reportNotes': a.report_notes or '',
        'narrative': a.narrative or '',
        'status': a.status or 'Active',
        'createdAt': a.created_at.isoformat() if a.created_at else None,
    }


def incident_to_dict(i):
    return {
        'id': i.incident_id,
        'incidentType': i.incident_type or '',
        'location': i.location or '',
        'description': i.description or '',
        'officersInvolved': i.officers_involved or '',
        'suspects': i.suspects or '',
        'status': i.status or 'Open',
        'priority': i.priority or 'Medium',
        'notes': i.notes or '',
        'createdAt': i.created_at.isoformat() if i.created_at else None,
    }


def evidence_to_dict(e):
    return {
        'id': e.evidence_id,
        'caseNumber': e.case_number or '',
        'evidenceDescription': e.evidence_description or '',
        'collectedBy': e.collected_by or '',
        'locationFound': e.location_found or '',
        'status': e.status or 'Active',
        'notes': e.notes or '',
        'createdAt': e.created_at.isoformat() if e.created_at else None,
    }


def traffic_stop_to_dict(t):
    return {
        'id': t.stop_id,
        'driverName': t.driver_name or '',
        'trafficPlate': t.plate or '',
        'plate': t.plate or '',
        'trafficReason': t.reason or '',
        'reason': t.reason or '',
        'trafficOutcome': t.outcome or '',
        'outcome': t.outcome or '',
        'officer': t.officer or '',
        'location': t.location or '',
        'notes': t.notes or '',
        'createdAt': t.created_at.isoformat() if t.created_at else None,
    }

def citation_to_dict(c):
    return {
        'id': c.citation_id,
        'civilianId': c.civilian_id or '',
        'issuingOfficer': c.issuing_officer or '',
        'violation': c.violation or '',
        'location': c.location or '',
        'fineAmount': c.fine_amount,
        'status': c.status or 'Issued',
        'notes': c.notes or '',
        'createdAt': c.created_at.isoformat() if c.created_at else None,
    }


def jail_booking_to_dict(j):
    return {
        'id': j.booking_id,
        'civilianId': j.civilian_id or '',
        'arrestId': j.arrest_id or '',
        'suspectName': j.suspect_name or '',
        'charges': j.charges or '',
        'bookingOfficer': j.booking_officer or '',
        'cellAssignment': j.cell_assignment or '',
        'bondAmount': PENDING_FINE if j.sentence_length == PENDING_SENTENCE else (j.bond_amount if j.bond_amount is not None else ''),
        'fineAmount': PENDING_FINE if j.sentence_length == PENDING_SENTENCE else (j.bond_amount if j.bond_amount is not None else ''),
        'sentenceLength': j.sentence_length or '',
        'status': j.status or 'Booked',
        'releaseDate': j.release_date.isoformat() if j.release_date else None,
        'releasedBy': j.released_by or '',
        'releaseReason': j.release_reason or '',
        'notes': j.notes or '',
        'createdAt': j.created_at.isoformat() if j.created_at else None,
    }



def call911_to_dict(c):
    return {
        'id': c.call_id,
        'callerName': c.caller_name or '',
        'location': c.location or '',
        'description': c.description or '',
        'incidentType': c.incident_type or '',
        'priority': c.priority or 'Medium',
        'assignedUnit': c.assigned_unit or '',
        'status': c.status or 'New',
        'dispatchNotes': c.dispatch_notes or '',
        'createdAt': c.created_at.isoformat() if c.created_at else None,
    }


def activity_log_to_dict(a):
    return {
        'id': a.log_id,
        'action': a.action or '',
        'officer': a.officer or '',
        'details': a.details or '',
        'timestamp': a.created_at.isoformat() if a.created_at else None,
    }



# ---------------------------------------------------------------------------
# Civilian PostgreSQL source-of-truth helpers
# ---------------------------------------------------------------------------

def _pick(data, *keys, default=''):
    """Return the first present, non-None payload value from frontend or DB-style keys."""
    for key in keys:
        if key in data and data.get(key) is not None:
            return data.get(key)
    return default


def _parse_date(value):
    if not value:
        return None
    if hasattr(value, 'isoformat') and not isinstance(value, str):
        return value
    try:
        return datetime.strptime(str(value), '%Y-%m-%d').date()
    except ValueError:
        return None


def _civilian_from_payload(data):
    """Map Civilian Registration form fields onto PostgreSQL Civilian columns."""
    vehicle_year = _pick(data, 'vehicleYear', 'vehicle_year', default=None)
    if vehicle_year in ('', None):
        vehicle_year = None
    else:
        try:
            vehicle_year = int(vehicle_year)
        except (TypeError, ValueError):
            vehicle_year = None

    return {
        'first_name': str(_pick(data, 'firstName', 'first_name')).strip(),
        'last_name': str(_pick(data, 'lastName', 'last_name')).strip(),
        'date_of_birth': _parse_date(_pick(data, 'dob', 'date_of_birth', default=None)),
        'gender': _pick(data, 'gender'),
        'phone_number': _pick(data, 'phone', 'phone_number'),
        'address': _pick(data, 'address'),
        'occupation': _pick(data, 'occupation'),
        'gang_affiliation': _pick(data, 'faction', 'gang_affiliation', default='None') or 'None',
        'emergency_contact_name': _pick(data, 'emergencyName', 'emergency_contact_name'),
        'emergency_contact_phone': _pick(data, 'emergencyPhone', 'emergency_contact_phone'),
        'driver_license_status': _pick(data, 'driverLicense', 'driver_license_status', default='Valid') or 'Valid',
        'firearm_license_status': _pick(data, 'firearmLicense', 'firearm_license_status', default='None') or 'None',
        'business_license_status': _pick(data, 'businessLicense', 'business_license_status', default='None') or 'None',
        'vehicle_make': _pick(data, 'vehicleMake', 'vehicle_make'),
        'vehicle_model': _pick(data, 'vehicleModel', 'vehicle_model'),
        'vehicle_year': vehicle_year,
        'vehicle_color': _pick(data, 'vehicleColor', 'vehicle_color'),
        'plate_number': _pick(data, 'plate', 'plate_number'),
        'insurance_status': _pick(data, 'insurance', 'insurance_status', default='Valid') or 'Valid',
        'criminal_background_notes': _pick(data, 'background', 'criminal_background_notes'),
        'character_backstory': _pick(data, 'backstory', 'character_backstory'),
    }


def _civilian_response(c):
    base = c.to_dict()
    base.update({
        'id': c.civilian_id,
        'name': f'{c.first_name or ""} {c.last_name or ""}'.strip(),
        'firstName': c.first_name or '',
        'lastName': c.last_name or '',
        'dob': c.date_of_birth.isoformat() if c.date_of_birth else '',
        'phone': c.phone_number or '',
        'faction': c.gang_affiliation or 'None',
        'emergencyName': c.emergency_contact_name or '',
        'emergencyPhone': c.emergency_contact_phone or '',
        'driverLicense': c.driver_license_status or 'Valid',
        'firearmLicense': c.firearm_license_status or 'None',
        'businessLicense': c.business_license_status or 'None',
        'vehicleMake': c.vehicle_make or '',
        'vehicleModel': c.vehicle_model or '',
        'vehicleYear': c.vehicle_year,
        'vehicleColor': c.vehicle_color or '',
        'plate': c.plate_number or '',
        'insurance': c.insurance_status or 'Valid',
        'background': c.criminal_background_notes or '',
        'backstory': c.character_backstory or '',
        'hasCriminalHistory': _civilian_related_history_exists(c),
    })
    return base


def _civilian_search_query(query, name=None, dob=None):
    q = (query or '').strip()
    name = (name or '').strip()
    dob = (dob or '').strip()
    db_query = scoped_query(Civilian)

    if name:
        db_query = db_query.filter(_civilian_name_filter(name))
    if dob:
        parsed_dob = _parse_date(dob)
        if parsed_dob:
            db_query = db_query.filter(Civilian.date_of_birth == parsed_dob)
    if q:
        filters = [
            Civilian.first_name.ilike(f'%{q}%'),
            Civilian.last_name.ilike(f'%{q}%'),
            Civilian.civilian_id.ilike(f'%{q}%'),
            Civilian.phone_number.ilike(f'%{q}%'),
            Civilian.plate_number.ilike(f'%{q}%'),
        ]
        parsed_q_dob = _parse_date(q)
        if parsed_q_dob:
            filters.append(Civilian.date_of_birth == parsed_q_dob)
        filters.append(_civilian_name_filter(q))
        db_query = db_query.filter(sqlalchemy.or_(*filters))

    return db_query


def _civilian_name_filter(value):
    parts = [p for p in value.split() if p]
    if len(parts) >= 2:
        first = parts[0]
        last = ' '.join(parts[1:])
        return sqlalchemy.or_(
            sqlalchemy.and_(Civilian.first_name.ilike(f'%{first}%'), Civilian.last_name.ilike(f'%{last}%')),
            sqlalchemy.and_(Civilian.first_name.ilike(f'%{last}%'), Civilian.last_name.ilike(f'%{first}%')),
        )
    return sqlalchemy.or_(Civilian.first_name.ilike(f'%{value}%'), Civilian.last_name.ilike(f'%{value}%'))

# ---------------------------------------------------------------------------
# Database-backed CAD data helpers
# ---------------------------------------------------------------------------

def load_cad_data():
    """Return the full CAD data dict assembled from DB tables for the active tenant only."""
    community_id = get_current_community_id()
    civilians   = [civilian_to_dict(c)     for c in scoped_query(Civilian, community_id).order_by(Civilian.created_at).all()]
    vehicles    = [vehicle_to_dict(v)      for v in scoped_query(Vehicle, community_id).order_by(Vehicle.created_at).all()]
    licenses    = [license_to_dict(l)      for l in scoped_query(License, community_id).order_by(License.created_at).all()]
    warrants    = [warrant_to_dict(w)      for w in scoped_query(Warrant, community_id).order_by(Warrant.created_at.desc()).all()]
    arrests     = [arrest_to_dict(a)       for a in scoped_query(Arrest, community_id).order_by(Arrest.created_at.desc()).all()]
    incidents   = [incident_to_dict(i)     for i in scoped_query(Incident, community_id).order_by(Incident.created_at.desc()).all()]
    evidence    = [evidence_to_dict(e)     for e in scoped_query(Evidence, community_id).order_by(Evidence.created_at.desc()).all()]
    traffic     = [traffic_stop_to_dict(t) for t in scoped_query(TrafficStop, community_id).order_by(TrafficStop.created_at.desc()).all()]
    calls911    = [call911_to_dict(c)      for c in scoped_query(Call911, community_id).order_by(Call911.created_at.desc()).all()]
    activity    = [activity_log_to_dict(a) for a in scoped_query(ActivityLog, community_id).order_by(ActivityLog.created_at.desc()).limit(200).all()]
    hearings    = [hearing_to_dict(h)      for h in scoped_query(Hearing, community_id).order_by(Hearing.created_at.desc()).all()]
    jail_records = [jail_booking_to_dict(j) for j in scoped_query(JailBooking, community_id).order_by(JailBooking.created_at.desc()).all()]
    officer_sessions = scoped_query(OfficerSession, community_id).filter(OfficerSession.status != 'Off Duty').order_by(OfficerSession.updated_at.desc()).all()
    officers = [
        {
            **session_to_dict(session),
            'id': session.callsign,
            'lastUpdate': session.updated_at.isoformat() if session.updated_at else (session.logged_in_at.isoformat() if session.logged_in_at else None),
        }
        for session in officer_sessions
    ] or get_config('default_officers', DEFAULT_OFFICERS, community_id=community_id)
    return {
        'civilians':   civilians,
        'vehicles':    vehicles,
        'licenses':    licenses,
        'warrants':    warrants,
        'arrests':     arrests,
        'incidents':   incidents,
        'evidence':    evidence,
        'trafficStops': traffic,
        'calls911':    calls911,
        'officers':    officers,
        'activityLog': activity,
        'hearings':    hearings,
        'jailRecords': jail_records,
    }

def _upsert_civilian(data):
    civ_id = data.get('id') or f"CIV-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3)}"
    community_id = get_current_community_id()
    obj = scoped_query(Civilian, community_id).filter_by(civilian_id=civ_id).first()
    if obj is None:
        obj = Civilian(community_id=community_id, civilian_id=civ_id, first_name=data.get('firstName', ''), last_name=data.get('lastName', ''))
        db.session.add(obj)
    obj.first_name   = data.get('firstName', '')
    obj.last_name    = data.get('lastName', '')
    obj.gender       = data.get('gender', '')
    obj.phone_number = data.get('phone', '')
    obj.address      = data.get('address', '')
    obj.occupation   = data.get('occupation', '')
    obj.updated_at   = datetime.utcnow()


def _upsert_vehicle(data):
    plate = data.get('plate', '').strip()
    if not plate:
        return
    community_id = get_current_community_id()
    obj = scoped_query(Vehicle, community_id).filter_by(plate=plate).first()
    if obj is None:
        obj = Vehicle(community_id=community_id, plate=plate)
        db.session.add(obj)
    obj.owner_name          = data.get('ownerName', '')
    obj.model               = data.get('model', '')
    obj.color               = data.get('color', '')
    obj.registration_status = data.get('registrationStatus', 'Valid')
    obj.updated_at          = datetime.utcnow()


def _upsert_license(data):
    lic_id = data.get('id') or f"LIC-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3)}"
    community_id = get_current_community_id()
    obj = scoped_query(License, community_id).filter_by(license_id=lic_id).first()
    if obj is None:
        obj = License(community_id=community_id, license_id=lic_id)
        db.session.add(obj)
    obj.owner_name   = data.get('ownerName', '')
    obj.license_type = data.get('licenseType', '')
    obj.status       = data.get('status', 'Valid')
    obj.issued_date  = data.get('issuedDate', '')
    obj.expiry_date  = data.get('expiryDate', '')
    obj.notes        = data.get('notes', '')
    obj.updated_at   = datetime.utcnow()


def _upsert_warrant(data):
    w_id = data.get('id') or f"WRT-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3)}"
    community_id = get_current_community_id()
    obj = scoped_query(Warrant, community_id).filter_by(warrant_id=w_id).first()
    if obj is None:
        obj = Warrant(community_id=community_id, warrant_id=w_id)
        db.session.add(obj)
    obj.warrant_name    = data.get('warrantName', '')
    obj.warrant_charges = data.get('warrantCharges', '')
    obj.warrant_issuer  = data.get('warrantIssuer', '')
    obj.warrant_notes   = data.get('warrantNotes', '')
    obj.warrant_status  = data.get('warrantStatus', 'Active')
    obj.expiration_date = data.get('expirationDate', '')
    obj.justification   = data.get('justification', '')
    obj.updated_at      = datetime.utcnow()


def _upsert_arrest(data):
    a_id = data.get('id') or data.get('arrest_id') or f"ARR-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3)}"
    community_id = get_current_community_id()
    obj = scoped_query(Arrest, community_id).filter_by(arrest_id=a_id).first()
    if obj is None:
        obj = Arrest(community_id=community_id, arrest_id=a_id, created_at=datetime.utcnow())
        db.session.add(obj)
    _apply_arrest_payload(obj, data)
    _ensure_arrest_custody_and_hearing(obj)
    logger.info(f'Arrest saved: {obj.arrest_id} civilian_id={obj.civilian_id or "unlinked"}')
    return obj

def _upsert_incident(data):
    i_id = data.get('id') or f"INC-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3)}"
    community_id = get_current_community_id()
    obj = scoped_query(Incident, community_id).filter_by(incident_id=i_id).first()
    if obj is None:
        obj = Incident(community_id=community_id, incident_id=i_id)
        db.session.add(obj)
    obj.incident_type     = data.get('incidentType', '')
    obj.location          = data.get('location', '')
    obj.description       = data.get('description', '')
    obj.officers_involved = data.get('officersInvolved', '')
    obj.suspects          = data.get('suspects', '')
    obj.status            = data.get('status', 'Open')
    obj.priority          = data.get('priority', 'Medium')
    obj.notes             = data.get('notes', '')
    obj.updated_at        = datetime.utcnow()


def _upsert_evidence(data):
    e_id = data.get('id') or f"EVD-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3)}"
    community_id = get_current_community_id()
    obj = scoped_query(Evidence, community_id).filter_by(evidence_id=e_id).first()
    if obj is None:
        obj = Evidence(community_id=community_id, evidence_id=e_id)
        db.session.add(obj)
    obj.case_number          = data.get('caseNumber', '')
    obj.evidence_description = data.get('evidenceDescription', data.get('description', ''))
    obj.collected_by         = data.get('collectedBy', '')
    obj.location_found       = data.get('locationFound', '')
    obj.status               = data.get('status', 'Active')
    obj.notes                = data.get('notes', '')
    obj.updated_at           = datetime.utcnow()


def _upsert_traffic_stop(data):
    t_id = data.get('id') or f"TRF-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3)}"
    community_id = get_current_community_id()
    obj = scoped_query(TrafficStop, community_id).filter_by(stop_id=t_id).first()
    if obj is None:
        obj = TrafficStop(community_id=community_id, stop_id=t_id)
        db.session.add(obj)
    obj.driver_name = data.get('driverName', '')
    obj.plate       = data.get('trafficPlate', data.get('plate', ''))
    obj.reason      = data.get('trafficReason', data.get('reason', ''))
    obj.outcome     = data.get('trafficOutcome', data.get('outcome', ''))
    obj.officer     = data.get('officer', '')
    obj.location    = data.get('location', '')
    obj.notes       = data.get('notes', '')
    obj.updated_at  = datetime.utcnow()


def _upsert_call911(data):
    c_id = data.get('id') or f"911-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3)}"
    community_id = get_current_community_id()
    obj = scoped_query(Call911, community_id).filter_by(call_id=c_id).first()
    if obj is None:
        obj = Call911(community_id=community_id, call_id=c_id)
        db.session.add(obj)
    obj.caller_name    = data.get('callerName', '')
    obj.location       = data.get('location', '')
    obj.description    = data.get('description', '')
    obj.incident_type  = data.get('incidentType', '')
    obj.priority       = data.get('priority', 'Medium')
    obj.assigned_unit  = data.get('assignedUnit', '')
    obj.status         = data.get('status', 'New')
    obj.dispatch_notes = data.get('dispatchNotes', '')
    obj.updated_at     = datetime.utcnow()


def _upsert_activity(data):
    a_id = data.get('id') or f"ACT-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3)}"
    community_id = get_current_community_id()
    obj = scoped_query(ActivityLog, community_id).filter_by(log_id=a_id).first()
    if obj is None:
        obj = ActivityLog(community_id=community_id, log_id=a_id)
        db.session.add(obj)
    obj.action  = data.get('action', '')
    obj.officer = data.get('officer', '')
    obj.details = data.get('details', '')


def save_cad_data(data):
    """Persist a full CAD data dict to the database."""
    try:
        if data.get('civilians'):
            logger.info('Ignoring civilians in bulk CAD save; use POST /api/civilians for PostgreSQL civilian writes')
        for item in data.get('vehicles', []):
            _upsert_vehicle(item)
        for item in data.get('licenses', []):
            _upsert_license(item)
        for item in data.get('warrants', []):
            _upsert_warrant(item)
        for item in data.get('arrests', []):
            _upsert_arrest(item)
        for item in data.get('incidents', []):
            _upsert_incident(item)
        for item in data.get('evidence', []):
            _upsert_evidence(item)
        for item in data.get('trafficStops', []):
            _upsert_traffic_stop(item)
        for item in data.get('calls911', []):
            _upsert_call911(item)
        for item in data.get('activityLog', []):
            _upsert_activity(item)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f'save_cad_data error: {e}')
        raise


def send_bolo_discord(bolo):
    webhook_url = os.environ.get('DISCORD_WEBHOOK_URL', '')
    if not webhook_url or 'placeholder' in webhook_url:
        return False
    threat_colors = {'High': 15158332, 'Medium': 16744272, 'Low': 5763719}
    color = threat_colors.get(bolo.get('threatLevel', 'Medium'), 16744272)
    fields = [
        {"name": "BOLO ID",      "value": f"`{bolo['id']}`",               "inline": True},
        {"name": "Threat Level", "value": bolo.get('threatLevel', '—'),    "inline": True},
        {"name": "Issued By",    "value": bolo.get('issuedBy', '—'),       "inline": True},
        {"name": "Last Seen",    "value": bolo.get('lastLocation', '—'),   "inline": True},
    ]
    if bolo.get('vehicle'):
        fields.append({"name": "Vehicle",  "value": bolo['vehicle'],  "inline": True})
    if bolo.get('charges'):
        fields.append({"name": "Charges",  "value": bolo['charges'],  "inline": False})
    auto_tag = ' *(auto-generated)*' if bolo.get('autoGenerated') else ''
    payload = {
        "username":   "GTAVCAD BOLO Board",
        "avatar_url": "https://cdn.discordapp.com/embed/avatars/0.png",
        "embeds": [{
            "title":       f"🔍 BOLO ISSUED — {bolo.get('suspectName', 'Unknown')}{auto_tag}",
            "description": bolo.get('description', ''),
            "color":       color,
            "fields":      fields,
            "footer":      {"text": f"GTAVCAD LSPD • {bolo.get('issuedAt', '')[:10]}"},
        }]
    }
    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            webhook_url, data=data,
            headers={'Content-Type': 'application/json'}, method='POST'
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 204)
    except Exception as e:
        logger.error(f'BOLO Discord webhook failed: {e}')
    return False


def create_bolo(suspect_name, description, last_location, charges, officer, threat_level='High', vehicle=''):
    bolo_id = f"BOLO-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3)}"
    bolo_obj = Bolo(
        community_id=get_current_community_id(),
        bolo_id=bolo_id,
        suspect_name=suspect_name,
        description=description,
        last_location=last_location,
        vehicle=vehicle,
        charges=charges,
        threat_level=threat_level,
        issued_by=officer,
        status='Active',
        auto_generated=True,
    )
    try:
        db.session.add(bolo_obj)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f'create_bolo DB error: {e}')
        raise
    bolo_dict = bolo_to_dict(bolo_obj)
    send_bolo_discord(bolo_dict)
    return bolo_dict


def load_radio_log():
    entries = scoped_query(RadioLog).order_by(RadioLog.created_at.desc()).limit(100).all()
    return [radio_to_dict(r) for r in reversed(entries)]


def load_server_status():
    status = ServerStatus.query.first()
    if status is None:
        status = ServerStatus(
            city_status='ACTIVE',
            player_count=0,
            max_players=32,
            custom_message='24/7 dispatch channel live',
        )
        try:
            db.session.add(status)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f'load_server_status init error: {e}')
    return status_to_dict(status)


def save_server_status(status_dict):
    status = ServerStatus.query.first()
    if status is None:
        status = ServerStatus()
        db.session.add(status)
    status.city_status    = status_dict.get('cityStatus', 'ACTIVE')
    status.player_count   = status_dict.get('playerCount', 0)
    status.max_players    = status_dict.get('maxPlayers', 32)
    status.custom_message = status_dict.get('customMessage', '')
    status.last_updated   = datetime.utcnow()
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f'save_server_status error: {e}')
        raise
    return status_to_dict(status)


def load_applications():
    apps = scoped_query(Application).order_by(Application.submitted_at.desc()).all()
    return [application_to_dict(a) for a in apps]


def save_application(data):
    count = scoped_query(Application).count()
    app_id = f"APP-{datetime.now().strftime('%Y%m%d%H%M%S')}-{count+1:04d}"
    app_obj = Application(
        community_id=get_current_community_id(),
        application_id=app_id,
        app_discord=data.get('appDiscord', ''),
        app_character=data.get('appCharacter', ''),
        application_type=data.get('applicationType', ''),
        age_confirmation=data.get('ageConfirmation', ''),
        experience=data.get('experience', ''),
        role_reason=data.get('roleReason', ''),
        availability=data.get('availability', ''),
        status='Pending',
        staff_notes='',
    )
    try:
        db.session.add(app_obj)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f'save_application DB error: {e}')
        raise
    return application_to_dict(app_obj)


def send_application_email(app):
    smtp_host = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
    smtp_port = int(os.environ.get('SMTP_PORT', '465'))
    smtp_email = os.environ.get('SMTP_EMAIL')
    smtp_password = os.environ.get('SMTP_PASSWORD')
    notify_email = os.environ.get('NOTIFY_EMAIL', smtp_email)
    from_name = os.environ.get('SMTP_FROM_NAME', 'GTAVCAD')

    if not smtp_email or not smtp_password:
        logger.warning('Email credentials not configured. Application saved but no email sent.')
        return False

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"[GTAVCAD] New Application — {app['applicationType']} — {app['id']}"
        msg['From'] = f"{from_name} <{smtp_email}>"
        msg['To'] = notify_email

        html = f"""
        <html><body style="font-family:Arial,sans-serif;background:#111;color:#eee;padding:24px;">
          <div style="max-width:600px;margin:0 auto;background:#1a1a1a;border-radius:12px;padding:24px;border:1px solid #333;">
            <h2 style="color:#ff2d2d;margin-top:0;">GTAVCAD — New Application Submitted</h2>
            <table style="width:100%;border-collapse:collapse;">
              <tr><td style="padding:8px 0;color:#aaa;width:40%;">Application ID</td><td style="padding:8px 0;font-weight:bold;">{app['id']}</td></tr>
              <tr><td style="padding:8px 0;color:#aaa;">Submitted At</td><td style="padding:8px 0;">{app['submittedAt']}</td></tr>
              <tr><td style="padding:8px 0;color:#aaa;">Discord</td><td style="padding:8px 0;">{app.get('appDiscord','N/A')}</td></tr>
              <tr><td style="padding:8px 0;color:#aaa;">Character Name</td><td style="padding:8px 0;">{app.get('appCharacter','N/A')}</td></tr>
              <tr><td style="padding:8px 0;color:#aaa;">Role Applied For</td><td style="padding:8px 0;"><strong style="color:#ff2d2d;">{app.get('applicationType','N/A')}</strong></td></tr>
              <tr><td style="padding:8px 0;color:#aaa;">Age</td><td style="padding:8px 0;">{app.get('ageConfirmation','N/A')}</td></tr>
              <tr><td style="padding:8px 0;color:#aaa;">Availability</td><td style="padding:8px 0;">{app.get('availability','N/A')}</td></tr>
            </table>
            <hr style="border-color:#333;margin:16px 0;">
            <p style="color:#aaa;margin:4px 0;">RP Experience</p>
            <p style="background:#111;padding:12px;border-radius:8px;border-left:3px solid #ff2d2d;">{app.get('experience','N/A')}</p>
            <p style="color:#aaa;margin:4px 0;">Why They Want This Role</p>
            <p style="background:#111;padding:12px;border-radius:8px;border-left:3px solid #555;">{app.get('roleReason','N/A')}</p>
            <p style="color:#555;font-size:12px;margin-top:24px;">GTAVCAD Application System — Automated Notification</p>
          </div>
        </body></html>
        """

        plain = f"""
GTAVCAD — New Application Submitted
=======================================
Application ID: {app['id']}
Submitted At:   {app['submittedAt']}
Discord:        {app.get('appDiscord','N/A')}
Character:      {app.get('appCharacter','N/A')}
Role:           {app.get('applicationType','N/A')}
Age:            {app.get('ageConfirmation','N/A')}
Availability:   {app.get('availability','N/A')}

RP Experience:
{app.get('experience','N/A')}

Why This Role:
{app.get('roleReason','N/A')}
        """

        msg.attach(MIMEText(plain, 'plain'))
        msg.attach(MIMEText(html, 'html'))

        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port) as srv:
                srv.login(smtp_email, smtp_password)
                srv.sendmail(smtp_email, notify_email, msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, smtp_port) as srv:
                srv.ehlo()
                srv.starttls()
                srv.login(smtp_email, smtp_password)
                srv.sendmail(smtp_email, notify_email, msg.as_string())

        logger.info(f"Application email sent for {app['id']}")
        return True
    except Exception as e:
        logger.error(f"Failed to send application email: {e}")
        return False


def send_application_discord(app):
    webhook_url = os.environ.get('DISCORD_WEBHOOK_URL', '')
    if not webhook_url or 'placeholder' in webhook_url:
        logger.warning('Discord webhook not configured. Skipping Discord notification.')
        return False

    try:
        type_colors = {
            'Police Department': 3447003,
            'EMS': 3066993,
            'Staff': 10181046,
            'Business Owner': 16744272,
            'Gang / Faction': 15158332,
            'Court / Judge / Lawyer': 16776960,
            'DMV Worker': 9807270,
        }
        color = type_colors.get(app.get('applicationType', ''), 3447003)

        payload = {
            "username": "GTAVCAD Applications",
            "avatar_url": "https://cdn.discordapp.com/embed/avatars/0.png",
            "embeds": [{
                "title": f"📋 New Application — {app.get('applicationType', 'Unknown')}",
                "description": f"**RP Experience:**\n{app.get('experience', 'N/A')}\n\n**Why This Role:**\n{app.get('roleReason', 'N/A')}",
                "color": color,
                "fields": [
                    {"name": "Application ID", "value": f"`{app['id']}`", "inline": True},
                    {"name": "Role", "value": app.get('applicationType', 'N/A'), "inline": True},
                    {"name": "Discord", "value": app.get('appDiscord', 'N/A'), "inline": True},
                    {"name": "Character", "value": app.get('appCharacter', 'N/A'), "inline": True},
                    {"name": "Age", "value": app.get('ageConfirmation', 'N/A'), "inline": True},
                    {"name": "Availability", "value": app.get('availability', 'N/A'), "inline": True},
                ],
                "footer": {"text": f"GTAVCAD Application System • {app['submittedAt'][:10]}"},
            }]
        }

        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            webhook_url, data=data,
            headers={'Content-Type': 'application/json'}, method='POST'
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status in (200, 204):
                logger.info(f"Discord notification sent for {app['id']}")
                return True
    except Exception as e:
        logger.error(f"Application Discord webhook failed: {e}")
    return False


def load_complaints():
    complaints = Complaint.query.order_by(Complaint.submitted_at.desc()).all()
    return [complaint_to_dict(c) for c in complaints]


def save_complaint(data):
    count = Complaint.query.count()
    cmp_id = f"CMP-{datetime.now().strftime('%Y%m%d%H%M%S')}-{count+1:04d}"
    cmp_obj = Complaint(
        complaint_id=cmp_id,
        complaint_discord=data.get('complaintDiscord', ''),
        reported_name=data.get('reportedName', ''),
        complaint_type=data.get('complaintType', ''),
        incident_date=data.get('incidentDate', ''),
        incident_location=data.get('incidentLocation', ''),
        witnesses=data.get('witnesses', ''),
        evidence_link=data.get('evidenceLink', ''),
        description=data.get('description', ''),
        resolution=data.get('resolution', ''),
        status='Open',
        staff_notes='',
    )
    try:
        db.session.add(cmp_obj)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f'save_complaint DB error: {e}')
        raise
    return complaint_to_dict(cmp_obj)


def send_email_notification(complaint):
    smtp_host = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
    smtp_port = int(os.environ.get('SMTP_PORT', '465'))
    smtp_email = os.environ.get('SMTP_EMAIL')
    smtp_password = os.environ.get('SMTP_PASSWORD')
    notify_email = os.environ.get('NOTIFY_EMAIL', smtp_email)
    from_name = os.environ.get('SMTP_FROM_NAME', 'GTAVCAD')

    if not smtp_email or not smtp_password:
        logger.warning('Email credentials not configured. Complaint saved but no email sent.')
        return False

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"[GTAVCAD] New Complaint — {complaint['complaintType']} — {complaint['id']}"
        msg['From'] = f"{from_name} <{smtp_email}>"
        msg['To'] = notify_email

        html = f"""
        <html><body style="font-family:Arial,sans-serif;background:#111;color:#eee;padding:24px;">
          <div style="max-width:600px;margin:0 auto;background:#1a1a1a;border-radius:12px;padding:24px;border:1px solid #333;">
            <h2 style="color:#ff2d2d;margin-top:0;">GTAVCAD — New Complaint Filed</h2>
            <table style="width:100%;border-collapse:collapse;">
              <tr><td style="padding:8px 0;color:#aaa;width:40%;">Complaint ID</td><td style="padding:8px 0;font-weight:bold;">{complaint['id']}</td></tr>
              <tr><td style="padding:8px 0;color:#aaa;">Submitted At</td><td style="padding:8px 0;">{complaint['submittedAt']}</td></tr>
              <tr><td style="padding:8px 0;color:#aaa;">Discord Username</td><td style="padding:8px 0;">{complaint.get('complaintDiscord','N/A')}</td></tr>
              <tr><td style="padding:8px 0;color:#aaa;">Reported Person</td><td style="padding:8px 0;">{complaint.get('reportedName','N/A')}</td></tr>
              <tr><td style="padding:8px 0;color:#aaa;">Complaint Type</td><td style="padding:8px 0;"><strong style="color:#ff2d2d;">{complaint.get('complaintType','N/A')}</strong></td></tr>
              <tr><td style="padding:8px 0;color:#aaa;">Incident Date/Time</td><td style="padding:8px 0;">{complaint.get('incidentDate','N/A')}</td></tr>
              <tr><td style="padding:8px 0;color:#aaa;">Location/Channel</td><td style="padding:8px 0;">{complaint.get('incidentLocation','N/A')}</td></tr>
              <tr><td style="padding:8px 0;color:#aaa;">Witnesses</td><td style="padding:8px 0;">{complaint.get('witnesses','None')}</td></tr>
              <tr><td style="padding:8px 0;color:#aaa;">Evidence Link</td><td style="padding:8px 0;">{complaint.get('evidenceLink','None')}</td></tr>
            </table>
            <hr style="border-color:#333;margin:16px 0;">
            <p style="color:#aaa;margin:4px 0;">Description</p>
            <p style="background:#111;padding:12px;border-radius:8px;border-left:3px solid #ff2d2d;">{complaint.get('description','N/A')}</p>
            <p style="color:#aaa;margin:4px 0;">Desired Resolution</p>
            <p style="background:#111;padding:12px;border-radius:8px;border-left:3px solid #555;">{complaint.get('resolution','N/A')}</p>
            <p style="color:#555;font-size:12px;margin-top:24px;">GTAVCAD Complaint System — Automated Notification</p>
          </div>
        </body></html>
        """

        plain = f"""
GTAVCAD — New Complaint Filed
=================================
Complaint ID:     {complaint['id']}
Submitted At:     {complaint['submittedAt']}
Discord Username: {complaint.get('complaintDiscord','N/A')}
Reported Person:  {complaint.get('reportedName','N/A')}
Complaint Type:   {complaint.get('complaintType','N/A')}
Incident Date:    {complaint.get('incidentDate','N/A')}
Location:         {complaint.get('incidentLocation','N/A')}
Witnesses:        {complaint.get('witnesses','None')}
Evidence Link:    {complaint.get('evidenceLink','None')}

Description:
{complaint.get('description','N/A')}

Desired Resolution:
{complaint.get('resolution','N/A')}
        """

        msg.attach(MIMEText(plain, 'plain'))
        msg.attach(MIMEText(html, 'html'))

        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port) as srv:
                srv.login(smtp_email, smtp_password)
                srv.sendmail(smtp_email, notify_email, msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, smtp_port) as srv:
                srv.ehlo()
                srv.starttls()
                srv.login(smtp_email, smtp_password)
                srv.sendmail(smtp_email, notify_email, msg.as_string())

        logger.info(f"Email notification sent for complaint {complaint['id']}")
        return True

    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False


def send_discord_notification(complaint):
    webhook_url = os.environ.get('DISCORD_WEBHOOK_URL', '')
    if not webhook_url or 'placeholder' in webhook_url:
        logger.warning('Discord webhook not configured. Skipping Discord notification.')
        return False

    try:
        type_colors = {
            'Player report': 15158332,
            'Staff complaint': 15105570,
            'Officer complaint': 15548997,
            'Rule break': 16711680,
            'Fail RP': 16744272,
            'RDM / VDM': 16711680,
            'Harassment': 15158332,
            'Evidence submission': 3447003,
        }
        color = type_colors.get(complaint.get('complaintType', ''), 15158332)

        fields = [
            {"name": "Complaint ID", "value": f"`{complaint['id']}`", "inline": True},
            {"name": "Type", "value": complaint.get('complaintType', 'N/A'), "inline": True},
            {"name": "Reported Person", "value": complaint.get('reportedName', 'N/A'), "inline": True},
            {"name": "Discord", "value": complaint.get('complaintDiscord', 'N/A'), "inline": True},
            {"name": "Location", "value": complaint.get('incidentLocation', 'N/A'), "inline": True},
            {"name": "Incident Date", "value": complaint.get('incidentDate', 'N/A'), "inline": True},
        ]
        if complaint.get('witnesses'):
            fields.append({"name": "Witnesses", "value": complaint['witnesses'], "inline": False})
        if complaint.get('evidenceLink'):
            fields.append({"name": "Evidence", "value": complaint['evidenceLink'], "inline": False})

        payload = {
            "username": "GTAVCAD Complaints",
            "avatar_url": "https://cdn.discordapp.com/embed/avatars/0.png",
            "embeds": [{
                "title": f"🚨 New Complaint Filed — {complaint.get('complaintType', 'Unknown')}",
                "description": f"**Description:**\n{complaint.get('description', 'N/A')}\n\n**Desired Resolution:**\n{complaint.get('resolution', 'N/A')}",
                "color": color,
                "fields": fields,
                "footer": {"text": f"GTAVCAD Complaint System • {complaint['submittedAt'][:10]}"},
            }]
        }

        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status in (200, 204):
                logger.info(f"Discord notification sent for {complaint['id']}")
                return True
    except Exception as e:
        logger.error(f"Discord webhook failed: {e}")
    return False


@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.get_json(silent=True) or {}
    password = data.get('password', '')
    admin_password_hash = os.environ.get('ADMIN_PASSWORD_HASH', '')
    if not admin_password_hash:
        return jsonify({'success': False, 'error': 'Admin password not configured'}), 500
    if verify_password(admin_password_hash, password):
        session['admin_logged_in'] = True
        session['role'] = 'Admin'
        session['user_id'] = 'admin'
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Invalid password'}), 401


@app.route('/api/admin/logout', methods=['POST'])
def admin_logout():
    session.clear()
    return jsonify({'success': True})


@app.route('/api/admin/session', methods=['GET'])
def admin_session():
    return jsonify({'success': True, 'loggedIn': bool(session.get('admin_logged_in'))})


# User Authentication Routes
@app.route('/api/auth/login', methods=['POST'])
def user_login():
    data = request.get_json(silent=True) or {}
    identifier = (data.get('username') or data.get('email') or '').strip()
    password = data.get('password', '').strip()

    if not identifier or not password:
        return jsonify({'success': False, 'error': 'Username/email and password required', 'code': 'MISSING_CREDENTIALS'}), 400

    identifier_lower = identifier.lower()
    logger.info("Auth login attempt identifier=%s ip=%s", identifier_lower, request.remote_addr)
    username_filter = func.lower(User.username) == identifier_lower if hasattr(User, 'username') else None
    email_filter = func.lower(User.email) == identifier_lower if hasattr(User, 'email') else None
    filters = [f for f in (username_filter, email_filter) if f is not None]
    if not filters:
        logger.error("Auth login failed: user model missing username/email columns")
        return jsonify({'success': False, 'error': 'Authentication unavailable', 'code': 'AUTH_UNAVAILABLE'}), 500
    matched_users = User.query.filter(or_(*filters)).all()
    if not matched_users:
        logger.warning("Auth login failed: account not found identifier=%s ip=%s", identifier_lower, request.remote_addr)
        return jsonify({'success': False, 'error': 'Account not found', 'code': 'ACCOUNT_NOT_FOUND'}), 404
    if len(matched_users) != 1:
        logger.warning("Auth login failed: ambiguous identifier=%s count=%s ip=%s", identifier_lower, len(matched_users), request.remote_addr)
        return jsonify({'success': False, 'error': 'Ambiguous login identifier', 'code': 'AMBIGUOUS_IDENTIFIER'}), 409
    user = matched_users[0]
    hash_prefix = (user.password_hash or '')[:20]
    logger.info("Auth login diagnostics identifier=%s user_found=true user_id=%s hash_prefix=%s active=%s role=%s platform_role=%s",
                identifier_lower, user.id, hash_prefix, bool(_user_field(user, 'active', True)), _user_field(user, 'role', ''), _user_field(user, 'platform_role', ''))
    if not bool(_user_field(user, 'active', True)):
        logger.warning("Auth login failed: inactive account user_id=%s ip=%s", user.id, request.remote_addr)
        return jsonify({'success': False, 'error': 'Account is inactive', 'code': 'ACCOUNT_INACTIVE'}), 403
    if not user.password_hash:
        logger.error("Auth login failed: missing password hash user_id=%s", user.id)
        return jsonify({'success': False, 'error': 'Internal authentication error', 'code': 'AUTH_STATE_INVALID'}), 500
    verify_result = verify_password(user.password_hash, password)
    logger.info("Auth login diagnostics user_id=%s verify_result=%s", user.id, verify_result)
    if not verify_result:
        logger.warning("Auth login failed: invalid credentials user_id=%s ip=%s", user.id, request.remote_addr)
        return jsonify({'success': False, 'error': 'Invalid username or password', 'code': 'INVALID_CREDENTIALS'}), 401

    # Update last login
    user.last_login = datetime.utcnow()
    db.session.commit()

    is_owner = _session_hydrate_user(user)
    session.permanent = True
    session['community_id'] = _user_field(user, 'community_id', None)
    session.modified = True

    redirect_target = '/admin' if is_owner else '/communities'
    requires_community_setup = False if is_owner else not bool(session.get('community_id'))

    logger.info("Auth login success login_success=true user_id=%s username=%s role=%s platform_role=%s is_platform_owner=%s session_keys=%s redirect=%s session_modified=%s",
                user.id, session.get('username'), session.get('role'), session.get('platform_role'), is_owner, sorted(list(session.keys())), redirect_target, session.modified)
    return jsonify({
        'success': True,
        'authenticated': True,
        'user': {
            'id': user.id,
            'username': _user_field(user, 'username', ''),
            'email': _user_field(user, 'email', None),
            'role': _user_field(user, 'role', 'Civilian') or 'Civilian',
            'platform_role': _user_field(user, 'platform_role', None),
            'is_platform_owner': is_owner,
            'community_id': _user_field(user, 'community_id', None),
            'requires_community_setup': requires_community_setup,
        },
        'redirect': '/admin' if is_owner else '/communities'
    })


@app.route('/api/auth/register', methods=['POST'])
def user_register():
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')
    email = data.get('email', '').strip() or None

    if not username or not password:
        return jsonify({'success': False, 'error': 'Username and password required', 'code': 'MISSING_CREDENTIALS'}), 400

    if len(password) < 8:
        return jsonify({'success': False, 'error': 'Password must be at least 8 characters', 'code': 'PASSWORD_TOO_SHORT'}), 400

    existing_query = User.query.filter(User.username == username)
    if email:
        existing_query = User.query.filter((User.username == username) | (User.email == email))
    existing = existing_query.first()
    if existing:
        if existing.username == username:
            return jsonify({'success': False, 'error': 'Username already exists', 'code': 'USERNAME_EXISTS'}), 409
        return jsonify({'success': False, 'error': 'Email already exists', 'code': 'EMAIL_EXISTS'}), 409

    user = User(username=username, email=email, password_hash=hash_password(password), role='Civilian', active=True)
    db.session.add(user)
    db.session.commit()

    _session_hydrate_user(user)
    ensure_platform_owner(user)

    return jsonify({
        'success': True,
        'user': user.to_dict(),
        'communities': [],
        'community_count': 0,
        'next_step': 'create_or_join_community',
        'redirect_url': '/create-community',
        'message': 'Registration successful',
    }), 201


@app.route('/api/auth/logout', methods=['POST'])
def user_logout():
    session.clear()
    return jsonify({'success': True})


@app.route('/api/auth/session', methods=['GET'])
def user_session():
    user_id = session.get('user_id')
    if not user_id:
        logger.info("Auth session check has_user_id=false authenticated=false reason=missing_user_id")
        return jsonify({'success': False, 'authenticated': False, 'error': 'Session expired', 'code': 'SESSION_EXPIRED'}), 401

    user = User.query.get(user_id)
    if not user or not user.active:
        logger.info("Auth session check has_user_id=true user_id=%s authenticated=false reason=user_inactive_or_missing", user_id)
        session.clear()
        return jsonify({'success': False, 'authenticated': False, 'error': 'User not found or inactive', 'code': 'USER_INACTIVE'}), 401

    owner = is_platform_owner()
    redirect_target = '/admin' if owner else '/communities'
    logger.info("Auth session check has_user_id=true user_id=%s authenticated=true is_platform_owner=%s", user_id, owner)
    return jsonify({
        'success': True,
        'authenticated': True,
        'user': {
            'id': user.id,
            'username': _user_field(user, 'username', ''),
            'email': _user_field(user, 'email', None),
            'role': _user_field(user, 'role', 'Civilian') or 'Civilian',
            'platform_role': _user_field(user, 'platform_role', None),
            'is_platform_owner': owner,
            'community_id': _user_field(user, 'community_id', None),
            'requires_community_setup': False if owner else not bool(_user_field(user, 'community_id', None))
        },
        'redirect': redirect_target,
    })


@app.route('/api/debug/session', methods=['GET'])
def debug_session():
    env = (os.environ.get('FLASK_ENV') or '').lower()
    owner = bool(session.get('is_platform_owner'))
    if env == 'production' and not owner:
        return jsonify({'success': False, 'error': 'Forbidden'}), 403
    return jsonify({
        'has_session_user_id': bool(session.get('user_id')),
        'session_keys': sorted(list(session.keys())),
        'cookie_secure': app.config.get('SESSION_COOKIE_SECURE', False),
        'cookie_samesite': app.config.get('SESSION_COOKIE_SAMESITE'),
        'secret_key_configured': bool(app.config.get('SECRET_KEY')),
        'is_platform_owner': owner,
    })


logger.info("✓ Auth routes registered")


@app.route('/api/onboarding/status', methods=['GET'])
def onboarding_status():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({
            'success': True,
            'authenticated': False,
            'status': 'login_required',
            'communities': [],
            'community_count': 0,
            'next_step': 'login',
        })

    memberships = CommunityMember.query.filter_by(user_id=user_id, status='Active').all()
    communities = []
    for membership in memberships:
        community = Community.query.filter_by(community_id=membership.community_id, status='Active').first()
        if community:
            communities.append({'community': community.to_dict(), 'membership': membership.to_dict()})

    next_step = 'community_picker' if len(communities) > 1 else 'enter_community' if len(communities) == 1 else 'onboarding'
    return jsonify({
        'success': True,
        'authenticated': True,
        'status': next_step,
        'communities': communities,
        'community_count': len(communities),
        'selected_community_id': session.get('selected_community_id'),
        'selected_community_slug': session.get('selected_community_slug'),
        'next_step': next_step,
    })


logger.info("✓ Onboarding routes registered")


@app.route('/api/auth/change-password', methods=['POST'])
@require_auth
def change_password():
    data = request.get_json(silent=True) or {}
    current_password = data.get('current_password', '')
    new_password = data.get('new_password', '')

    if not current_password or not new_password:
        return jsonify({'success': False, 'error': 'Current and new password required', 'code': 'MISSING_PASSWORDS'}), 400

    if len(new_password) < 8:
        return jsonify({'success': False, 'error': 'New password must be at least 8 characters', 'code': 'PASSWORD_TOO_SHORT'}), 400

    user_id = session.get('user_id')
    user = User.query.get(user_id)

    if not verify_password(user.password_hash, current_password):
        return jsonify({'success': False, 'error': 'Current password is incorrect', 'code': 'INVALID_CURRENT_PASSWORD'}), 400

    user.password_hash = hash_password(new_password)
    db.session.commit()

    return jsonify({'success': True, 'message': 'Password changed successfully'})


@app.route('/api/admin/create-user', methods=['POST'])
@admin_required
def create_user():
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')
    role = data.get('role', 'Civilian')
    email = data.get('email', '').strip() or None

    if not username or not password:
        return jsonify({'success': False, 'error': 'Username and password required', 'code': 'MISSING_CREDENTIALS'}), 400

    if len(password) < 8:
        return jsonify({'success': False, 'error': 'Password must be at least 8 characters', 'code': 'PASSWORD_TOO_SHORT'}), 400

    if role not in ROLES:
        return jsonify({'success': False, 'error': 'Invalid role', 'code': 'INVALID_ROLE'}), 400

    # Check if username or email already exists
    existing = User.query.filter((User.username == username) | (User.email == email)).first()
    if existing:
        if existing.username == username:
            return jsonify({'success': False, 'error': 'Username already exists', 'code': 'USERNAME_EXISTS'}), 409
        else:
            return jsonify({'success': False, 'error': 'Email already exists', 'code': 'EMAIL_EXISTS'}), 409

    user = User(
        username=username,
        email=email,
        password_hash=hash_password(password),
        role=role
    )
    db.session.add(user)
    db.session.commit()

    return jsonify({
        'success': True,
        'user': user.to_dict(),
        'message': 'User created successfully'
    })


@app.route('/api/admin/users', methods=['GET'])
@admin_required
def list_users():
    users = User.query.all()
    return jsonify({
        'success': True,
        'users': [user.to_dict() for user in users]
    })


@app.route('/api/admin/users/<int:user_id>', methods=['PUT'])
@admin_required
def update_user(user_id):
    user = User.query.get_or_404(user_id)
    data = request.get_json(silent=True) or {}

    # Update allowed fields
    if 'role' in data:
        if data['role'] not in ROLES:
            return jsonify({'success': False, 'error': 'Invalid role', 'code': 'INVALID_ROLE'}), 400
        user.role = data['role']

    if 'active' in data:
        user.active = data['active']

    if 'email' in data:
        email = data['email'].strip() if data['email'] else None
        # Check if email is taken by another user
        existing = User.query.filter(User.email == email, User.id != user_id).first()
        if existing:
            return jsonify({'success': False, 'error': 'Email already exists', 'code': 'EMAIL_EXISTS'}), 409
        user.email = email

    db.session.commit()

    return jsonify({
        'success': True,
        'user': user.to_dict(),
        'message': 'User updated successfully'
    })


@app.route('/api/admin/config', methods=['GET'])
@admin_required
def get_config_admin():
    configs = Config.query.all()
    return jsonify({'success': True, 'config': [c.to_dict() for c in configs]})


@app.route('/api/admin/config/<key>', methods=['PUT'])
@admin_required
def update_config(key):
    data = request.get_json(silent=True) or {}
    current_community_id = get_current_community_id()
    config = None
    if current_community_id:
        config = Config.query.filter_by(key=key, community_id=current_community_id).first()
    if not config:
        config = Config.query.filter_by(key=key, community_id=None).first()
    if not config:
        config = Config(key=key, community_id=current_community_id)
        db.session.add(config)

    import json
    if 'value' in data:
        try:
            # Validate JSON if it's meant to be JSON
            json.dumps(data['value'])
            config.value = json.dumps(data['value'])
        except:
            config.value = str(data['value'])

    if 'description' in data:
        config.description = data['description']

    config.updated_at = datetime.utcnow()
    db.session.commit()

    return jsonify({'success': True, 'config': config.to_dict(), 'message': 'Config updated successfully'})



@app.route('/api/platform', methods=['GET'])
def get_platform_metadata():
    """Public global platform metadata that must never be tenant-branded."""
    return jsonify({
        'success': True,
        'platform': {
            'platform_name': PLATFORM_NAME,
            'platform_domain': PLATFORM_DOMAIN,
            'tagline': PLATFORM_TAGLINE,
            'cta': PLATFORM_CTA,
            'default_community': {
                'community_name': DEFAULT_COMMUNITY_NAME,
                'community_slug': DEFAULT_COMMUNITY_SLUG,
                'cad_name': DEFAULT_COMMUNITY_CAD_NAME,
            },
            'global_routes': ['/', '/login', '/register', '/communities', '/create-community'],
            'community_route_prefix': '/c/<community_slug>',
        }
    })

@app.route('/api/config/<key>', methods=['GET'])
def get_public_config(key):
    """Get public configuration values."""
    public_keys = ['platform_name', 'platform_domain', 'platform_tagline', 'platform_cta', 'server_name', 'departments', 'call_types', 'agency_names']
    if key not in public_keys:
        return jsonify({'success': False, 'error': 'Config key not public', 'code': 'CONFIG_NOT_PUBLIC'}), 403

    if key.startswith('platform_'):
        value = get_config(key)
    else:
        value = get_config(key, community_id=get_current_community_id())
    return jsonify({'success': True, 'key': key, 'value': value})


@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint for monitoring."""
    redis_url = os.environ.get('REDIS_URL')
    health = {
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'version': '3.0.0',  # Phase 3
        'checks': {},
        'uptime_seconds': int(time.time() - PROCESS_START_TIME),
        'memory_usage_mb': round((__import__('resource').getrusage(__import__('resource').RUSAGE_SELF).ru_maxrss / 1024), 2),
        'active_sessions': UserSession.query.filter_by(active=True).count(),
        'active_websocket_connections': len(ACTIVE_SOCKET_CONNECTIONS),
        'websocket_status': 'healthy'
    }

    # Database health
    try:
        db.engine.execute(text('SELECT 1'))
        health['checks']['database'] = {'status': 'healthy', 'message': 'Database connection OK'}
    except Exception as e:
        health['status'] = 'unhealthy'
        health['checks']['database'] = {'status': 'unhealthy', 'message': str(e)}

    # Migration status
    try:
        # Check if alembic_version table exists
        inspector = sa_inspect(db.engine)
        if 'alembic_version' in inspector.get_table_names():
            health['checks']['migrations'] = {'status': 'healthy', 'message': 'Migrations initialized'}
        else:
            health['checks']['migrations'] = {'status': 'warning', 'message': 'Migrations not initialized'}
    except Exception as e:
        health['checks']['migrations'] = {'status': 'error', 'message': str(e)}

    # Auth status
    try:
        admin_count = User.query.filter_by(role='Admin', active=True).count()
        health['checks']['auth'] = {
            'status': 'healthy' if admin_count > 0 else 'warning',
            'message': f'{admin_count} active admin users'
        }
    except Exception as e:
        health['checks']['auth'] = {'status': 'error', 'message': str(e)}

    # Environment validation
    missing_vars = []
    required_vars = ['DATABASE_URL']
    for var in required_vars:
        if not os.environ.get(var):
            missing_vars.append(var)

    if missing_vars:
        health['status'] = 'unhealthy'
        health['checks']['environment'] = {
            'status': 'unhealthy',
            'message': f'Missing required variables: {", ".join(missing_vars)}'
        }
    else:
        health['checks']['environment'] = {'status': 'healthy', 'message': 'All required variables present'}

    if redis_url:
        try:
            import redis
            redis.Redis.from_url(redis_url, socket_connect_timeout=1).ping()
            health['checks']['redis'] = {'status': 'healthy', 'message': 'Redis ping OK'}
        except Exception as e:
            health['checks']['redis'] = {'status': 'error', 'message': str(e)}
            health['status'] = 'unhealthy'
    else:
        health['checks']['redis'] = {'status': 'disabled', 'message': 'REDIS_URL not configured'}

    # Set overall status
    if any(check.get('status') in ['unhealthy', 'error'] for check in health['checks'].values()):
        health['status'] = 'unhealthy'
    elif any(check.get('status') == 'warning' for check in health['checks'].values()):
        health['status'] = 'warning'

    status_code = 200 if health['status'] == 'healthy' else 503
    return jsonify(health), status_code


@app.route('/api/platform/status', methods=['GET'])
@admin_required
def platform_status():
    return jsonify({
        'success': True,
        'timestamp': datetime.utcnow().isoformat(),
        'metrics': {
            'total_online_users': UserSession.query.filter_by(active=True).count(),
            'total_online_officers': UserSession.query.filter(UserSession.active.is_(True), UserSession.role.in_(['Police', 'LEO', 'Dispatch'])).count(),
            'active_dispatch_calls': DispatchCall.query.filter(DispatchCall.status.in_(['Open', 'Active', 'In Progress'])).count(),
            'websocket_connections': len(ACTIVE_SOCKET_CONNECTIONS),
            'communities_online': db.session.query(UserSession.tenant).filter(UserSession.active.is_(True)).distinct().count(),
            'active_scenes': Incident.query.filter(Incident.status.in_(['Open', 'Active'])).count(),
            'pending_hearings': Hearing.query.filter(Hearing.status.in_(['Scheduled', 'Pending'])).count(),
            'open_warrants': Warrant.query.filter(Warrant.status.in_(['Active', 'Open'])).count()
        }
    })


@app.route('/api/diagnostics', methods=['GET'])
@admin_required
def diagnostics():
    """Detailed diagnostics for administrators."""
    diag = {
        'timestamp': datetime.utcnow().isoformat(),
        'system': {
            'python_version': f'{__import__("sys").version_info.major}.{__import__("sys").version_info.minor}',
            'flask_version': __import__('flask').__version__,
            'platform': __import__('platform').platform()
        },
        'database': {
            'url': os.environ.get('DATABASE_URL', 'Not set')[:50] + '...' if os.environ.get('DATABASE_URL') else 'Not set',
            'tables': []
        },
        'config': {
            'flask_secret_set': bool(os.environ.get('FLASK_SECRET')),
            'admin_password_hash_set': bool(os.environ.get('ADMIN_PASSWORD_HASH')),
            'database_url_set': bool(os.environ.get('DATABASE_URL'))
        },
        'users': {
            'total': User.query.count(),
            'admins': User.query.filter_by(role='Admin').count(),
            'active': User.query.filter_by(active=True).count()
        }
    }

    # Get table list
    try:
        inspector = sa_inspect(db.engine)
        diag['database']['tables'] = inspector.get_table_names()
    except Exception as e:
        diag['database']['error'] = str(e)

    return jsonify({'success': True, 'diagnostics': diag})


@app.route('/api/bootstrap/first-admin', methods=['POST'])
def bootstrap_first_admin():
    """Create the first admin user. Only works if no admins exist."""
    # Check if any admins already exist
    admin_count = User.query.filter_by(role='Admin', active=True).count()
    if admin_count > 0:
        return jsonify({'success': False, 'error': 'Admin users already exist', 'code': 'ADMINS_EXIST'}), 403

    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')
    email = data.get('email', '').strip() or None

    if not username or not password:
        return jsonify({'success': False, 'error': 'Username and password required', 'code': 'MISSING_CREDENTIALS'}), 400

    if len(password) < 8:
        return jsonify({'success': False, 'error': 'Password must be at least 8 characters', 'code': 'PASSWORD_TOO_SHORT'}), 400

    # Check if username/email already exists
    existing = User.query.filter((User.username == username) | (User.email == email)).first()
    if existing:
        if existing.username == username:
            return jsonify({'success': False, 'error': 'Username already exists', 'code': 'USERNAME_EXISTS'}), 409
        else:
            return jsonify({'success': False, 'error': 'Email already exists', 'code': 'EMAIL_EXISTS'}), 409

    user = User(
        username=username,
        email=email,
        password_hash=hash_password(password),
        role='Admin'
    )
    db.session.add(user)
    db.session.commit()

    logger.info(f'✅ First admin user created: {username}')

    return jsonify({
        'success': True,
        'user': user.to_dict(),
        'message': 'First admin user created successfully'
    })


@app.route('/api/complaint', methods=['POST'])
def submit_complaint():
    data = request.get_json(silent=True) or {}
    required = ['complaintDiscord', 'reportedName', 'complaintType', 'incidentDate', 'incidentLocation', 'description', 'resolution']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({'success': False, 'error': f"Missing required fields: {', '.join(missing)}"}), 400

    complaint = save_complaint(data)
    email_sent = send_email_notification(complaint)
    send_discord_notification(complaint)

    return jsonify({
        'success': True,
        'id': complaint['id'],
        'emailSent': email_sent,
        'message': 'Complaint submitted successfully. Staff will review it shortly.'
    })


@app.route('/api/complaints', methods=['GET'])
@admin_required
def list_complaints():
    complaints = Complaint.query.order_by(Complaint.submitted_at.desc()).all()
    result = [complaint_to_dict(c) for c in complaints]
    return jsonify({'success': True, 'complaints': result, 'total': len(result)})


@app.route('/api/complaint/<complaint_id>/status', methods=['POST'])
@admin_required
def update_complaint_status(complaint_id):
    data = request.get_json(silent=True) or {}
    new_status = data.get('status')
    staff_notes = data.get('staffNotes')
    valid_statuses = ['Open', 'Under Review', 'Resolved', 'Dismissed']
    if new_status and new_status not in valid_statuses:
        return jsonify({'success': False, 'error': 'Invalid status'}), 400

    c = Complaint.query.filter_by(complaint_id=complaint_id).first()
    if c is None:
        return jsonify({'success': False, 'error': 'Complaint not found'}), 404
    if new_status:
        c.status = new_status
        c.updated_at = datetime.utcnow()
    if staff_notes is not None:
        c.staff_notes = staff_notes
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f'update_complaint_status error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500
    return jsonify({'success': True, 'complaint': complaint_to_dict(c)})


@app.route('/api/complaint/<complaint_id>', methods=['DELETE'])
@admin_required
def delete_complaint(complaint_id):
    c = Complaint.query.filter_by(complaint_id=complaint_id).first()
    if c is None:
        return jsonify({'success': False, 'error': 'Complaint not found'}), 404
    try:
        db.session.delete(c)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f'delete_complaint error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500
    return jsonify({'success': True})


@app.route('/api/application', methods=['POST'])
def submit_application():
    data = request.get_json(silent=True) or {}
    required = ['appDiscord', 'appCharacter', 'applicationType', 'ageConfirmation', 'experience', 'roleReason', 'availability']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({'success': False, 'error': f"Missing required fields: {', '.join(missing)}"}), 400

    application = save_application(data)
    send_application_email(application)
    send_application_discord(application)

    return jsonify({
        'success': True,
        'id': application['id'],
        'message': 'Application submitted successfully. Staff will review it and contact you via Discord.'
    })


@app.route('/api/applications', methods=['GET'])
@admin_required
def list_applications():
    apps = scoped_query(Application).order_by(Application.submitted_at.desc()).all()
    result = [application_to_dict(a) for a in apps]
    return jsonify({'success': True, 'applications': result, 'total': len(result)})


@app.route('/api/application/<app_id>/status', methods=['POST'])
@admin_required
def update_application_status(app_id):
    data = request.get_json(silent=True) or {}
    new_status = data.get('status')
    staff_notes = data.get('staffNotes')
    valid_statuses = ['Pending', 'Under Review', 'Accepted', 'Denied']
    if new_status and new_status not in valid_statuses:
        return jsonify({'success': False, 'error': 'Invalid status'}), 400

    a = scoped_query(Application).filter_by(application_id=app_id).first()
    if a is None:
        return jsonify({'success': False, 'error': 'Application not found'}), 404
    if new_status:
        a.status = new_status
        a.updated_at = datetime.utcnow()
    if staff_notes is not None:
        a.staff_notes = staff_notes
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f'update_application_status error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500
    return jsonify({'success': True, 'application': application_to_dict(a)})


@app.route('/api/application/<app_id>', methods=['DELETE'])
@admin_required
def delete_application(app_id):
    a = scoped_query(Application).filter_by(application_id=app_id).first()
    if a is None:
        return jsonify({'success': False, 'error': 'Application not found'}), 404
    try:
        db.session.delete(a)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f'delete_application error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500
    return jsonify({'success': True})


@app.route('/api/server-status', methods=['GET'])
def get_server_status():
    try:
        status = load_server_status()
        return jsonify({'success': True, 'status': status})
    except Exception as e:
        logger.error(f'Error loading server status: {e}')
        return jsonify({'success': False, 'error': 'Failed to load server status', 'code': 'STATUS_ERROR'}), 500


def send_status_discord_notification(old_status, new_status):
    webhook_url = os.environ.get('DISCORD_WEBHOOK_URL', '')
    if not webhook_url or 'placeholder' in webhook_url:
        logger.warning('Discord webhook not configured. Skipping status notification.')
        return False

    status_colors = {
        'ACTIVE':      0x4caf50,
        'OFFLINE':     0x555555,
        'MAINTENANCE': 0x4a9eff,
        'WHITELIST':   0xf5a623,
    }
    status_emojis = {
        'ACTIVE':      '🟢',
        'OFFLINE':     '🔴',
        'MAINTENANCE': '🔵',
        'WHITELIST':   '🟡',
    }

    city = new_status.get('cityStatus', 'ACTIVE')
    color = status_colors.get(city, 0x555555)
    emoji = status_emojis.get(city, '⚪')

    old_city = old_status.get('cityStatus', 'ACTIVE')
    changed = old_city != city
    title = f"{emoji} City Status Changed: {old_city} → {city}" if changed else f"{emoji} City Status Updated: {city}"

    fields = [
        {"name": "City Status", "value": city, "inline": True},
        {"name": "Players Online", "value": f"{new_status.get('playerCount', 0)} / {new_status.get('maxPlayers', 32)}", "inline": True},
    ]
    if new_status.get('customMessage'):
        fields.append({"name": "Message", "value": new_status['customMessage'], "inline": False})

    payload = {
        "username": "GTAVCAD Status",
        "avatar_url": "https://cdn.discordapp.com/embed/avatars/0.png",
        "embeds": [{
            "title": title,
            "color": color,
            "fields": fields,
            "footer": {"text": f"GTAVCAD • {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}"},
        }]
    }

    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        urllib.request.urlopen(req, timeout=5)
        logger.info('Status Discord notification sent.')
        return True
    except Exception as e:
        logger.error(f'Failed to send status Discord notification: {e}')
        return False


@app.route('/api/server-status', methods=['POST'])
@admin_required
def update_server_status():
    data = request.get_json(silent=True) or {}
    old_status = load_server_status()
    status = dict(old_status)
    valid_statuses = ['ACTIVE', 'OFFLINE', 'MAINTENANCE', 'WHITELIST']
    if 'cityStatus' in data and data['cityStatus'] in valid_statuses:
        status['cityStatus'] = data['cityStatus']
    if 'playerCount' in data:
        try:
            status['playerCount'] = max(0, int(data['playerCount']))
        except (ValueError, TypeError):
            pass
    if 'maxPlayers' in data:
        try:
            status['maxPlayers'] = max(1, int(data['maxPlayers']))
        except (ValueError, TypeError):
            pass
    if 'customMessage' in data:
        status['customMessage'] = str(data['customMessage'])[:200]
    save_server_status(status)
    send_status_discord_notification(old_status, status)
    return jsonify({'success': True, 'status': status})


@app.route('/api/bolos', methods=['GET'])
def get_bolos():
    try:
        bolos = scoped_query(Bolo).order_by(Bolo.created_at.desc()).all()
        return jsonify({'success': True, 'bolos': [bolo_to_dict(b) for b in bolos]})
    except Exception as e:
        logger.error(f'Error loading bolos: {e}')
        return jsonify({'success': False, 'error': 'Failed to load bolos', 'code': 'BOLOS_ERROR'}), 500


@police_required
@app.route('/api/bolo', methods=['POST'])
@police_required
def post_bolo():
    data = request.get_json(silent=True) or {}
    required = ['suspectName', 'description', 'lastLocation', 'threatLevel', 'issuedBy']
    if not all(data.get(f) for f in required):
        return jsonify({'success': False, 'error': 'Missing required fields.'}), 400
    bolo_id = f"BOLO-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3)}"
    bolo_obj = Bolo(
        community_id=get_current_community_id(),
        bolo_id=bolo_id,
        suspect_name=data.get('suspectName', 'Unknown'),
        description=data.get('description', ''),
        last_location=data.get('lastLocation', ''),
        vehicle=data.get('vehicle', ''),
        charges=data.get('charges', ''),
        threat_level=data.get('threatLevel', 'Medium'),
        issued_by=data.get('issuedBy', ''),
        status='Active',
        auto_generated=False,
    )
    try:
        db.session.add(bolo_obj)
        db.session.commit()
        from cad_helpers import log_audit
        log_audit(data.get('issuedBy', 'unknown'), 'create_bolo', 'Bolo', bolo_id)
    except Exception as e:
        db.session.rollback()
        logger.error(f'post_bolo DB error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500
    bolo_dict = bolo_to_dict(bolo_obj)
    send_bolo_discord(bolo_dict)
    emit_community_event('bolo:created', bolo_dict)
    return jsonify({'success': True, 'bolo': bolo_dict})


@police_required
@app.route('/api/bolo/<bolo_id>/clear', methods=['POST'])
def clear_bolo(bolo_id):
    b = scoped_query(Bolo).filter_by(bolo_id=bolo_id).first()
    if b is None:
        return jsonify({'success': False, 'error': 'BOLO not found.'}), 404
    b.status = 'Cleared'
    b.updated_at = datetime.utcnow()
    try:
        db.session.commit()
        from cad_helpers import log_audit
        log_audit('unknown', 'clear_bolo', 'Bolo', bolo_id)
    except Exception as e:
        db.session.rollback()
        logger.error(f'clear_bolo error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500
    emit_community_event('bolo:cleared', {'bolo_id': bolo_id, 'status': 'Cleared'})
    return jsonify({'success': True})


@police_required
@app.route('/api/ai/use-of-force', methods=['POST'])
def ai_use_of_force():
    api_key = os.environ.get('OPENROUTER_API_KEY', '')
    if not api_key:
        return jsonify({'success': False, 'error': 'OPENROUTER_API_KEY not configured.'}), 503

    data = request.get_json(silent=True) or {}
    officer       = data.get('officer', 'Unknown').strip()
    subject       = data.get('subject', 'Unknown').strip()
    location      = data.get('location', 'Unknown').strip()
    force_type    = data.get('forceType', '').strip()
    resistance    = data.get('resistance', '').strip()
    incident_desc = data.get('incidentDesc', '').strip()
    charges       = data.get('charges', '').strip()
    injuries      = data.get('injuries', '').strip()
    weapons       = data.get('weaponsObserved', 'No').strip()
    bodycam       = data.get('bodycam', 'Yes').strip()

    system_msg = """You are an AI-powered Computer Aided Dispatch (CAD) and legal report-writing system for GTAVCAD, a GTA V roleplay server set in Los Santos.
LOCATION RULES (CRITICAL): ALL locations must reference real GTA V map areas — Davis, Strawberry, Mission Row, Vespucci, Del Perro, Mirror Park, Route 68, Senora Freeway, Legion Square, Pillbox Hill Medical Center, Maze Bank Arena, etc.
USE OF FORCE REPORTS must be court-defensible: internally consistent, no contradictions, avoid vague phrases like 'acted suspicious', use only observable behaviour (e.g. 'subject repeatedly reached into waistband and ignored verbal commands'). Every escalation step must be justified. Force must match threat level. Flag any missing critical data as UNKNOWN – REQUIRES OFFICER INPUT."""

    user_msg = f"""Generate a complete Use of Force Report for GTAVCAD LSPD. Respond with ONLY a valid JSON object with these exact keys:

- "reportId": a realistic LSPD case number string (e.g. "UOF-2026-0047")
- "dateTime": today's date + a realistic time string (e.g. "May 05, 2026 — 22:14 hrs")
- "location": GTA V formatted location — convert any vague input to nearest GTA V equivalent
- "officerInvolved": officer name / badge
- "subjectInvolved": subject name
- "incidentSummary": 2-3 sentence objective overview of the incident
- "forceType": one of ["Presence", "Verbal Commands", "Physical Control", "Less Lethal (Taser/Baton)", "Lethal Force (Firearm)"]
- "reasonForForce": 2-3 sentences explaining exactly what the subject did to necessitate force, using observable behaviour only
- "resistanceLevel": one of ["Compliant", "Passive Resistance", "Active Resistance", "Assaultive", "Life-Threatening"]
- "threatAssessment": object with "weaponsObserved" (bool), "threatToOfficer" (bool), "threatToPublic" (bool), each with a one-sentence explanation
- "legalJustification": 3-4 sentence court-defensible paragraph tying officer actions to subject behaviour, emphasising proportional response under LSPD use-of-force policy
- "forceTimeline": array of 4-6 short step strings (e.g. ["Officer arrived at scene", "Initial verbal commands given", ...])
- "medicalAftercare": object with "emsRequested" (bool), "injuriesObserved" (string), "treatmentProvided" (string)
- "evidence": object with "bodycam" (bool), "witnesses" (string), "sceneEvidence" (string)
- "disposition": one of ["Arrested", "Hospitalized", "Arrested + Hospitalized", "Released — No Charges", "Deceased"]
- "chargesRecommended": comma-separated string of recommended charges (e.g. "Assault on Officer, Resisting Arrest")
- "liabilityWarning": string — if any critical justification data is missing or force seems disproportionate, return a warning starting with "⚠️ REPORT MAY BE LEGALLY WEAK –". Otherwise return empty string.
- "suspectFled": boolean — true if subject evaded or escaped, false otherwise
- "lastKnownLocation": if suspectFled true, specific GTA V street/area; otherwise empty string

Officer: {officer}
Subject: {subject}
Location: {location}
Force Type Used: {force_type if force_type else 'Not specified'}
Resistance Level: {resistance if resistance else 'Not specified'}
Weapons Observed: {weapons}
Bodycam: {bodycam}
Injuries: {injuries if injuries else 'None reported'}
Charges: {charges if charges else 'Not specified'}
Incident Description: {incident_desc if incident_desc else 'Not provided'}

Respond only with the JSON object. No markdown, no extra text."""

    try:
        payload = json.dumps({
            'model': 'openai/gpt-4o-mini',
            'messages': [
                {'role': 'system', 'content': system_msg},
                {'role': 'user', 'content': user_msg}
            ],
            'max_tokens': 900,
            'temperature': 0.5,
            'response_format': {'type': 'json_object'}
        }).encode('utf-8')

        req = urllib.request.Request(
            'https://openrouter.ai/api/v1/chat/completions',
            data=payload,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}',
                'HTTP-Referer': 'https://nthacityrp.com',
                'X-Title': 'GTAVCAD Police CAD'
            },
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=25) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            ai_json = json.loads(result['choices'][0]['message']['content'])
            auto_bolo = None
            if ai_json.get('suspectFled'):
                auto_bolo = create_bolo(
                    suspect_name=subject,
                    description=f'Subject fled after use-of-force incident. {incident_desc[:120] if incident_desc else ""}',
                    last_location=ai_json.get('lastKnownLocation', '') or location,
                    charges=charges or ai_json.get('chargesRecommended', ''),
                    officer=officer,
                    threat_level='High'
                )
            return jsonify({'success': True, 'report': ai_json, 'autoBolo': auto_bolo})
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        logger.error(f'OpenRouter UOF error: {e.code} {body}')
        return jsonify({'success': False, 'error': f'OpenRouter error {e.code}.'}), 502
    except Exception as e:
        logger.error(f'AI UOF generation failed: {e}')
        return jsonify({'success': False, 'error': 'Report generation failed. Try again.'}), 500


@police_required
@app.route('/api/ai/generate-bolo', methods=['POST'])
def ai_generate_bolo():
    api_key = os.environ.get('OPENROUTER_API_KEY', '')
    if not api_key:
        return jsonify({'success': False, 'error': 'OPENROUTER_API_KEY not configured.'}), 503

    data = request.get_json(silent=True) or {}
    charges = data.get('charges', '').strip()

    system_msg = """You are an AI-powered Computer Aided Dispatch (CAD) system for GTAVCAD, a GTA V roleplay server set in Los Santos.
LOCATION RULES (CRITICAL): ALL locations must be real GTA V map areas — Davis, Strawberry, Mission Row, Vespucci, Del Perro, Mirror Park, Rockford Hills, Sandy Shores, Route 68, Senora Freeway, Legion Square, Pillbox Hill, Maze Bank Arena, LSIA, La Mesa, Cypress Flats, etc.
VEHICLES: Use GTA V vehicle names — Baller, Dominator, Sultan, Kuruma, Sentinel, Schafter, Issi, Elegy, Banshee, Sandking, Granger, etc.
Generate realistic RP suspect profiles. No real-world references."""

    charge_hint = f" The suspect is wanted for: {charges}." if charges else " Pick a realistic crime scenario."

    user_msg = f"""Generate a realistic BOLO (Be On the Lookout) notice for an LSPD officer.{charge_hint}

Respond with ONLY a valid JSON object with these exact keys:
- "suspectName": realistic full name OR "Unknown Male" / "Unknown Female" if identity unconfirmed
- "description": 2-sentence physical description (gender, approx age, build, hair, clothing, distinguishing features like tattoos/scars)
- "lastLocation": specific GTA V street + area (e.g. "Covenant Ave & Forum Dr, Davis")
- "vehicle": GTA V vehicle name + color + partial plate (e.g. "Navy Blue Baller, partial plate 4KX") or "On foot" if no vehicle
- "charges": 1-3 charge strings (e.g. "Armed Robbery, Possession of Illegal Firearm")
- "threatLevel": "High", "Medium", or "Low" — based on severity of charges

Respond only with the JSON object. No markdown, no extra text."""

    try:
        payload = json.dumps({
            'model': 'openai/gpt-4o-mini',
            'messages': [
                {'role': 'system', 'content': system_msg},
                {'role': 'user', 'content': user_msg}
            ],
            'max_tokens': 350,
            'temperature': 0.85,
            'response_format': {'type': 'json_object'}
        }).encode('utf-8')

        req = urllib.request.Request(
            'https://openrouter.ai/api/v1/chat/completions',
            data=payload,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}',
                'HTTP-Referer': 'https://nthacityrp.com',
                'X-Title': 'GTAVCAD Police CAD'
            },
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            ai_json = json.loads(result['choices'][0]['message']['content'])
            return jsonify({'success': True, 'bolo': ai_json})
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        logger.error(f'OpenRouter generate-bolo error: {e.code} {body}')
        return jsonify({'success': False, 'error': f'OpenRouter error {e.code}.'}), 502
    except Exception as e:
        logger.error(f'AI BOLO generation failed: {e}')
        return jsonify({'success': False, 'error': 'BOLO generation failed. Try again.'}), 500


@app.route('/api/ai/police-report', methods=['POST'])
def ai_police_report():
    api_key = os.environ.get('OPENROUTER_API_KEY', '')
    if not api_key:
        return jsonify({'success': False, 'error': 'OPENROUTER_API_KEY not configured. Add it in your environment secrets.'}), 503

    data = request.get_json(silent=True) or {}
    suspect = data.get('suspectName', 'Unknown')
    charges = data.get('charges', 'Unknown')
    officer = data.get('arrestingOfficer', 'Unknown')
    location = data.get('arrestLocation', 'Unknown')
    evidence = data.get('evidenceAttached', 'None')
    penalty = data.get('penalty', 'Unknown')
    notes = data.get('reportNotes', '')

    system_msg = """You are an AI-powered Computer Aided Dispatch (CAD) system and report-writing assistant for a GTA V roleplay server called GTAVCAD set in Los Santos.
LOCATION RULES (CRITICAL): ALL locations must reference GTA V map areas, streets, or landmarks such as Davis, Strawberry, Mission Row, Vespucci, Del Perro, Mirror Park, Route 68, Great Ocean Highway, Senora Freeway, Legion Square, Pillbox Hill Medical Center, Maze Bank Arena. If a vague location is given, convert it to the closest GTA V equivalent.
Maintain a professional law enforcement tone. No breaking RP immersion. No real-world cities."""

    user_msg = f"""Generate an INCIDENT REPORT for the following arrest. Respond with ONLY a valid JSON object with exactly four keys:
- "narrative": a formal, professional arrest narrative (150-220 words, third-person past tense). Use INCIDENT REPORT MODE structure: include Date/Time, Location (GTA V formatted), Reporting Officer, Involved Parties, Incident Type, Narrative, Actions Taken, Evidence, Disposition.
- "suggestedPenalty": a short realistic penalty string (e.g. "3 years / $25,000 fine") based on the charges — if already provided, refine and return it.
- "suspectFled": boolean true if the narrative indicates the suspect evaded, escaped, fled, or was not apprehended — otherwise false.
- "lastKnownLocation": if suspectFled is true, a specific GTA V street/area where the suspect was last seen (e.g. "Elgin Ave & Adam's Apple Blvd, Strawberry") — otherwise empty string.

Suspect: {suspect}
Charges: {charges}
Arresting Officer: {officer}
Arrest Location: {location}
Evidence: {evidence}
Current Penalty: {penalty if penalty else 'Not specified'}
Officer Notes: {notes if notes else 'None provided'}

Respond only with the JSON object. No markdown, no extra text."""

    try:
        payload = json.dumps({
            'model': 'openai/gpt-4o-mini',
            'messages': [
                {'role': 'system', 'content': system_msg},
                {'role': 'user',   'content': user_msg}
            ],
            'max_tokens': 600,
            'temperature': 0.6,
            'response_format': {'type': 'json_object'}
        }).encode('utf-8')

        req = urllib.request.Request(
            'https://openrouter.ai/api/v1/chat/completions',
            data=payload,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}',
                'HTTP-Referer': 'https://nthacityrp.com',
                'X-Title': 'GTAVCAD Police CAD'
            },
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=25) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            ai_json = json.loads(result['choices'][0]['message']['content'])
            suspect_fled = ai_json.get('suspectFled', False)
            auto_bolo = None
            if suspect_fled:
                last_loc = ai_json.get('lastKnownLocation', '') or location
                auto_bolo = create_bolo(
                    suspect_name=suspect,
                    description=f'Suspect fled scene. Charges: {charges}.',
                    last_location=last_loc,
                    charges=charges,
                    officer=officer,
                    threat_level='High'
                )
                logger.info(f'Auto-BOLO created for {suspect} — fled scene')
            return jsonify({
                'success': True,
                'narrative': ai_json.get('narrative', ''),
                'suggestedPenalty': ai_json.get('suggestedPenalty', ''),
                'suspectFled': suspect_fled,
                'autoBolo': auto_bolo
            })
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        logger.error(f'OpenRouter API error: {e.code} {body}')
        return jsonify({'success': False, 'error': f'OpenRouter error {e.code}: check your API key and billing.'}), 502
    except Exception as e:
        logger.error(f'AI report generation failed: {e}')
        return jsonify({'success': False, 'error': 'Report generation failed. Try again.'}), 500


@app.route('/api/radio-log', methods=['GET'])
def get_radio_log():
    try:
        entries = scoped_query(RadioLog).order_by(RadioLog.created_at.desc()).limit(50).all()
        return jsonify({'success': True, 'entries': [radio_to_dict(r) for r in reversed(entries)]})
    except Exception as e:
        logger.error(f'Error loading radio log: {e}')
        return jsonify({'success': False, 'error': 'Failed to load radio log', 'code': 'RADIO_LOG_ERROR'}), 500


@app.route('/api/radio-log', methods=['POST'])
@police_required
def post_radio_log():
    data = request.get_json(silent=True) or {}
    unit = data.get('unit', '').strip()
    channel = data.get('channel', 'Primary').strip()
    message = data.get('message', '').strip()
    if not unit or not message:
        return jsonify({'success': False, 'error': 'Unit and message are required.'}), 400
    log_id = f"RADIO-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3)}"
    entry_obj = RadioLog(
        community_id=get_current_community_id(),
        log_id=log_id,
        unit=unit,
        channel=channel,
        message=message,
    )
    try:
        db.session.add(entry_obj)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f'post_radio_log error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500
    return jsonify({'success': True, 'entry': radio_to_dict(entry_obj)})


@app.route('/api/ai/dispatch', methods=['POST'])
@dispatch_required
def ai_dispatch():
    api_key = os.environ.get('OPENROUTER_API_KEY', '')
    if not api_key:
        return jsonify({'success': False, 'error': 'OPENROUTER_API_KEY not configured.'}), 503

    data = request.get_json(silent=True) or {}
    caller = data.get('callerName', 'Unknown')
    location = data.get('location', 'Unknown')
    description = data.get('description', '')

    system_msg = """You are an AI-powered Computer Aided Dispatch (CAD) system for GTAVCAD, a GTA V roleplay server set in Los Santos.
LOCATION RULES (CRITICAL): ALL locations must reference GTA V map areas — Davis, Strawberry, Mission Row, Vespucci, Del Perro, Mirror Park, Route 68, Senora Freeway, Legion Square, Pillbox Hill, Maze Bank Arena, etc. Convert vague locations to nearest GTA V equivalent.
DISPATCH LOGIC: Assign units using LSPD format (e.g. LSPD-1A23, LSPD-2B04) for city calls, BCSO format (e.g. BCSO-3C11) for county/highway calls, K9-01/K9-02 for dog units, AIR-1 for helicopter. Escalate priority for weapons, violence, or pursuit. Suggest backup when warranted.
Maintain professional law enforcement tone. No real-world city references."""

    user_msg = f"""Triage this 911 call using DISPATCH LOGIC. Respond with ONLY a valid JSON object with these exact keys:
- "incidentType": one of exactly ["Robbery", "Assault", "Suspicious activity", "Traffic accident", "Shots fired", "Domestic disturbance", "Drug activity", "Pursuit", "Hostage situation", "Noise complaint"]
- "priority": one of exactly ["Critical", "High", "Medium", "Low"] — Critical=active threat/shots/hostage, High=robbery/assault in progress, Medium=suspicious/drugs, Low=noise/minor
- "assignedUnit": realistic LSPD/BCSO unit designation based on location and incident type (e.g. "LSPD-1A23", "BCSO-2B11", "K9-02", "AIR-1")
- "status": always "New"
- "triage": one dispatcher-style sentence (max 20 words) summarising the call with GTA V location reference

Caller: {caller}
Location: {location}
Description: {description if description else 'No description provided'}

Respond only with the JSON object. No markdown, no extra text."""

    try:
        payload = json.dumps({
            'model': 'openai/gpt-4o-mini',
            'messages': [
                {'role': 'system', 'content': system_msg},
                {'role': 'user', 'content': user_msg}
            ],
            'max_tokens': 200,
            'temperature': 0.4,
            'response_format': {'type': 'json_object'}
        }).encode('utf-8')

        req = urllib.request.Request(
            'https://openrouter.ai/api/v1/chat/completions',
            data=payload,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}',
                'HTTP-Referer': 'https://nthacityrp.com',
                'X-Title': 'GTAVCAD Police CAD'
            },
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            ai_json = json.loads(result['choices'][0]['message']['content'])
            return jsonify({
                'success': True,
                'incidentType': ai_json.get('incidentType', ''),
                'priority': ai_json.get('priority', ''),
                'assignedUnit': ai_json.get('assignedUnit', ''),
                'status': ai_json.get('status', 'New'),
                'triage': ai_json.get('triage', '')
            })
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        logger.error(f'OpenRouter dispatch error: {e.code} {body}')
        return jsonify({'success': False, 'error': f'OpenRouter error {e.code}: check your API key.'}), 502
    except Exception as e:
        logger.error(f'AI dispatch triage failed: {e}')
        return jsonify({'success': False, 'error': 'Triage failed. Try again.'}), 500


@police_required
@app.route('/api/ai/warrant', methods=['POST'])
def ai_warrant():
    api_key = os.environ.get('OPENROUTER_API_KEY', '')
    if not api_key:
        return jsonify({'success': False, 'error': 'OPENROUTER_API_KEY not configured.'}), 503

    data = request.get_json(silent=True) or {}
    suspect = data.get('warrantName', 'Unknown')
    charges = data.get('warrantCharges', 'Unknown')
    issuer = data.get('warrantIssuer', 'Unknown')
    existing_notes = data.get('warrantNotes', '')

    system_msg = """You are an AI-powered Computer Aided Dispatch (CAD) system and report-writing assistant for GTAVCAD, a GTA V roleplay server set in Los Santos.
LOCATION RULES (CRITICAL): ALL locations must reference GTA V map areas — Davis, Strawberry, Mission Row, Vespucci, Del Perro, Mirror Park, Route 68, Senora Freeway, Legion Square, Pillbox Hill, Maze Bank Arena, etc.
Write in professional law enforcement language. Ground all references in Los Santos / San Andreas. No real-world city names."""

    user_msg = f"""Generate an arrest warrant justification. Respond with ONLY a valid JSON object with exactly two keys:
- "justification": a formal probable-cause warrant justification (80-130 words) written in official LSPD legal language. Reference GTA V locations where relevant. Include probable cause, evidence basis, and the threat to public safety in Los Santos.
- "suggestedStatus": always return "Active"

Suspect: {suspect}
Charges: {charges}
Issued By: {issuer}
Additional Notes: {existing_notes if existing_notes else 'None'}

Respond only with the JSON object. No markdown, no extra text."""

    from datetime import timedelta
    expiration_date = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')

    try:
        payload = json.dumps({
            'model': 'openai/gpt-4o-mini',
            'messages': [
                {'role': 'system', 'content': system_msg},
                {'role': 'user', 'content': user_msg}
            ],
            'max_tokens': 300,
            'temperature': 0.7,
            'response_format': {'type': 'json_object'}
        }).encode('utf-8')

        req = urllib.request.Request(
            'https://openrouter.ai/api/v1/chat/completions',
            data=payload,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}',
                'HTTP-Referer': 'https://nthacityrp.com',
                'X-Title': 'GTAVCAD Police CAD'
            },
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            ai_json = json.loads(result['choices'][0]['message']['content'])
            return jsonify({
                'success': True,
                'justification': ai_json.get('justification', ''),
                'suggestedStatus': ai_json.get('suggestedStatus', 'Active'),
                'suggestedExpiration': expiration_date
            })
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        logger.error(f'OpenRouter warrant error: {e.code} {body}')
        return jsonify({'success': False, 'error': f'OpenRouter error {e.code}: check your API key.'}), 502
    except Exception as e:
        logger.error(f'AI warrant generation failed: {e}')
        return jsonify({'success': False, 'error': 'Warrant generation failed. Try again.'}), 500


@app.route('/api/ai/generate-call', methods=['POST'])
@dispatch_required
def ai_generate_call():
    api_key = os.environ.get('OPENROUTER_API_KEY', '')
    if not api_key:
        return jsonify({'success': False, 'error': 'OPENROUTER_API_KEY not configured.'}), 503

    data = request.get_json(silent=True) or {}
    call_type = data.get('callType', '').strip()

    system_msg = """You are an AI-powered Computer Aided Dispatch (CAD) system for GTAVCAD, a GTA V roleplay server set in Los Santos.
CALL GENERATION MODE: Generate fully realistic GTA V emergency calls.
LOCATION RULES (CRITICAL): ALL locations must be real GTA V map areas — Davis, Strawberry, Mission Row, Vespucci, Del Perro, Mirror Park, Rockford Hills, Sandy Shores, Paleto Bay, Route 68, Senora Freeway, Great Ocean Highway, Legion Square, Pillbox Hill Medical Center, Maze Bank Arena, LSIA, La Mesa, Cypress Flats, etc.
DISPATCH LOGIC: Assign LSPD units (LSPD-1A23, LSPD-2B04) for city calls, BCSO (BCSO-3C11) for county/highway, K9-01/K9-02, AIR-1 for helicopter. Escalate priority based on severity.
Generate realistic caller names (first + last). The transcript must feel like a real 911 call — dispatcher asks clarifying questions, caller may be panicked or calm depending on incident. No real-world references."""

    type_hint = f" The call type should be: {call_type}." if call_type else " Pick a random realistic incident type."

    user_msg = f"""Generate a complete GTA V 911 emergency call for an LSPD dispatch session.{type_hint}

Respond with ONLY a valid JSON object with these exact keys:
- "callType": the incident type (e.g. "Shots Fired", "Traffic Accident", "Armed Robbery", "Domestic Disturbance", "Pursuit", "Suspicious Person", "Drug Activity", "Assault in Progress")
- "caller": realistic full name of the caller
- "location": specific GTA V street, area, or landmark (e.g. "Forum Drive & Covenant Ave, Davis" or "Route 68 near Harmony")
- "description": 2-3 sentences of what the caller describes to dispatch
- "dispatchNotes": 1-2 sentences of internal dispatcher notes (unit recommendation, hazards, backup needed)
- "priority": one of "Critical", "High", "Medium", "Low"
- "assignedUnit": LSPD/BCSO unit designation (e.g. "LSPD-1A23", "BCSO-2B11", "AIR-1", "K9-02")
- "transcript": an array of 6-10 objects, each with "speaker" ("Dispatch" or "Caller") and "line" (the spoken dialogue). Make it realistic — dispatcher confirms location, caller may be scared or urgent, dispatcher gives instructions and confirms unit en route.

Respond only with the JSON object. No markdown, no extra text."""

    try:
        payload = json.dumps({
            'model': 'openai/gpt-4o-mini',
            'messages': [
                {'role': 'system', 'content': system_msg},
                {'role': 'user', 'content': user_msg}
            ],
            'max_tokens': 800,
            'temperature': 0.9,
            'response_format': {'type': 'json_object'}
        }).encode('utf-8')

        req = urllib.request.Request(
            'https://openrouter.ai/api/v1/chat/completions',
            data=payload,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}',
                'HTTP-Referer': 'https://nthacityrp.com',
                'X-Title': 'GTAVCAD Police CAD'
            },
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=25) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            ai_json = json.loads(result['choices'][0]['message']['content'])
            return jsonify({'success': True, 'call': ai_json})
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        logger.error(f'OpenRouter generate-call error: {e.code} {body}')
        return jsonify({'success': False, 'error': f'OpenRouter error {e.code}.'}), 502
    except Exception as e:
        logger.error(f'AI call generation failed: {e}')
        return jsonify({'success': False, 'error': 'Call generation failed. Try again.'}), 500


@app.route('/api/ai/incident-summary', methods=['POST'])
def ai_incident_summary():
    api_key = os.environ.get('OPENROUTER_API_KEY', '')
    if not api_key:
        return jsonify({'success': False, 'error': 'OPENROUTER_API_KEY not configured.'}), 503

    data = request.get_json(silent=True) or {}
    notes = data.get('notes', '').strip()

    if not notes:
        return jsonify({'success': False, 'error': 'No CAD notes provided.'}), 400

    system_msg = """You are an AI-powered Computer Aided Dispatch (CAD) system and report-writing assistant for GTAVCAD, a GTA V roleplay server set in Los Santos.
LOCATION RULES (CRITICAL): ALL locations must reference GTA V map areas — Davis, Strawberry, Mission Row, Vespucci, Del Perro, Mirror Park, Route 68, Senora Freeway, Legion Square, Pillbox Hill, Maze Bank Arena, etc. Convert any vague or real-world locations to the closest GTA V equivalent.
OUTPUT: Generate Discord-formatted (#criminal-files channel) summaries. Use INCIDENT REPORT MODE structure. Professional law enforcement tone only."""

    user_msg = f"""An officer has provided raw CAD notes. Generate a clean Discord-formatted incident summary for the #criminal-files channel.

Rules:
- Use **bold** for all section labels
- Use a `code block` only for case/report numbers if present
- Max 200 words
- Sections (include if data available): **Incident Type**, **Location** (GTA V formatted), **Date/Time**, **Officers Involved**, **Unit(s)**, **Suspect(s)**, **Charges**, **Outcome**, **Notes**
- End with: ―――――――――――――――――――――
- Raw Discord markdown only — no wrapper blocks

Raw CAD Notes:
{notes}

Respond with ONLY a valid JSON object with one key:
- "summary": the full Discord-formatted incident summary string"""

    try:
        payload = json.dumps({
            'model': 'openai/gpt-4o-mini',
            'messages': [
                {'role': 'system', 'content': system_msg},
                {'role': 'user', 'content': user_msg}
            ],
            'max_tokens': 500,
            'temperature': 0.4,
            'response_format': {'type': 'json_object'}
        }).encode('utf-8')

        req = urllib.request.Request(
            'https://openrouter.ai/api/v1/chat/completions',
            data=payload,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}',
                'HTTP-Referer': 'https://nthacityrp.com',
                'X-Title': 'GTAVCAD Police CAD'
            },
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            ai_json = json.loads(result['choices'][0]['message']['content'])
            return jsonify({'success': True, 'summary': ai_json.get('summary', '')})
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        logger.error(f'OpenRouter incident summary error: {e.code} {body}')
        return jsonify({'success': False, 'error': f'OpenRouter error {e.code}.'}), 502
    except Exception as e:
        logger.error(f'AI incident summary failed: {e}')
        return jsonify({'success': False, 'error': 'Summary failed. Try again.'}), 500


@app.route('/api/ai/suspect-match', methods=['POST'])
def ai_suspect_match():
    api_key = os.environ.get('OPENROUTER_API_KEY', '')
    if not api_key:
        return jsonify({'success': False, 'error': 'OPENROUTER_API_KEY not configured.'}), 503

    data = request.get_json(silent=True) or {}
    description = data.get('description', '').strip()
    civilians = data.get('civilians', [])

    if not description:
        return jsonify({'success': False, 'error': 'No description provided.'}), 400

    if not civilians:
        return jsonify({'success': True, 'matches': [], 'note': 'No civilians registered in the system yet.'})

    civ_list = '\n'.join([
        f"- Name: {c.get('firstName','?')} {c.get('lastName','?')} | DOB: {c.get('dob','?')} | Gender: {c.get('gender','?')} | Occupation: {c.get('occupation','?')} | Notes: {c.get('notes','')}"
        for c in civilians[:50]
    ])

    system_msg = """You are an AI-powered suspect identification assistant for GTAVCAD, a GTA V roleplay server set in Los Santos.
You help LSPD officers cross-reference physical suspect descriptions against the civilian registry. Be precise and analytical. Only match civilians where there is genuine physical basis. Maintain professional law enforcement tone."""

    user_msg = f"""An LSPD officer has provided a physical description of a suspect spotted in Los Santos. Cross-reference the registered civilian database and return the top matches.

Respond with ONLY a valid JSON object with one key:
- "matches": array of up to 3 objects, each with:
  - "name": full civilian name
  - "confidence": "High", "Medium", or "Low"
  - "reason": one short sentence (max 15 words) citing specific matching physical traits

If no civilians reasonably match, return an empty matches array.

Suspect Description: {description}

Registered Civilians:
{civ_list}

Respond only with the JSON object. No markdown, no extra text."""

    try:
        payload = json.dumps({
            'model': 'openai/gpt-4o-mini',
            'messages': [
                {'role': 'system', 'content': system_msg},
                {'role': 'user', 'content': user_msg}
            ],
            'max_tokens': 300,
            'temperature': 0.3,
            'response_format': {'type': 'json_object'}
        }).encode('utf-8')

        req = urllib.request.Request(
            'https://openrouter.ai/api/v1/chat/completions',
            data=payload,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}',
                'HTTP-Referer': 'https://nthacityrp.com',
                'X-Title': 'GTAVCAD Police CAD'
            },
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            ai_json = json.loads(result['choices'][0]['message']['content'])
            return jsonify({'success': True, 'matches': ai_json.get('matches', [])})
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        logger.error(f'OpenRouter suspect match error: {e.code} {body}')
        return jsonify({'success': False, 'error': f'OpenRouter error {e.code}.'}), 502
    except Exception as e:
        logger.error(f'AI suspect match failed: {e}')
        return jsonify({'success': False, 'error': 'Match failed. Try again.'}), 500


@app.route('/api/officer-status', methods=['PATCH'])
def patch_officer_status():
    denied = require_police_cad_access()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    officer_id = data.get('id', '').strip()
    new_status = data.get('status', '').strip()
    valid_statuses = ['Available', 'Assigned', 'En Route', 'On Scene', 'Busy', 'Off Duty', 'Active', 'On Duty']
    if not officer_id or new_status not in valid_statuses:
        return jsonify({'success': False, 'error': 'invalid id or status'}), 400
    try:
        ensure_officer_sessions_schema()
    except Exception as e:
        logger.error(f'patch_officer_status schema error: {e}')
        return jsonify({'success': False, 'error': 'Unable to update officer status.'}), 500
    community_id = get_current_community_id()
    s = scoped_query(OfficerSession, community_id).filter_by(callsign=officer_id).first()
    if s is None:
        s = OfficerSession(
            community_id=community_id,
            callsign=officer_id,
            officer_name=data.get('name', officer_id),
            department=data.get('department', ''),
        )
        db.session.add(s)
    s.status = new_status
    s.updated_at = datetime.utcnow()
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f'patch_officer_status error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500
    logger.info(f"Officer status update: {officer_id} → {new_status}")
    return jsonify({'success': True})


@app.route('/api/officer-sessions', methods=['GET'])
def get_officer_sessions():
    denied = require_police_cad_access()
    if denied:
        return denied
    try:
        ensure_officer_sessions_schema()
        sessions = scoped_query(OfficerSession).all()
    except Exception as e:
        logger.error(f'get_officer_sessions error: {e}')
        return jsonify({'success': False, 'error': 'Unable to load officer sessions.'}), 500
    result = {s.callsign: session_to_dict(s) for s in sessions}
    return jsonify({'success': True, 'sessions': result})


@app.route('/api/officer-sessions/active', methods=['GET'])
def get_active_officer_sessions():
    denied = require_police_cad_access()
    if denied:
        return denied
    try:
        ensure_officer_sessions_schema()
        sessions = scoped_query(OfficerSession).filter_by(status='On Duty').order_by(OfficerSession.updated_at.desc()).all()
    except Exception as e:
        logger.error(f'get_active_officer_sessions error: {e}')
        return jsonify({'success': False, 'error': 'Unable to load active officer sessions.'}), 500
    return jsonify({'success': True, 'sessions': [session_to_dict(s) for s in sessions]})


@app.route('/api/officer-session', methods=['POST'])
def post_officer_session():
    denied = require_police_cad_access()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    callsign = (data.get('callsign') or '').strip()
    name = (data.get('officer_name') or data.get('officerName') or data.get('name') or '').strip()
    department = (data.get('department') or '').strip()
    if not callsign:
        return jsonify({'success': False, 'error': 'Callsign is required.'}), 400
    if not name:
        return jsonify({'success': False, 'error': 'Officer name is required.'}), 400
    if not department:
        return jsonify({'success': False, 'error': 'Department is required.'}), 400

    try:
        ensure_officer_sessions_schema()
        s = scoped_query(OfficerSession).filter_by(callsign=callsign).first()
        if s is not None and (s.status or '').strip().lower() == 'on duty':
            return jsonify({'success': False, 'error': 'Callsign already in use.'}), 409
        now = datetime.utcnow()
        if s is None:
            s = OfficerSession(community_id=get_current_community_id(), callsign=callsign)
            db.session.add(s)
        s.officer_name = name
        s.department = department
        s.status = 'On Duty'
        s.logged_in_at = now
        s.updated_at = now
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f'post_officer_session error: {e}')
        return jsonify({'success': False, 'error': 'Unable to start officer session.'}), 500

    logger.info(f"Officer login: {callsign} ({name}) — {department}")
    return jsonify({'success': True, 'session': officer_session_response(s)})


@app.route('/api/officer-sessions/end', methods=['POST'])
def end_officer_session():
    denied = require_police_cad_access()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    callsign = (data.get('callsign') or '').strip()
    if not callsign:
        return jsonify({'success': False, 'error': 'Callsign is required.'}), 400
    try:
        ensure_officer_sessions_schema()
        s = scoped_query(OfficerSession).filter_by(callsign=callsign).first()
        if s:
            s.status = 'Off Duty'
            s.updated_at = datetime.utcnow()
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f'end_officer_session error: {e}')
        return jsonify({'success': False, 'error': 'Unable to end officer session.'}), 500
    logger.info(f"Officer end shift: {callsign}")
    return jsonify({'success': True})


@app.route('/api/officer-session/<callsign>', methods=['DELETE'])
def delete_officer_session(callsign):
    # Backward-compatible endpoint for older Police/CAD clients.
    return end_officer_session_for_callsign(callsign)


def end_officer_session_for_callsign(callsign):
    try:
        ensure_officer_sessions_schema()
        s = scoped_query(OfficerSession).filter_by(callsign=callsign).first()
        if s:
            s.status = 'Off Duty'
            s.updated_at = datetime.utcnow()
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f'delete_officer_session error: {e}')
        return jsonify({'success': False, 'error': 'Unable to end officer session.'}), 500
    logger.info(f"Officer end shift: {callsign}")
    return jsonify({'success': True})


@app.route('/api/alerts', methods=['GET'])
def get_alerts():
    denied = require_police_cad_access()
    if denied:
        return denied
    since = request.args.get('since', '')
    query = scoped_query(Alert).order_by(Alert.created_at.desc()).limit(100)
    alerts = [alert_to_dict(a) for a in query.all()]
    if since:
        alerts = [a for a in alerts if (a.get('issuedAt') or '') > since]
    return jsonify({'alerts': alerts[:20]})


@app.route('/api/alert', methods=['POST'])
def post_alert():
    data = request.get_json(silent=True) or {}
    alert_type = data.get('type', '').strip()
    message = data.get('message', '').strip()
    issued_by = data.get('issuedBy', 'Dispatch').strip()
    valid_types = ['PANIC', 'BOLO', 'ALL UNITS', 'CODE RED']
    if not alert_type or not message:
        return jsonify({'success': False, 'error': 'type and message are required'}), 400
    if alert_type not in valid_types:
        return jsonify({'success': False, 'error': f'Invalid type. Must be one of: {", ".join(valid_types)}'}), 400
    alert_id = f"ALERT-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3)}"
    alert_obj = Alert(
        community_id=get_current_community_id(),
        alert_id=alert_id,
        alert_type=alert_type,
        message=message,
        issued_by=issued_by,
    )
    try:
        db.session.add(alert_obj)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f'post_alert error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500
    alert_dict = alert_to_dict(alert_obj)
    logger.info(f"Alert broadcast: {alert_id} — {alert_type} by {issued_by}")
    return jsonify({'success': True, 'alert': alert_dict})



@police_required
@app.route('/api/cad/arrests', methods=['POST'])
def create_arrest_report():
    body = request.get_json(silent=True) or {}
    for field in ('suspectName', 'charges', 'arrestingOfficer', 'arrestLocation'):
        if not body.get(field):
            return jsonify({'success': False, 'error': f'Missing required field: {field}'}), 400

    arrest_id = body.get('id') or body.get('arrestId') or body.get('arrest_id') or f"arr-{int(datetime.utcnow().timestamp() * 1000)}-{secrets.token_hex(4)}"
    community_id = get_current_community_id()
    arrest = scoped_query(Arrest, community_id).filter_by(arrest_id=arrest_id).first()
    if arrest is None:
        arrest = Arrest(community_id=community_id, arrest_id=arrest_id, created_at=datetime.utcnow())
        db.session.add(arrest)

    try:
        _apply_arrest_payload(arrest, {**body, 'id': arrest_id})
        db.session.flush()
        _ensure_arrest_custody_and_hearing(arrest)
        db.session.commit()
        logger.info(f'Arrest saved and committed: {arrest.arrest_id}')
        from cad_helpers import log_audit
        from security_service import get_current_user
        user = get_current_user()
        log_audit(user['user_id'] or body.get('arrestingOfficer', 'unknown'), 'create_arrest', 'Arrest', arrest.arrest_id, actor_role=user['role'], ip_address=user['ip'])
        return jsonify({'success': True, 'arrest': arrest_to_dict(arrest)})
    except Exception as e:
        db.session.rollback()
        logger.error(f'create_arrest_report error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/cad', methods=['GET'])
@app.route('/api/cad/data', methods=['GET'])
def get_cad_data():
    denied = require_police_cad_access()
    if denied:
        return denied
    try:
        data = load_cad_data()
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        logger.error(f'Error loading CAD data: {e}')
        return jsonify({'success': False, 'error': 'Failed to load CAD data', 'code': 'LOAD_ERROR'}), 500


@app.route('/api/cad', methods=['POST'])
@app.route('/api/cad/data', methods=['POST'])
def post_cad_data():
    denied = require_police_cad_access()
    if denied:
        return denied
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error': 'Invalid payload'}), 400

    try:
        save_cad_data(data)
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        logger.error(f'Error saving CAD data: {e}')
        return jsonify({'success': False, 'error': str(e), 'code': 'SAVE_ERROR'}), 500

@app.route('/api/ai/shift-summary', methods=['POST'])
def ai_shift_summary():
    api_key = os.environ.get('OPENROUTER_API_KEY', '')
    if not api_key:
        return jsonify({'success': False, 'error': 'OPENROUTER_API_KEY not configured.'}), 503

    data     = request.get_json(silent=True) or {}
    officer  = data.get('officer',    'Unknown')
    callsign = data.get('callsign',   '')
    dept     = data.get('department', '')
    started  = data.get('shiftStart', 'Unknown')
    calls    = data.get('calls',        [])
    arrests  = data.get('arrests',      [])
    warrants = data.get('warrants',     [])
    traffic  = data.get('trafficStops', [])

    def fmt_calls(lst):
        lines = [f"- [{c.get('priority','?')}] {c.get('incidentType','Unknown')} @ {c.get('location','?')} — {c.get('status','?')}" for c in lst[:8]]
        return '\n'.join(lines) if lines else 'None'

    def fmt_arrests(lst):
        lines = [f"- {a.get('suspectName','?')}: {a.get('charges','?')} | Penalty: {a.get('penalty','?')}" for a in lst[:8]]
        return '\n'.join(lines) if lines else 'None'

    def fmt_warrants(lst):
        lines = [f"- {w.get('warrantName', w.get('suspectName','?'))}: {w.get('warrantCharges', w.get('charges','?'))} ({w.get('warrantStatus', w.get('status','Active'))})" for w in lst[:8]]
        return '\n'.join(lines) if lines else 'None'

    def fmt_traffic(lst):
        lines = [f"- {t.get('driverName','?')} ({t.get('trafficPlate', t.get('plate','?'))}): {t.get('trafficReason', t.get('reason','?'))} → {t.get('trafficOutcome', t.get('outcome','?'))}" for t in lst[:8]]
        return '\n'.join(lines) if lines else 'None'

    system_msg = (
        "You are an AI report-writing assistant for GTAVCAD, a GTA V roleplay server set in Los Santos. "
        "Write professional law enforcement shift summaries for Discord posting. Use GTA V location and street names. "
        "Keep it RP-immersive, third-person, professional tone. No real-world city references."
    )

    user_msg = f"""Generate a Discord-ready end-of-shift summary for this officer. Use Discord markdown (bold with **, bullets with •). No # headers.

Officer: {officer} ({callsign}) — {dept}
Shift Started: {started}

Calls Handled ({len(calls)} total):
{fmt_calls(calls)}

Arrests Made ({len(arrests)} total):
{fmt_arrests(arrests)}

Warrants Issued ({len(warrants)} total):
{fmt_warrants(warrants)}

Traffic Stops ({len(traffic)} total):
{fmt_traffic(traffic)}

Structure: one opening sentence → **Calls** section → **Arrests** section → **Warrants** section → **Traffic Stops** section → professional closing line. Under 300 words. Plain Discord text only, no JSON."""

    try:
        payload = json.dumps({
            'model': 'openai/gpt-4o-mini',
            'messages': [
                {'role': 'system', 'content': system_msg},
                {'role': 'user',   'content': user_msg}
            ],
            'max_tokens': 500,
            'temperature': 0.6,
        }).encode('utf-8')
        req = urllib.request.Request(
            'https://openrouter.ai/api/v1/chat/completions',
            data=payload,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}',
                'HTTP-Referer': 'https://nthacityrp.com',
                'X-Title': 'GTAVCAD Police CAD'
            },
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=25) as resp:
            result  = json.loads(resp.read().decode('utf-8'))
            summary = result['choices'][0]['message']['content']
            return jsonify({'success': True, 'summary': summary})
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        logger.error(f'OpenRouter shift-summary error: {e.code} {body}')
        return jsonify({'success': False, 'error': f'OpenRouter error {e.code}.'}), 502
    except Exception as e:
        logger.error(f'AI shift summary failed: {e}')
        return jsonify({'success': False, 'error': 'Shift summary failed. Try again.'}), 500


@app.route('/api/court/hearings', methods=['GET'])
def get_hearings():
    denied = require_police_cad_access()
    if denied:
        return denied
    hearings = scoped_query(Hearing).order_by(Hearing.scheduled_at.desc()).all()
    return jsonify({'success': True, 'hearings': [hearing_to_dict(h) for h in hearings]})


@judge_required
@app.route('/api/court/hearings', methods=['POST'])
def create_hearing():
    denied = require_police_cad_access()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    for field in ('suspectName', 'charges', 'hearingType', 'scheduledAt', 'filingOfficer'):
        if not body.get(field):
            return jsonify({'success': False, 'error': f'Missing required field: {field}'}), 400
    ts = int(datetime.utcnow().timestamp() * 1000)
    rand = secrets.token_hex(5)
    hearing_obj = Hearing(
        community_id=get_current_community_id(),
        hearing_id=f'hearing-{ts}-{rand}',
        civilian_id=body.get('civilianId', body.get('civilian_id', '')),
        suspect_name=body.get('suspectName', '').strip(),
        charges=body.get('charges', '').strip(),
        hearing_type=body.get('hearingType', 'Arraignment'),
        scheduled_at=body.get('scheduledAt', ''),
        judge=body.get('judge', '').strip(),
        notes=body.get('notes', '').strip(),
        arrest_id=body.get('arrestId', ''),
        filing_officer=body.get('filingOfficer', '').strip(),
        outcome='',
        sentence_length='',
        fine_amount='',
        outcome_notes='',
        status='Scheduled',
    )
    try:
        db.session.add(hearing_obj)
        db.session.commit()
        from cad_helpers import log_audit
        log_audit(body.get('filingOfficer', 'unknown'), 'create_hearing', 'Hearing', hearing_obj.hearing_id)
    except Exception as e:
        db.session.rollback()
        logger.error(f'create_hearing error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500
    return jsonify({'success': True, 'hearing': hearing_to_dict(hearing_obj)})


@judge_required
@app.route('/api/court/hearings/<hearing_id>', methods=['PUT'])
def update_hearing(hearing_id):
    denied = require_police_cad_access()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    h = scoped_query(Hearing).filter_by(hearing_id=hearing_id).first()
    if h is None:
        return jsonify({'success': False, 'error': 'Hearing not found'}), 404
    if 'outcome' in body:
        h.outcome = body['outcome']
    if 'sentenceLength' in body:
        h.sentence_length = body['sentenceLength']
    if 'fineAmount' in body:
        h.fine_amount = body['fineAmount']
    if 'outcomeNotes' in body:
        h.outcome_notes = body['outcomeNotes']
    if 'status' in body:
        h.status = body['status']
    if 'judge' in body:
        h.judge = body['judge']
    if 'notes' in body:
        h.notes = body['notes']
    if 'scheduledAt' in body:
        h.scheduled_at = body['scheduledAt']
    h.updated_at = datetime.utcnow()
    _sync_custody_from_completed_hearing(h)
    try:
        db.session.commit()
        from cad_helpers import log_audit
        log_audit('judge', 'update_hearing', 'Hearing', hearing_id)
    except Exception as e:
        db.session.rollback()
        logger.error(f'update_hearing error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500
    return jsonify({'success': True, 'hearing': hearing_to_dict(h)})


@judge_required
@app.route('/api/court/hearings/<hearing_id>', methods=['DELETE'])
def delete_hearing(hearing_id):
    denied = require_police_cad_access()
    if denied:
        return denied
    h = scoped_query(Hearing).filter_by(hearing_id=hearing_id).first()
    if h is None:
        return jsonify({'success': False, 'error': 'Hearing not found'}), 404
    try:
        db.session.delete(h)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f'delete_hearing error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500
    return jsonify({'success': True})


@app.route('/api/jail/inmates', methods=['GET'])
def get_inmates():
    denied = require_police_cad_access()
    if denied:
        return denied
    inmates = scoped_query(Inmate).order_by(Inmate.booked_at.desc()).all()
    return jsonify({'success': True, 'inmates': [inmate_to_dict(i) for i in inmates]})


@app.route('/api/jail/inmates', methods=['POST'])
def book_inmate():
    denied = require_police_cad_access()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    for field in ('suspectName', 'charges', 'bookedBy'):
        if not body.get(field):
            return jsonify({'success': False, 'error': f'Missing required field: {field}'}), 400
    ts = int(datetime.utcnow().timestamp() * 1000)
    rand = secrets.token_hex(4)
    inmate_obj = Inmate(
        community_id=get_current_community_id(),
        inmate_id=f'inmate-{ts}-{rand}',
        suspect_name=body.get('suspectName', '').strip(),
        charges=body.get('charges', '').strip(),
        penalty=body.get('penalty', '').strip(),
        cell=body.get('cell', '').strip(),
        booked_by=body.get('bookedBy', '').strip(),
        arrest_id=body.get('arrestId', ''),
        estimated_release=body.get('estimatedRelease', ''),
        notes=body.get('notes', '').strip(),
        status='In Custody',
    )
    try:
        db.session.add(inmate_obj)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f'book_inmate error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500
    return jsonify({'success': True, 'inmate': inmate_to_dict(inmate_obj)})


@app.route('/api/jail/inmates/<inmate_id>', methods=['PUT'])
def update_inmate(inmate_id):
    denied = require_police_cad_access()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    inmate = scoped_query(Inmate).filter_by(inmate_id=inmate_id).first()
    if inmate is None:
        return jsonify({'success': False, 'error': 'Inmate not found'}), 404
    if 'estimatedRelease' in body:
        inmate.estimated_release = body['estimatedRelease']
    if 'cell' in body:
        inmate.cell = body['cell']
    if 'notes' in body:
        inmate.notes = body['notes']
    if 'penalty' in body:
        inmate.penalty = body['penalty']
    if 'status' in body:
        inmate.status = body['status']
    inmate.updated_at = datetime.utcnow()
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f'update_inmate error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500
    return jsonify({'success': True, 'inmate': inmate_to_dict(inmate)})


@app.route('/api/jail/inmates/<inmate_id>/release', methods=['POST'])
def release_inmate(inmate_id):
    denied = require_police_cad_access()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    inmate = scoped_query(Inmate).filter_by(inmate_id=inmate_id).first()
    if inmate is None:
        return jsonify({'success': False, 'error': 'Inmate not found'}), 404
    inmate.status = 'Released'
    inmate.released_at = datetime.utcnow()
    inmate.released_by = body.get('releasedBy', 'Officer').strip()
    inmate.release_reason = body.get('releaseReason', '').strip()
    inmate.updated_at = datetime.utcnow()
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f'release_inmate error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500
    return jsonify({'success': True, 'inmate': inmate_to_dict(inmate)})


# ---------------------------------------------------------------------------
# AI Civilian Generation
# ---------------------------------------------------------------------------

@app.route('/api/ai/civilian', methods=['POST'])
@admin_required
def generate_ai_civilian():
    """Generate and save an AI civilian."""
    from civilian_ai_service import generate_and_save_civilian
    from cad_helpers import log_audit

    try:
        civilian_data = generate_and_save_civilian()
        log_audit('ai', 'generate_civilian', 'Civilian', civilian_data['civilian_id'])

        return jsonify({
            'success': True,
            'civilian': civilian_data,
            'message': f"Generated {civilian_data['full_name']}"
        })
    except ValueError as e:
        logger.error(f'Duplicate prevention failed: {e}')
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400
    except Exception as e:
        logger.error(f'Failed to generate civilian: {e}')
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ---------------------------------------------------------------------------
# AI Assist — Civilian Generator (public, no admin required)
# ---------------------------------------------------------------------------

@app.route('/api/ai/civilian-assist', methods=['POST'])
def ai_civilian_assist():
    """Generate civilian data for form population (NO auto-save)."""
    try:
        params = request.get_json() or {}

        from ai_assist_service import generate_ai_civilian

        civilian_data, source = generate_ai_civilian(params)

        if 'error' in civilian_data:
            return jsonify({'success': False, 'error': civilian_data['error']}), 400

        # Return ONLY form-visible fields
        return jsonify({
            'success': True,
            'data': civilian_data,
            'source': source,
        }), 200

    except Exception as e:
        logger.error(f'AI assist error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/civilians', methods=['POST'])
def create_civilian():
    """Persist a Civilian Registration payload directly to PostgreSQL."""
    try:
        data = request.get_json(silent=True) or {}
        mapped = _civilian_from_payload(data)

        if not mapped['first_name'] or not mapped['last_name']:
            return jsonify({'success': False, 'error': 'firstName and lastName are required'}), 400

        civilian_id = f"CIV-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3)}"
        civilian = Civilian(community_id=community_id, civilian_id=civilian_id, **mapped)

        db.session.add(civilian)
        db.session.commit()

        logger.info('Civilian insert success: civilian_id=%s name="%s %s" plate="%s"',
                    civilian.civilian_id, civilian.first_name, civilian.last_name, civilian.plate_number or '')

        return jsonify({
            'success': True,
            'civilian_id': civilian.civilian_id,
            'civilian': _civilian_response(civilian),
        }), 201

    except Exception as e:
        db.session.rollback()
        logger.error(f'Failed to create civilian: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/civilians', methods=['GET'])
def get_civilians():
    """Read civilian records directly from PostgreSQL with q/name/dob filters."""
    q = request.args.get('q', '').strip()
    name = request.args.get('name', '').strip()
    dob = request.args.get('dob', '').strip()

    try:
        logger.info('Civilian lookup query: q="%s" name="%s" dob="%s"', q, name, dob)
        civilians = (_civilian_search_query(q, name=name, dob=dob)
                     .order_by(Civilian.created_at.desc())
                     .limit(100)
                     .all())
        result = [_civilian_response(c) for c in civilians]
        logger.info('Civilian lookup result count: %s', len(result))
        return jsonify({'success': True, 'civilians': result, 'results': result, 'total': len(result)})
    except Exception as e:
        logger.error(f'Civilian lookup error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/civilian/search', methods=['POST'])
def search_civilians():
    """Police/CAD civilian lookup backed by PostgreSQL civilians table."""
    data = request.get_json(silent=True) or {}
    query = (data.get('query') or data.get('q') or '').strip()
    name = (data.get('name') or '').strip()
    dob = (data.get('dob') or '').strip()

    if not query and not name and not dob:
        return jsonify({'success': False, 'error': 'Query required'}), 400

    try:
        logger.info('Civilian lookup query: q="%s" name="%s" dob="%s"', query, name, dob)
        civilians = _civilian_search_query(query, name=name, dob=dob).order_by(Civilian.created_at.desc()).limit(50).all()
        result = [_civilian_response(c) for c in civilians]
        logger.info('Civilian lookup result count: %s', len(result))
        return jsonify({'success': True, 'results': result, 'civilians': result, 'total': len(result)})
    except Exception as e:
        logger.error(f'Civilian search error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/cad/search', methods=['POST'])
def cad_search():
    """Search civilians in PostgreSQL database for CAD."""
    try:
        data = request.get_json(silent=True) or {}
        query_type = data.get('type', 'all')
        query_value = (data.get('query') or data.get('q') or '').strip()

        if not query_value:
            return jsonify({'success': False, 'error': 'Query required'}), 400

        logger.info('Civilian lookup query: cad_type="%s" query="%s"', query_type, query_value)

        if query_type == 'name':
            civilians = _civilian_search_query('', name=query_value).all()
        elif query_type == 'dob':
            civilians = _civilian_search_query('', dob=query_value).all()
        elif query_type in ('plate', 'phone', 'civilian_id'):
            column = {
                'plate': Civilian.plate_number,
                'phone': Civilian.phone_number,
                'civilian_id': Civilian.civilian_id,
            }[query_type]
            civilians = scoped_query(Civilian).filter(column.ilike(f'%{query_value}%')).order_by(Civilian.created_at.desc()).limit(50).all()
        elif query_type == 'all':
            civilians = _civilian_search_query(query_value).order_by(Civilian.created_at.desc()).limit(50).all()
        else:
            return jsonify({'success': False, 'error': 'Invalid search type'}), 400

        results = [_civilian_response(c) for c in civilians]
        logger.info('Civilian lookup result count: %s', len(results))

        return jsonify({
            'success': True,
            'query_type': query_type,
            'query': query_value,
            'results': results,
            'civilians': results,
            'total': len(results),
        }), 200

    except Exception as e:
        logger.error(f'CAD search error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------------------------------------------------------------------------
# Advanced AI Character Engine
# ---------------------------------------------------------------------------

@app.route('/api/ai/character', methods=['POST'])
def ai_generate_character():
    """Generate AI character data (form population only, no auto-save)."""
    data = request.get_json(silent=True) or {}

    from ai_assist_service import generate_ai_civilian

    try:
        ai_result, source = generate_ai_civilian(data)

        if 'error' in ai_result:
            return jsonify({'success': False, 'error': ai_result['error']}), 500

        return jsonify({
            'success': True,
            'source': source,
            'data': ai_result,
        })
    except Exception as e:
        logger.error(f'Character generation failed: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/ai/narrative', methods=['POST'])
def ai_generate_narrative():
    """Generate AI narrative for reports."""
    data = request.get_json(silent=True) or {}

    narrative_type = data.get('type', 'arrest_narrative')
    context = data.get('context', '')

    if not context:
        return jsonify({'success': False, 'error': 'Context required'}), 400

    from ai_character_engine import generate_narrative
    from cad_helpers import log_ai_generation

    result = generate_narrative(narrative_type, context)

    if 'error' in result:
        log_ai_generation('narrative', data, 'Failed', status='Error', error_message=result['error'])
        return jsonify({'success': False, 'error': result['error']}), 500

    log_ai_generation('narrative', data, f'Generated {narrative_type}', status='Success')
    return jsonify({'success': True, 'narrative': result})


@app.route('/api/cad/civilian/<civilian_id>', methods=['GET'])
def get_cad_civilian(civilian_id):
    denied = require_police_cad_access()
    if denied:
        return denied
    """Get civilian details for CAD."""
    try:
        civilian = scoped_query(Civilian).filter_by(civilian_id=civilian_id).first()

        if not civilian:
            return jsonify({'success': False, 'error': 'Civilian not found'}), 404

        return jsonify({
            'success': True,
            'civilian': _civilian_response(civilian),
        }), 200

    except Exception as e:
        logger.error(f'Failed to get civilian: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/cad/civilians', methods=['GET'])
def get_all_cad_civilians():
    denied = require_police_cad_access()
    if denied:
        return denied
    """Get all civilians for CAD list."""
    try:
        civilians = scoped_query(Civilian).order_by(Civilian.created_at.desc()).all()

        results = [_civilian_response(c) for c in civilians]

        logger.info(f'CAD civilians list: total={len(results)}')

        return jsonify({
            'success': True,
            'civilians': results,
            'total': len(results),
        }), 200

    except Exception as e:
        logger.error(f'Failed to get civilians list: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/civilian/<civilian_id>', methods=['GET'])
def get_civilian(civilian_id):
    c = scoped_query(Civilian).filter_by(civilian_id=civilian_id).first()
    if not c:
        return jsonify({'success': False, 'error': 'Civilian not found'}), 404

    return jsonify({
        'success': True,
        'civilian': _civilian_response(c),
    })


# ---------------------------------------------------------------------------
# Dispatch CAD Routes
# ---------------------------------------------------------------------------

@app.route('/api/dispatch/calls', methods=['GET'])
def get_dispatch_calls():
    denied = require_police_cad_access()
    if denied:
        return denied
    """Get active dispatch calls."""
    from dispatch_service import get_active_calls

    calls = get_active_calls()
    return jsonify({'success': True, 'calls': calls, 'total': len(calls)})


@dispatch_required
@app.route('/api/dispatch/calls', methods=['POST'])
def create_dispatch_call_route():
    """Create a new dispatch call."""
    data = request.get_json(silent=True) or {}

    required = ['caller_name', 'location', 'call_type', 'description']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({'success': False, 'error': f'Missing fields: {", ".join(missing)}'}), 400

    from dispatch_service import create_dispatch_call as create_call
    from cad_helpers import log_audit

    try:
        call = create_call(
            data['caller_name'],
            data['location'],
            data['call_type'],
            data['description'],
            data.get('priority', 'Medium')
        )

        log_audit('dispatch', 'create_call', 'DispatchCall', call.call_id)
        emit_community_event('dispatch:call_created', {
            'call_id': call.call_id,
            'caller_name': call.caller_name,
            'location': call.location,
            'call_type': call.call_type,
            'description': call.description,
            'priority': call.priority,
            'status': call.status,
        })

        return jsonify({
            'success': True,
            'call_id': call.call_id,
            'message': 'Dispatch call created'
        })
    except Exception as e:
        logger.error(f'Failed to create dispatch call: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@dispatch_required
@app.route('/api/dispatch/calls/<call_id>', methods=['PUT'])
def update_dispatch_call(call_id):
    """Update dispatch call status or assignment."""
    data = request.get_json(silent=True) or {}

    from dispatch_service import assign_units_to_call, close_dispatch_call
    from cad_helpers import log_audit

    try:
        call = None

        if 'units' in data:
            call = assign_units_to_call(call_id, data['units'])
            log_audit('dispatch', 'assign_units', 'DispatchCall', call_id)
            emit_community_event('dispatch:units_assigned', {
                'call_id': call_id,
                'units': data['units'],
                'status': getattr(call, 'status', None),
            })

        if 'resolution' in data:
            call = close_dispatch_call(call_id, data['resolution'])
            log_audit('dispatch', 'close_call', 'DispatchCall', call_id)
            emit_community_event('dispatch:call_closed', {
                'call_id': call_id,
                'resolution': data['resolution'],
                'status': getattr(call, 'status', 'Closed'),
            })

        if not call:
            return jsonify({'success': False, 'error': 'Call not found'}), 404

        return jsonify({'success': True, 'message': 'Call updated'})
    except Exception as e:
        logger.error(f'Failed to update dispatch call: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/dispatch/officer-status', methods=['GET'])
def get_all_officer_status():
    """Get all officer statuses."""
    sessions = scoped_query(OfficerSession).all()

    result = [{
        'callsign': s.callsign,
        'officer_name': s.officer_name,
        'department': s.department,
        'status': s.status,
        'logged_in_at': s.logged_in_at.isoformat() if s.logged_in_at else None,
    } for s in sessions]

    return jsonify({'success': True, 'officers': result, 'total': len(result)})


@dispatch_required
@app.route('/api/dispatch/officer-status/<callsign>', methods=['PUT'])
def update_officer_status_route(callsign):
    """Update officer status."""
    data = request.get_json(silent=True) or {}
    new_status = data.get('status')

    if not new_status:
        return jsonify({'success': False, 'error': 'Status required'}), 400

    from dispatch_service import update_officer_status
    from cad_helpers import log_audit

    try:
        officer_session = update_officer_status(callsign, new_status)
        if not officer_session:
            return jsonify({'success': False, 'error': 'Officer not found'}), 404

        log_audit('dispatch', 'update_status', 'OfficerSession', callsign)
        emit_community_event('officer:status_changed', {
            'callsign': callsign,
            'status': new_status,
            'updated_at': datetime.utcnow().isoformat(),
        })

        return jsonify({'success': True, 'message': 'Status updated'})
    except Exception as e:
        logger.error(f'Failed to update officer status: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@dispatch_required
@app.route('/api/dispatch/panic', methods=['POST'])
def panic_button():
    """Officer panic button - creates urgent dispatch call."""
    data = request.get_json(silent=True) or {}

    callsign = data.get('callsign', 'Unknown')
    location = data.get('location', 'Unknown')

    from dispatch_service import create_dispatch_call as create_call
    from cad_helpers import log_audit

    try:
        call = create_call(
            f'Officer {callsign} - PANIC BUTTON',
            location,
            'Officer Needs Help',
            f'OFFICER PANIC BUTTON ACTIVATED - {callsign} at {location}',
            'Critical'
        )

        log_audit('dispatch', 'panic_button', 'DispatchCall', call.call_id)
        emit_community_event('dispatch:panic', {
            'call_id': call.call_id,
            'callsign': callsign,
            'location': location,
            'priority': 'Critical',
            'message': 'PANIC BUTTON ACTIVATED',
            'created_at': datetime.utcnow().isoformat(),
        })

        return jsonify({
            'success': True,
            'call_id': call.call_id,
            'message': 'PANIC BUTTON ACTIVATED - All units respond'
        })
    except Exception as e:
        logger.error(f'Panic button failed: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------------------------------------------------------------------------
# DMV/Records Routes
# ---------------------------------------------------------------------------

@app.route('/api/dmv/license/<license_id>', methods=['GET'])
def get_license(license_id):
    """Get license information."""
    from dmv_service import get_license_by_id

    license = get_license_by_id(license_id)
    if not license:
        return jsonify({'success': False, 'error': 'License not found'}), 404

    return jsonify({
        'success': True,
        'license': {
            'license_id': license.license_id,
            'owner_name': license.owner_name,
            'license_type': license.license_type,
            'status': license.status,
            'issued_date': license.issued_date,
            'expiry_date': license.expiry_date,
            'notes': license.notes,
        }
    })

@app.route('/api/dmv/license/civilian/<civilian_id>', methods=['GET'])
def check_civilian_license(civilian_id):
    """Check license status for a civilian."""
    from dmv_service import check_license_status

    result = check_license_status(civilian_id)
    return jsonify({'success': True, 'data': result})

@dmv_required
@app.route('/api/dmv/license/<license_id>/suspend', methods=['POST'])
def suspend_license_route(license_id):
    """Suspend a driver's license."""
    data = request.get_json(silent=True) or {}
    reason = data.get('reason', 'No reason provided')

    from dmv_service import suspend_license
    from cad_helpers import log_audit

    try:
        license = suspend_license(license_id, reason)
        if not license:
            return jsonify({'success': False, 'error': 'License not found'}), 404

        log_audit('dmv', 'suspend_license', 'License', license_id)
        return jsonify({'success': True, 'message': 'License suspended'})
    except Exception as e:
        logger.error(f'Failed to suspend license: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500

@dmv_required
@app.route('/api/dmv/license/<license_id>/revoke', methods=['POST'])
def revoke_license_route(license_id):
    """Revoke a driver's license."""
    data = request.get_json(silent=True) or {}
    reason = data.get('reason', 'No reason provided')

    from dmv_service import revoke_license
    from cad_helpers import log_audit

    try:
        license = revoke_license(license_id, reason)
        if not license:
            return jsonify({'success': False, 'error': 'License not found'}), 404

        log_audit('dmv', 'revoke_license', 'License', license_id)
        return jsonify({'success': True, 'message': 'License revoked'})
    except Exception as e:
        logger.error(f'Failed to revoke license: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/dmv/vehicle/plate/<plate>', methods=['GET'])
def lookup_plate(plate):
    """Look up vehicle by license plate."""
    from dmv_service import lookup_vehicle_by_plate

    vehicle = lookup_vehicle_by_plate(plate)
    if not vehicle:
        return jsonify({'success': False, 'error': 'Vehicle not found'}), 404

    return jsonify({'success': True, 'vehicle': vehicle})

@app.route('/api/dmv/vehicle/owner/<civilian_id>', methods=['GET'])
def lookup_owner_vehicles(civilian_id):
    """Look up all vehicles owned by a civilian."""
    from dmv_service import lookup_vehicles_by_owner

    vehicles = lookup_vehicles_by_owner(civilian_id)
    return jsonify({'success': True, 'vehicles': vehicles, 'total': len(vehicles)})

@dmv_required
@app.route('/api/dmv/vehicle/stolen/<plate>', methods=['POST'])
def flag_stolen(plate):
    """Flag a vehicle as stolen."""
    from dmv_service import flag_stolen_vehicle
    from cad_helpers import log_audit

    try:
        vehicle = flag_stolen_vehicle(plate)
        if not vehicle:
            return jsonify({'success': False, 'error': 'Vehicle not found'}), 404

        log_audit('dmv', 'flag_stolen', 'Vehicle', plate)
        return jsonify({'success': True, 'message': 'Vehicle flagged as stolen'})
    except Exception as e:
        logger.error(f'Failed to flag stolen vehicle: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500

@dmv_required
@app.route('/api/dmv/vehicle/recovered/<plate>', methods=['POST'])
def recover_vehicle(plate):
    """Mark a stolen vehicle as recovered."""
    from dmv_service import recover_stolen_vehicle
    from cad_helpers import log_audit

    try:
        vehicle = recover_stolen_vehicle(plate)
        if not vehicle:
            return jsonify({'success': False, 'error': 'Vehicle not found'}), 404

        log_audit('dmv', 'recover_vehicle', 'Vehicle', plate)
        return jsonify({'success': True, 'message': 'Vehicle marked as recovered'})
    except Exception as e:
        logger.error(f'Failed to recover vehicle: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500

@dmv_required
@app.route('/api/dmv/vehicle/impound/<plate>', methods=['POST'])
def impound_vehicle_route(plate):
    """Impound a vehicle."""
    data = request.get_json(silent=True) or {}
    reason = data.get('reason', 'No reason provided')

    from dmv_service import impound_vehicle
    from cad_helpers import log_audit

    try:
        vehicle = impound_vehicle(plate, reason)
        if not vehicle:
            return jsonify({'success': False, 'error': 'Vehicle not found'}), 404

        log_audit('dmv', 'impound_vehicle', 'Vehicle', plate)
        return jsonify({'success': True, 'message': 'Vehicle impounded'})
    except Exception as e:
        logger.error(f'Failed to impound vehicle: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500

@dmv_required
@app.route('/api/dmv/vehicle/release/<plate>', methods=['POST'])
def release_vehicle_route(plate):
    """Release an impounded vehicle."""
    from dmv_service import release_impounded_vehicle
    from cad_helpers import log_audit

    try:
        vehicle = release_impounded_vehicle(plate)
        if not vehicle:
            return jsonify({'success': False, 'error': 'Vehicle not found'}), 404

        log_audit('dmv', 'release_vehicle', 'Vehicle', plate)
        return jsonify({'success': True, 'message': 'Vehicle released from impound'})
    except Exception as e:
        logger.error(f'Failed to release vehicle: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------------------------------------------------------------------------
# DMV Vehicle CRUD Routes (Phase 1: Dedicated backend persistence)
# ---------------------------------------------------------------------------

@app.route('/api/dmv/vehicles', methods=['GET'])
def get_all_vehicles():
    """List all vehicles in DMV database."""
    try:
        vehicles = scoped_query(Vehicle).order_by(Vehicle.created_at.desc()).all()
        result = [vehicle_to_dict(v) for v in vehicles]
        return jsonify({'success': True, 'vehicles': result, 'total': len(result)})
    except Exception as e:
        logger.error(f'Failed to get vehicles: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@dmv_required
@app.route('/api/dmv/vehicles', methods=['POST'])
def create_vehicle():
    """Create a new vehicle registration in DMV."""
    data = request.get_json(silent=True) or {}
    
    # Field mapping: frontend camelCase -> database snake_case
    plate = (data.get('plateau Number') or data.get('plateNumber') or data.get('plate') or '').strip()
    if not plate:
        return jsonify({'success': False, 'error': 'plate number is required'}), 400
    
    # Check for duplicates
    existing = scoped_query(Vehicle).filter_by(plate=plate).first()
    if existing:
        return jsonify({'success': False, 'error': f'Vehicle with plate {plate} already exists'}), 409
    
    try:
        owner_civilian_id = data.get('ownerCivilianId') or data.get('owner_civilian_id') or ''
        vehicle = Vehicle(community_id=community_id, 
            vehicle_id=f"VEH-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3)}",
            owner_civilian_id=owner_civilian_id,
            plate=plate,
            vin=data.get('vin', ''),
            make=(data.get('vehicleMake') or data.get('make') or '').strip(),
            model=(data.get('vehicleModel') or data.get('model') or '').strip(),
            color=(data.get('vehicleColor') or data.get('color') or '').strip(),
            registration_status=(data.get('registrationStatus') or data.get('registration_status') or 'Valid').strip(),
            insurance_status=(data.get('insuranceStatus') or data.get('insurance_status') or 'Valid').strip(),
            notes=data.get('notes', ''),
            owner_name=data.get('ownerName') or data.get('owner_name') or '',
        )
        db.session.add(vehicle)
        db.session.commit()
        
        from cad_helpers import log_audit
        log_audit('dmv', 'create_vehicle', 'Vehicle', vehicle.vehicle_id)
        logger.info(f'Vehicle registered: {plate} owner={vehicle.owner_name}')
        return jsonify({
            'success': True,
            'vehicle_id': vehicle.vehicle_id,
            'vehicle': vehicle_to_dict(vehicle)
        }), 201
    except Exception as e:
        db.session.rollback()
        logger.error(f'Failed to create vehicle: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@dmv_required
@app.route('/api/dmv/vehicles/<plate>', methods=['PUT'])
def update_vehicle(plate):
    """Update an existing vehicle registration."""
    data = request.get_json(silent=True) or {}
    
    try:
        vehicle = scoped_query(Vehicle).filter_by(plate=plate).first()
        if not vehicle:
            return jsonify({'success': False, 'error': 'Vehicle not found'}), 404
        
        # Update mappable fields from frontend -> database
        if 'vehicleMake' in data or 'make' in data:
            vehicle.make = (data.get('vehicleMake') or data.get('make') or '').strip()
        if 'vehicleModel' in data or 'model' in data:
            vehicle.model = (data.get('vehicleModel') or data.get('model') or '').strip()
        if 'vehicleColor' in data or 'color' in data:
            vehicle.color = (data.get('vehicleColor') or data.get('color') or '').strip()
        if 'insuranceStatus' in data or 'insurance_status' in data:
            vehicle.insurance_status = (data.get('insuranceStatus') or data.get('insurance_status') or 'Valid').strip()
        if 'registrationStatus' in data or 'registration_status' in data:
            vehicle.registration_status = (data.get('registrationStatus') or data.get('registration_status') or 'Valid').strip()
        if 'ownerName' in data or 'owner_name' in data:
            vehicle.owner_name = (data.get('ownerName') or data.get('owner_name') or '').strip()
        if 'notes' in data:
            vehicle.notes = data.get('notes', '')
        if 'vin' in data:
            vehicle.vin = data.get('vin', '')
        
        vehicle.updated_at = datetime.utcnow()
        db.session.commit()
        
        logger.info(f'Vehicle updated: {plate}')
        return jsonify({'success': True, 'vehicle': vehicle_to_dict(vehicle)})
    except Exception as e:
        db.session.rollback()
        logger.error(f'Failed to update vehicle: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@dmv_required
@app.route('/api/dmv/vehicles/<plate>', methods=['DELETE'])
def delete_vehicle(plate):
    """Delete a vehicle registration (admin only)."""
    try:
        vehicle = scoped_query(Vehicle).filter_by(plate=plate).first()
        if not vehicle:
            return jsonify({'success': False, 'error': 'Vehicle not found'}), 404
        
        db.session.delete(vehicle)
        db.session.commit()
        
        logger.info(f'Vehicle deleted: {plate}')
        return jsonify({'success': True, 'message': 'Vehicle deleted'})
    except Exception as e:
        db.session.rollback()
        logger.error(f'Failed to delete vehicle: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------------------------------------------------------------------------
# DMV License CRUD Routes (Phase 1: Dedicated backend persistence)
# ---------------------------------------------------------------------------

@app.route('/api/dmv/licenses', methods=['GET'])
def get_all_licenses():
    """List all licenses in DMV database."""
    try:
        licenses = scoped_query(License).order_by(License.created_at.desc()).all()
        result = [license_to_dict(l) for l in licenses]
        return jsonify({'success': True, 'licenses': result, 'total': len(result)})
    except Exception as e:
        logger.error(f'Failed to get licenses: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@dmv_required
@app.route('/api/dmv/licenses', methods=['POST'])
def create_license():
    """Create a new driver license in DMV."""
    data = request.get_json(silent=True) or {}
    
    # Field mapping: frontend camelCase -> database snake_case
    owner_name = (data.get('licenseName') or data.get('ownerName') or data.get('owner_name') or '').strip()
    if not owner_name:
        return jsonify({'success': False, 'error': 'owner name is required'}), 400
    
    license_type = (data.get('licenseClass') or data.get('licenseType') or data.get('license_type') or '').strip()
    if not license_type:
        return jsonify({'success': False, 'error': 'license class/type is required'}), 400
    
    try:
        license_id = f"LIC-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3)}"
        license_obj = License(community_id=community_id, 
            license_id=license_id,
            owner_name=owner_name,
            license_type=license_type,
            status=(data.get('status') or 'Valid').strip(),
            issued_date=data.get('licenseIssuedDate') or data.get('issued_date') or '',
            expiry_date=data.get('licenseExpiration') or data.get('expiryDate') or data.get('expiry_date') or '',
            notes=data.get('notes', '') or data.get('restrictions', ''),
        )
        db.session.add(license_obj)
        db.session.commit()
        
        from cad_helpers import log_audit
        log_audit('dmv', 'create_license', 'License', license_id)
        logger.info(f'License issued: {license_id} to {owner_name} class={license_type}')
        return jsonify({
            'success': True,
            'license_id': license_id,
            'license': license_to_dict(license_obj)
        }), 201
    except Exception as e:
        db.session.rollback()
        logger.error(f'Failed to create license: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@dmv_required
@app.route('/api/dmv/licenses/<license_id>', methods=['PUT'])
def update_license_route(license_id):
    """Update an existing driver license."""
    data = request.get_json(silent=True) or {}
    
    try:
        license_obj = scoped_query(License).filter_by(license_id=license_id).first()
        if not license_obj:
            return jsonify({'success': False, 'error': 'License not found'}), 404
        
        # Update mappable fields
        if 'ownerName' in data or 'licenseName' in data or 'owner_name' in data:
            val = data.get('ownerName') or data.get('licenseName') or data.get('owner_name')
            if val:
                license_obj.owner_name = val.strip()
        if 'licenseClass' in data or 'licenseType' in data or 'license_type' in data:
            val = data.get('licenseClass') or data.get('licenseType') or data.get('license_type')
            if val:
                license_obj.license_type = val.strip()
        if 'status' in data:
            license_obj.status = data.get('status', 'Valid').strip()
        if 'licenseExpiration' in data or 'expiryDate' in data or 'expiry_date' in data:
            license_obj.expiry_date = data.get('licenseExpiration') or data.get('expiryDate') or data.get('expiry_date') or ''
        if 'notes' in data:
            license_obj.notes = data.get('notes', '')
        if 'restrictions' in data:
            license_obj.notes = data.get('restrictions', '')
        
        license_obj.updated_at = datetime.utcnow()
        db.session.commit()
        
        logger.info(f'License updated: {license_id}')
        return jsonify({'success': True, 'license': license_to_dict(license_obj)})
    except Exception as e:
        db.session.rollback()
        logger.error(f'Failed to update license: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@dmv_required
@app.route('/api/dmv/licenses/<license_id>', methods=['DELETE'])
def delete_license_route(license_id):
    """Delete a driver license (admin only)."""
    try:
        license_obj = scoped_query(License).filter_by(license_id=license_id).first()
        if not license_obj:
            return jsonify({'success': False, 'error': 'License not found'}), 404
        
        db.session.delete(license_obj)
        db.session.commit()
        
        logger.info(f'License deleted: {license_id}')
        return jsonify({'success': True, 'message': 'License deleted'})
    except Exception as e:
        db.session.rollback()
        logger.error(f'Failed to delete license: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------------------------------------------------------------------------
# Business CRUD Routes (Phase 1: Complete business persistence)
# ---------------------------------------------------------------------------

def business_to_dict(b):
    """Convert Business model to JSON response dict."""
    return {
        'business_id': b.business_id,
        'owner_civilian_id': b.owner_civilian_id or '',
        'business_name': b.business_name or '',
        'business_type': b.business_type or '',
        'license_status': b.license_status or 'Active',
        'address': b.address or '',
        'employees': b.employees or 0,
        'inspection_notes': b.inspection_notes or '',
        'legal_flags': b.legal_flags or '',
        'created_at': b.created_at.isoformat() if b.created_at else None,
        'updated_at': b.updated_at.isoformat() if b.updated_at else None,
    }


@app.route('/api/businesses', methods=['GET'])
def get_all_businesses():
    """List all businesses in the system."""
    try:
        businesses = scoped_query(Business).order_by(Business.created_at.desc()).all()
        result = [business_to_dict(b) for b in businesses]
        return jsonify({'success': True, 'businesses': result, 'total': len(result)})
    except Exception as e:
        logger.error(f'Failed to get businesses: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/businesses', methods=['POST'])
def create_business():
    """Create a new business registration."""
    data = request.get_json(silent=True) or {}
    
    business_name = (data.get('businessName') or data.get('business_name') or '').strip()
    if not business_name:
        return jsonify({'success': False, 'error': 'business_name is required'}), 400
    
    try:
        business_id = f"BIZ-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3)}"
        business = Business(
            business_id=business_id,
            community_id=get_current_community_id(),
            owner_civilian_id=data.get('ownerCivilianId') or data.get('owner_civilian_id') or '',
            business_name=business_name,
            business_type=(data.get('businessType') or data.get('business_type') or '').strip(),
            license_status=(data.get('licenseStatus') or data.get('license_status') or 'Active').strip(),
            address=data.get('address') or data.get('desiredLocation') or '',
            employees=int(data.get('employees', 0)) if data.get('employees') else 0,
            inspection_notes=data.get('inspectionNotes') or data.get('inspection_notes') or '',
            legal_flags=data.get('legalFlags') or data.get('legal_flags') or data.get('illegalDisclosure') or '',
        )
        db.session.add(business)
        db.session.commit()
        
        logger.info(f'Business registered: {business_id} name={business_name} type={business.business_type}')
        
        # Log audit trail
        try:
            from cad_helpers import log_audit
            log_audit('business', 'create', 'Business', business_id)
        except:
            pass
        
        return jsonify({
            'success': True,
            'business_id': business_id,
            'business': business_to_dict(business)
        }), 201
    except Exception as e:
        db.session.rollback()
        logger.error(f'Failed to create business: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/businesses/<business_id>', methods=['GET'])
def get_business(business_id):
    """Get a specific business by ID."""
    try:
        business = scoped_query(Business).filter_by(business_id=business_id).first()
        if not business:
            return jsonify({'success': False, 'error': 'Business not found'}), 404
        
        return jsonify({'success': True, 'business': business_to_dict(business)})
    except Exception as e:
        logger.error(f'Failed to get business: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/businesses/<business_id>', methods=['PUT'])
def update_business(business_id):
    """Update an existing business."""
    data = request.get_json(silent=True) or {}
    
    try:
        business = scoped_query(Business).filter_by(business_id=business_id).first()
        if not business:
            return jsonify({'success': False, 'error': 'Business not found'}), 404
        
        # Update fields if provided
        if 'businessName' in data or 'business_name' in data:
            val = data.get('businessName') or data.get('business_name')
            if val:
                business.business_name = val.strip()
        if 'businessType' in data or 'business_type' in data:
            val = data.get('businessType') or data.get('business_type')
            if val:
                business.business_type = val.strip()
        if 'licenseStatus' in data or 'license_status' in data:
            val = data.get('licenseStatus') or data.get('license_status')
            if val:
                business.license_status = val.strip()
        if 'address' in data or 'desiredLocation' in data:
            business.address = (data.get('address') or data.get('desiredLocation') or '').strip()
        if 'employees' in data:
            try:
                business.employees = int(data.get('employees', 0))
            except:
                pass
        if 'inspectionNotes' in data or 'inspection_notes' in data:
            business.inspection_notes = (data.get('inspectionNotes') or data.get('inspection_notes') or '').strip()
        if 'legalFlags' in data or 'legal_flags' in data or 'illegalDisclosure' in data:
            val = data.get('legalFlags') or data.get('legal_flags') or data.get('illegalDisclosure')
            if val:
                business.legal_flags = val.strip()
        if 'ownerCivilianId' in data or 'owner_civilian_id' in data:
            val = data.get('ownerCivilianId') or data.get('owner_civilian_id')
            if val:
                business.owner_civilian_id = val.strip()
        
        business.updated_at = datetime.utcnow()
        db.session.commit()
        
        logger.info(f'Business updated: {business_id}')
        return jsonify({'success': True, 'business': business_to_dict(business)})
    except Exception as e:
        db.session.rollback()
        logger.error(f'Failed to update business: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/businesses/<business_id>', methods=['DELETE'])
def delete_business(business_id):
    """Delete a business (admin only)."""
    try:
        business = scoped_query(Business).filter_by(business_id=business_id).first()
        if not business:
            return jsonify({'success': False, 'error': 'Business not found'}), 404
        
        db.session.delete(business)
        db.session.commit()
        
        logger.info(f'Business deleted: {business_id}')
        return jsonify({'success': True, 'message': 'Business deleted'})
    except Exception as e:
        db.session.rollback()
        logger.error(f'Failed to delete business: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/applications', methods=['GET'])
@admin_required
def list_applications_admin():
    """List applications (admin endpoint)."""
    return list_applications()

# ---------------------------------------------------------------------------
# World Realism Routes
# ---------------------------------------------------------------------------

@app.route('/api/world/address', methods=['GET'])
def generate_address_route():
    """Generate a random address."""
    from world_realism_service import generate_address

    neighborhood = request.args.get('neighborhood')
    address = generate_address(neighborhood)

    return jsonify({'success': True, 'address': address})

@app.route('/api/world/plate', methods=['GET'])
def generate_plate_route():
    """Generate a random license plate."""
    from world_realism_service import generate_plate

    plate = generate_plate()
    return jsonify({'success': True, 'plate': plate})

@app.route('/api/world/vehicle', methods=['GET'])
def generate_vehicle_route():
    """Generate a random vehicle."""
    from world_realism_service import generate_vehicle

    vehicle = generate_vehicle()
    return jsonify({'success': True, 'vehicle': vehicle})

@app.route('/api/world/business', methods=['GET'])
def generate_business_route():
    """Generate a random business."""
    from world_realism_service import generate_business

    neighborhood = request.args.get('neighborhood')
    business = generate_business(neighborhood)

    return jsonify({'success': True, 'business': business})

@app.route('/api/world/name', methods=['GET'])
def generate_name_route():
    """Generate a random name."""
    from world_realism_service import generate_name

    gender = request.args.get('gender', 'random')
    name = generate_name(gender)

    return jsonify({'success': True, 'name': name})

@app.route('/api/world/rp-history', methods=['GET'])
def generate_rp_history_route():
    """Generate a random RP history."""
    from world_realism_service import generate_rp_history

    history = generate_rp_history()
    return jsonify({'success': True, 'history': history})

@app.route('/api/world/call', methods=['GET'])
def generate_call_route():
    """Generate a random dispatch call."""
    from world_realism_service import generate_dispatch_call

    call = generate_dispatch_call()
    return jsonify({'success': True, 'call': call})

@app.route('/api/world/neighborhoods', methods=['GET'])
def get_neighborhoods():
    """Get list of all neighborhoods."""
    from world_realism_service import NEIGHBORHOODS

    return jsonify({'success': True, 'neighborhoods': NEIGHBORHOODS})


# ---------------------------------------------------------------------------
# Relationship Routes
# ---------------------------------------------------------------------------

@app.route('/api/relationships/link-vehicle', methods=['POST'])
@admin_required
def link_vehicle_route():
    """Link civilian to vehicle."""
    data = request.get_json(silent=True) or {}
    civilian_id = data.get('civilian_id')
    vehicle_id = data.get('vehicle_id')

    if not civilian_id or not vehicle_id:
        return jsonify({'success': False, 'error': 'Missing required fields'}), 400

    from relationships_service import link_civilian_to_vehicle
    from cad_helpers import log_audit

    try:
        vehicle = link_civilian_to_vehicle(civilian_id, vehicle_id)
        if not vehicle:
            return jsonify({'success': False, 'error': 'Vehicle not found'}), 404

        log_audit('relationships', 'link_vehicle', 'Vehicle', vehicle_id)
        return jsonify({'success': True, 'message': 'Vehicle linked to civilian'})
    except Exception as e:
        logger.error(f'Failed to link vehicle: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/relationships/gang-crew/<gang_name>', methods=['GET'])
def get_gang_crew_route(gang_name):
    """Get gang crew with relationships."""
    from relationships_service import get_gang_crew

    crew = get_gang_crew(gang_name)
    return jsonify({'success': True, 'crew': crew, 'total': len(crew)})


@app.route('/api/relationships/criminal-history/<civilian_id>', methods=['GET'])
def get_criminal_history_route(civilian_id):
    """Get complete criminal history."""
    from relationships_service import get_civilian_criminal_history

    history = get_civilian_criminal_history(civilian_id)
    if not history:
        return jsonify({'success': False, 'error': 'Civilian not found'}), 404

    return jsonify({'success': True, 'history': history})


@app.route('/api/relationships/create-arrest', methods=['POST'])
@admin_required
def create_arrest_route():
    """Create arrest and update criminal history."""
    data = request.get_json(silent=True) or {}

    required = ['civilian_id', 'charges', 'arresting_officer', 'location', 'narrative']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({'success': False, 'error': f'Missing fields: {", ".join(missing)}'}), 400

    from relationships_service import create_arrest_record, create_warrant_from_arrest
    from cad_helpers import log_audit

    try:
        arrest = create_arrest_record(
            data['civilian_id'],
            data['charges'],
            data['arresting_officer'],
            data['location'],
            data['narrative']
        )
        _ensure_arrest_custody_and_hearing(arrest)
        db.session.commit()

        # Auto-create warrant if requested
        if data.get('create_warrant'):
            warrant = create_warrant_from_arrest(
                arrest.arrest_id,
                data['civilian_id'],
                data['charges'],
                data.get('probable_cause', 'Arrest warrant')
            )
            log_audit('relationships', 'create_warrant', 'Warrant', warrant.warrant_id)

        log_audit('relationships', 'create_arrest', 'Arrest', arrest.arrest_id)
        return jsonify({'success': True, 'arrest_id': arrest.arrest_id})
    except Exception as e:
        logger.error(f'Failed to create arrest: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/relationships/warrant-check/<plate>', methods=['GET'])
def warrant_check_route(plate):
    """Check for warrants on traffic stop."""
    from relationships_service import check_warrant_on_traffic_stop

    result = check_warrant_on_traffic_stop(plate)
    if not result:
        return jsonify({'success': True, 'warrants': None})

    return jsonify({'success': True, 'warrants': result})


@app.route('/api/relationships/family', methods=['POST'])
@admin_required
def create_family_route():
    """Create family relationship."""
    data = request.get_json(silent=True) or {}

    from relationships_service import create_family_relationship
    from cad_helpers import log_audit

    try:
        assoc = create_family_relationship(
            data['civilian_id1'],
            data['civilian_id2'],
            data.get('relationship', 'Family')
        )

        log_audit('relationships', 'create_family', 'KnownAssociate', assoc.associate_id)
        return jsonify({'success': True, 'message': 'Family relationship created'})
    except Exception as e:
        logger.error(f'Failed to create family: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/relationships/employment', methods=['POST'])
@admin_required
def create_employment_route():
    """Link civilian to business as employee."""
    data = request.get_json(silent=True) or {}

    from relationships_service import create_employment_relationship
    from cad_helpers import log_audit

    try:
        assoc = create_employment_relationship(
            data['civilian_id'],
            data['business_id']
        )

        log_audit('relationships', 'create_employment', 'KnownAssociate', assoc.associate_id)
        return jsonify({'success': True, 'message': 'Employment relationship created'})
    except Exception as e:
        logger.error(f'Failed to create employment: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------------------------------------------------------------------------
# Evidence Routes
# ---------------------------------------------------------------------------

@police_required
@app.route('/api/evidence/create', methods=['POST'])
def create_evidence_route():
    """Create evidence record."""
    data = request.get_json(silent=True) or {}

    required = ['case_id', 'arrest_id', 'evidence_type', 'description', 'collected_by', 'location_found']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({'success': False, 'error': f'Missing fields: {", ".join(missing)}'}), 400

    from evidence_service import create_evidence
    from cad_helpers import log_audit

    try:
        evidence = create_evidence(
            data['case_id'],
            data['arrest_id'],
            data['evidence_type'],
            data['description'],
            data['collected_by'],
            data['location_found']
        )

        log_audit('evidence', 'create_evidence', 'Evidence', evidence.evidence_id)
        return jsonify({'success': True, 'evidence_id': evidence.evidence_id})
    except Exception as e:
        logger.error(f'Failed to create evidence: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/evidence/<evidence_id>/chain-of-custody', methods=['GET'])
def get_evidence_custody_route(evidence_id):
    """Get chain of custody for evidence."""
    from evidence_service import get_evidence_chain_of_custody

    custody = get_evidence_chain_of_custody(evidence_id)
    if not custody:
        return jsonify({'success': False, 'error': 'Evidence not found'}), 404

    return jsonify({'success': True, 'custody': custody})


@police_required
@app.route('/api/evidence/<evidence_id>/transfer', methods=['POST'])
def transfer_evidence_route(evidence_id):
    """Transfer evidence custody."""
    data = request.get_json(silent=True) or {}

    from evidence_service import transfer_evidence_custody
    from cad_helpers import log_audit

    try:
        evidence = transfer_evidence_custody(
            evidence_id,
            data.get('from_officer', 'Unknown'),
            data.get('to_officer', 'Unknown'),
            data.get('reason', 'Transfer')
        )

        if not evidence:
            return jsonify({'success': False, 'error': 'Evidence not found'}), 404

        log_audit('evidence', 'transfer_evidence', 'Evidence', evidence_id)
        return jsonify({'success': True, 'message': 'Evidence transferred'})
    except Exception as e:
        logger.error(f'Failed to transfer evidence: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@police_required
@app.route('/api/evidence/<evidence_id>/release', methods=['POST'])
def release_evidence_route(evidence_id):
    """Release evidence from storage."""
    data = request.get_json(silent=True) or {}

    from evidence_service import release_evidence
    from cad_helpers import log_audit

    try:
        evidence = release_evidence(evidence_id, data.get('reason', 'Case closed'))
        if not evidence:
            return jsonify({'success': False, 'error': 'Evidence not found'}), 404

        log_audit('evidence', 'release_evidence', 'Evidence', evidence_id)
        return jsonify({'success': True, 'message': 'Evidence released'})
    except Exception as e:
        logger.error(f'Failed to release evidence: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------------------------------------------------------------------------
# Court Routes
# ---------------------------------------------------------------------------

@app.route('/api/court/case/create', methods=['POST'])
@admin_required
def create_case_route():
    """Create case from arrest."""
    data = request.get_json(silent=True) or {}

    from court_service import create_case_from_arrest
    from cad_helpers import log_audit

    try:
        case = create_case_from_arrest(
            data.get('arrest_id'),
            data.get('civilian_id'),
            data.get('charges')
        )

        log_audit('court', 'create_case', 'CaseFile', case.case_id)
        return jsonify({'success': True, 'case_id': case.case_id})
    except Exception as e:
        logger.error(f'Failed to create case: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/court/case/<case_id>', methods=['GET'])
def get_case_route(case_id):
    """Get case summary."""
    from court_service import get_case_summary

    summary = get_case_summary(case_id)
    if not summary:
        return jsonify({'success': False, 'error': 'Case not found'}), 404

    return jsonify({'success': True, 'case': summary})


@app.route('/api/court/case/<case_id>/assign-judge', methods=['POST'])
@admin_required
def assign_judge_route(case_id):
    """Assign judge to case."""
    data = request.get_json(silent=True) or {}

    from court_service import assign_judge
    from cad_helpers import log_audit

    try:
        case = assign_judge(case_id, data.get('judge_name', 'Judge TBD'))
        if not case:
            return jsonify({'success': False, 'error': 'Case not found'}), 404

        log_audit('court', 'assign_judge', 'CaseFile', case_id)
        return jsonify({'success': True, 'message': 'Judge assigned'})
    except Exception as e:
        logger.error(f'Failed to assign judge: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/court/case/<case_id>/prosecutor-notes', methods=['POST'])
@admin_required
def prosecutor_notes_route(case_id):
    """Add prosecutor notes."""
    data = request.get_json(silent=True) or {}

    from court_service import add_prosecutor_notes
    from cad_helpers import log_audit

    try:
        case = add_prosecutor_notes(case_id, data.get('notes', ''))
        if not case:
            return jsonify({'success': False, 'error': 'Case not found'}), 404

        log_audit('court', 'prosecutor_notes', 'CaseFile', case_id)
        return jsonify({'success': True, 'message': 'Notes added'})
    except Exception as e:
        logger.error(f'Failed to add notes: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/court/case/<case_id>/close', methods=['POST'])
@admin_required
def close_case_route(case_id):
    """Close case with verdict and sentencing."""
    data = request.get_json(silent=True) or {}

    from court_service import close_case
    from cad_helpers import log_audit

    try:
        case = close_case(
            case_id,
            data.get('outcome', 'Guilty'),
            data.get('sentence_type', 'Probation'),
            data.get('sentence_length', '1 year'),
            data.get('notes', '')
        )

        if not case:
            return jsonify({'success': False, 'error': 'Case not found'}), 404

        log_audit('court', 'close_case', 'CaseFile', case_id)
        return jsonify({'success': True, 'message': 'Case closed'})
    except Exception as e:
        logger.error(f'Failed to close case: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/court/cases/search', methods=['POST'])
def search_cases_route():
    """Search cases."""
    data = request.get_json(silent=True) or {}
    query = data.get('query', '').strip()

    if not query or len(query) < 2:
        return jsonify({'success': False, 'error': 'Query must be at least 2 characters'}), 400

    from court_service import search_cases

    cases = search_cases(query)
    return jsonify({'success': True, 'cases': cases, 'total': len(cases)})


# ---------------------------------------------------------------------------
# Immersion Features Routes
# ---------------------------------------------------------------------------

@app.route('/api/immersion/alerts', methods=['GET'])
def get_alerts_route():
    """Get active MDT alerts."""
    from immersion_service import get_active_alerts

    officer_id = request.args.get('officer_id')
    limit = request.args.get('limit', 20, type=int)

    alerts = get_active_alerts(officer_id, limit)
    return jsonify({'success': True, 'alerts': alerts, 'total': len(alerts)})


@app.route('/api/immersion/warrant-hit/<plate>', methods=['GET'])
def warrant_hit_alert_route(plate):
    """Check for warrant hit on plate."""
    from immersion_service import generate_warrant_hit_alert

    alert = generate_warrant_hit_alert(plate)
    if not alert:
        return jsonify({'success': True, 'alert': None})

    return jsonify({'success': True, 'alert': alert})


@app.route('/api/immersion/stolen-vehicle/<plate>', methods=['GET'])
def stolen_vehicle_alert_route(plate):
    """Check for stolen vehicle alert."""
    from immersion_service import generate_stolen_vehicle_alert

    alert = generate_stolen_vehicle_alert(plate)
    if not alert:
        return jsonify({'success': True, 'alert': None})

    return jsonify({'success': True, 'alert': alert})


@app.route('/api/immersion/bolo-match/<civilian_id>', methods=['GET'])
def bolo_match_alert_route(civilian_id):
    """Check for BOLO match."""
    from immersion_service import generate_bolo_match_alert

    alert = generate_bolo_match_alert(civilian_id)
    if not alert:
        return jsonify({'success': True, 'alert': None})

    return jsonify({'success': True, 'alert': alert})


@app.route('/api/immersion/safety-warning/<civilian_id>', methods=['GET'])
def safety_warning_route(civilian_id):
    """Get officer safety warning."""
    data = request.get_json(silent=True) or {}
    officer_id = data.get('officer_id', 'dispatch')

    from immersion_service import generate_safety_warning_alert

    alert = generate_safety_warning_alert(civilian_id, officer_id)
    if not alert:
        return jsonify({'success': True, 'alert': None})

    return jsonify({'success': True, 'alert': alert})


@app.route('/api/immersion/dispatch-audio/<call_id>', methods=['GET'])
def dispatch_audio_route(call_id):
    """Get dispatch audio log for call."""
    from immersion_service import generate_dispatch_audio_log

    log = generate_dispatch_audio_log(call_id)
    if not log:
        return jsonify({'success': False, 'error': 'Call not found'}), 404

    return jsonify({'success': True, 'audio_log': log})


@app.route('/api/immersion/audio-logs', methods=['GET'])
def audio_logs_route():
    """Get recent dispatch audio logs."""
    from immersion_service import get_dispatch_audio_logs

    limit = request.args.get('limit', 20, type=int)
    logs = get_dispatch_audio_logs(limit)

    return jsonify({'success': True, 'logs': logs, 'total': len(logs)})


@app.route('/api/immersion/incident-timeline/<call_id>', methods=['GET'])
def incident_timeline_route(call_id):
    """Get incident timeline."""
    from immersion_service import get_incident_timeline

    timeline = get_incident_timeline(call_id)
    if not timeline:
        return jsonify({'success': False, 'error': 'Call not found'}), 404

    return jsonify({'success': True, 'timeline': timeline})


@app.route('/api/immersion/mdt-dashboard', methods=['GET'])
def mdt_dashboard_route():
    """Get complete MDT dashboard data."""
    from immersion_service import get_active_alerts, get_dispatch_audio_logs

    officer_id = request.args.get('officer_id')

    alerts = get_active_alerts(officer_id, 10)
    audio_logs = get_dispatch_audio_logs(5)

    # Get active calls
    active_calls = DispatchCall.query.filter(
        DispatchCall.status.in_(['New', 'Assigned', 'En Route', 'On Scene'])
    ).order_by(DispatchCall.created_at.desc()).limit(10).all()

    calls_data = [{
        'call_id': c.call_id,
        'location': c.location,
        'priority': c.priority,
        'status': c.status,
        'description': (c.description or '')[:100],
    } for c in active_calls]

    return jsonify({
        'success': True,
        'dashboard': {
            'alerts': alerts,
            'audio_logs': audio_logs,
            'active_calls': calls_data,
            'timestamp': datetime.utcnow().isoformat(),
        }
    })



def frontend_page(filename):
    """Serve a browser page from the app root."""
    return send_from_directory('.', filename)


@app.route('/')
def home():
    return frontend_page('index.html')


@app.route('/login')
def login_page():
    return frontend_page('login.html')


@app.route('/register')
def register_page():
    return frontend_page('register.html')


@app.route('/communities')
def communities_page():
    return frontend_page('communities.html')


@app.route('/create-community')
def create_community_page():
    return frontend_page('create-community.html')


@app.route('/join-community')
def join_community_page():
    return frontend_page('join-community.html')


@app.route('/c/<community_slug>/')
def community_home(community_slug):
    # Tenant entry point should always land in full CAD/MDT shell.
    return frontend_page('police.html')


@app.route('/c/<community_slug>/<page>')
def community_page(community_slug, page):
    allowed_pages = {
        'index.html',
        'rules.html',
        'police.html',
        'dmv.html',
        'donations.html',
        'businesses.html',
        'applications.html',
        'complaints.html',
        'civilian.html',
        'cad.html',
        'join.html',
    }
    extensionless_aliases = {
        'index': 'index.html',
        'rules': 'rules.html',
        'police': 'police.html',
        'dmv': 'dmv.html',
        'donations': 'donations.html',
        'businesses': 'businesses.html',
        'applications': 'applications.html',
        'complaints': 'complaints.html',
        'civilian': 'civilian.html',
        'cad': 'police.html',
        'join': 'join.html',
    }
    page = extensionless_aliases.get(page, page)
    if page in allowed_pages:
        return frontend_page(page)
    abort(404)




@app.route('/admin')
def platform_admin_page():
    if not session.get('user_id'):
        return redirect('/login', code=302)
    if not is_platform_owner():
        return frontend_page('admin-forbidden.html'), 403
    return frontend_page('admin.html')


@app.route('/community-admin')
@require_auth
def community_admin_page():
    community_id = get_current_community_id()
    membership = CommunityMember.query.filter_by(user_id=session.get('user_id'), community_id=community_id, status='Active').first()
    normalized_role = normalize_community_role(membership.role) if membership else None
    if normalized_role not in ('Owner', 'Admin', 'CommunityOwner', 'CommunityAdmin'):
        return frontend_page('community-admin-forbidden.html'), 403
    return frontend_page('community-admin.html')


@app.route('/<path:path>')
def serve_static(path):
    route_aliases = {
        '': 'index.html',
        'login': 'login.html',
        'register': 'register.html',
        'communities': 'communities.html',
        'create-community': 'create-community.html',
        'join-community': 'join-community.html',
    }
    if path in route_aliases:
        return frontend_page(route_aliases[path])

    legacy_tenant_pages = {
        'rules.html': 'rules.html',
        'civilian.html': 'civilian.html',
        'police.html': 'police.html',
        'cad.html': 'cad.html',
        'dmv.html': 'dmv.html',
        'businesses.html': 'businesses.html',
        'applications.html': 'applications.html',
        'donations.html': 'donations.html',
        'complaints.html': 'complaints.html',
        'join.html': 'join.html',
    }
    if path in legacy_tenant_pages:
        target = f'/c/{DEFAULT_COMMUNITY_SLUG}/{legacy_tenant_pages[path]}'
        return redirect(target, code=302)

    parts = path.strip('/').split('/') if path else []
    if len(parts) >= 3 and parts[0] == 'c' and parts[2] in {'assets', 'static'}:
        asset_path = '/'.join(parts[2:])
        if os.path.exists(os.path.join('.', asset_path)):
            return frontend_page(asset_path)

    if path.startswith('api/'):
        return jsonify({
            'success': False,
            'error': 'Endpoint not found',
            'code': 'NOT_FOUND'
        }), 404

    if os.path.exists(os.path.join('.', path)):
        return frontend_page(path)
    return frontend_page('index.html')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)


def configured_platform_owner_matches_user(user):
    owner_email = (os.getenv('PLATFORM_OWNER_EMAIL') or '').strip().lower()
    owner_username = (os.getenv('PLATFORM_OWNER_USERNAME') or '').strip().lower()
    if not user:
        return False
    email = (getattr(user, 'email', None) or '').strip().lower()
    username = (getattr(user, 'username', None) or '').strip().lower()
    return (owner_email and email == owner_email) or (owner_username and username == owner_username)


def ensure_platform_owner(user):
    if not user:
        return False

    normalized_role = (user.role or '').strip()
    platform_role = (getattr(user, 'platform_role', None) or '').strip()
    should_promote = False

    if normalized_role == 'PlatformOwner' or platform_role == 'PlatformOwner':
        should_promote = True
    elif configured_platform_owner_matches_user(user):
        should_promote = True
    else:
        owner_exists = User.query.filter_by(role='PlatformOwner').first() is not None
        if not owner_exists:
            should_promote = True

    if should_promote and user.role != 'PlatformOwner':
        user.role = 'PlatformOwner'
        if hasattr(User, 'platform_role'):
            user.platform_role = 'PlatformOwner'
        db.session.commit()
        logger.info("PlatformOwner bootstrap promoted user_id=%s email=%s", user.id, getattr(user, 'email', None))
    elif should_promote and hasattr(User, 'platform_role') and getattr(user, 'platform_role', None) != 'PlatformOwner':
        user.platform_role = 'PlatformOwner'
        db.session.commit()
        logger.info("PlatformOwner bootstrap normalized platform_role for user_id=%s", user.id)

    if should_promote and not bool(_user_field(user, 'active', True)):
        user.active = True
        db.session.commit()
    return _session_hydrate_user(user)


def normalize_community_role(role):
    mapping = {
        'communityowner': 'CommunityOwner',
        'owner': 'Owner',
        'communityadmin': 'CommunityAdmin',
        'admin': 'Admin',
    }
    key = (role or '').strip().lower()
    return mapping.get(key, role)


def has_community_owner_access(user_id, community=None, membership=None):
    """Normalize owner/admin access checks with owner_user_id fallback."""
    if not user_id:
        return False
    normalized_role = normalize_community_role(getattr(membership, 'role', None)) if membership else None
    if normalized_role in ('Owner', 'Admin', 'CommunityOwner', 'CommunityAdmin'):
        return True
    if community and getattr(community, 'owner_user_id', None) == user_id:
        return True
    return False


def is_platform_owner():
    user_id = session.get('user_id')
    user = User.query.get(user_id) if isinstance(user_id, int) else None
    if user and ensure_platform_owner(user):
        return True

    session_role = (session.get('role') or '').strip()
    session_platform_role = (session.get('platform_role') or '').strip()
    if session_role == 'PlatformOwner' or session_platform_role == 'PlatformOwner':
        return True

    if user and configured_platform_owner_matches_user(user):
        return True

    session_email = (session.get('email') or '').strip().lower()
    session_username = (session.get('username') or '').strip().lower()
    owner_email = (os.getenv('PLATFORM_OWNER_EMAIL') or '').strip().lower()
    owner_username = (os.getenv('PLATFORM_OWNER_USERNAME') or '').strip().lower()
    return (owner_email and session_email == owner_email) or (owner_username and session_username == owner_username)


def log_platform_admin(action, target_user_id=None, tenant=None, details=None):
    db.session.add(PlatformAdminLog(
        actor_user_id=session.get('user_id') if isinstance(session.get('user_id'), int) else None,
        target_user_id=target_user_id,
        tenant=tenant,
        action=action,
        details=json.dumps(details or {}),
        ip_address=request.remote_addr,
    ))


def invalidate_user_sessions(user_id):
    UserSession.query.filter_by(user_id=user_id, active=True).update({'active': False, 'invalidated_at': datetime.utcnow()})


@app.route('/api/auth/forgot-password', methods=['POST'])
@limiter.limit("5 per minute")
def forgot_password():
    data = request.get_json(silent=True) or {}
    identifier = (data.get('identifier') or '').strip()
    user = User.query.filter((User.username == identifier) | (User.email == identifier)).first()
    if not user:
        return jsonify({'success': True, 'message': 'If the account exists, a reset token was generated.'})
    token = secrets.token_urlsafe(32)
    db.session.add(PasswordResetToken(user_id=user.id, token=token, tenant=session.get('selected_community_id'), expires_at=datetime.utcnow() + timedelta(hours=1)))
    db.session.commit()
    return jsonify({'success': True, 'reset_token': token, 'message': 'Use this token to reset password.'})


@app.route('/api/auth/reset-password', methods=['POST'])
@limiter.limit("5 per minute")
def reset_password_with_token():
    data = request.get_json(silent=True) or {}
    token = data.get('token')
    new_password = data.get('new_password', '')
    prt = PasswordResetToken.query.filter_by(token=token, used=False).first()
    if not prt or prt.expires_at < datetime.utcnow() or len(new_password) < 8:
        return jsonify({'success': False, 'error': 'Invalid token or password'}), 400
    user = User.query.get(prt.user_id)
    user.password_hash = hash_password(new_password)
    prt.used = True
    invalidate_user_sessions(user.id)
    log_platform_admin('token_password_reset', target_user_id=user.id, tenant=session.get('selected_community_id'))
    db.session.commit()
    return jsonify({'success': True, 'message': 'Password reset successful'})


@app.route('/api/platform-owner/recovery/reset-password', methods=['POST'])
@limiter.limit("5 per minute")
def platform_owner_recovery_reset_password():
    data = request.get_json(silent=True) or {}
    configured_token = os.getenv('PLATFORM_OWNER_RECOVERY_TOKEN', '')
    owner_email = (os.getenv('PLATFORM_OWNER_EMAIL') or '').strip().lower()
    email = (data.get('email') or '').strip().lower()
    provided_token = data.get('token', '')
    new_password = data.get('new_password', '')
    confirm_password = data.get('confirm_password', '')

    if not configured_token or provided_token != configured_token:
        return jsonify({'success': False, 'error': 'Invalid recovery token'}), 403
    if len(new_password) < 8 or new_password != confirm_password:
        return jsonify({'success': False, 'error': 'Password validation failed'}), 400

    user = User.query.filter(func.lower(User.email) == email).first()
    if not user:
        return jsonify({'success': False, 'error': 'PlatformOwner account not found'}), 404
    if user.role != 'PlatformOwner' and getattr(user, 'platform_role', None) != 'PlatformOwner' and (not owner_email or email != owner_email):
        return jsonify({'success': False, 'error': 'User is not eligible for PlatformOwner recovery'}), 403

    user.password_hash = hash_password(new_password)
    user.role = 'PlatformOwner'
    if hasattr(User, 'platform_role'):
        user.platform_role = 'PlatformOwner'
    user.active = True
    invalidate_user_sessions(user.id)
    log_platform_admin('platform_owner_recovery_password_reset', target_user_id=user.id, tenant='*', details={'email': email})
    db.session.commit()
    logger.info("PlatformOwner recovery reset completed for user_id=%s email=%s", user.id, email)
    return jsonify({'success': True, 'message': 'PlatformOwner password reset successfully'})


@app.route('/api/platform-admin/overview', methods=['GET'])
def platform_admin_overview():
    """Get platform admin overview with safe hydration and fallback values."""
    if not is_platform_owner():
        return jsonify({'success': False, 'error': 'Forbidden'}), 403

    try:
        logger.info('Fetching platform admin overview...')
        now = datetime.utcnow()

        def _safe_isoformat(dt):
            """Safely convert a datetime to ISO string, returning None on failure."""
            if dt is None:
                return None
            try:
                if isinstance(dt, datetime):
                    return dt.isoformat()
                return str(dt)
            except Exception:
                return None

        # --- Communities ---
        logger.info('Hydrating communities...')
        community_rows = []
        try:
            communities = Community.query.order_by(Community.created_at.desc()).all()
            for c in communities:
                try:
                    active_sessions_count = 0
                    try:
                        active_sessions_count = UserSession.query.filter_by(
                            tenant=c.community_id, active=True
                        ).count()
                    except Exception as e:
                        logger.warning(f'Could not count active sessions for community {c.community_id}: {e}')

                    last_seen = None
                    try:
                        last_session = UserSession.query.filter_by(
                            tenant=c.community_id
                        ).order_by(UserSession.last_seen.desc()).first()
                        if last_session and last_session.last_seen:
                            last_seen = last_session.last_seen
                    except Exception as e:
                        logger.warning(f'Could not fetch last session for community {c.community_id}: {e}')

                    owner_username = 'Unknown'
                    try:
                        if c.owner_user_id:
                            owner_user = User.query.get(c.owner_user_id)
                            if owner_user and owner_user.username:
                                owner_username = owner_user.username
                    except Exception as e:
                        logger.warning(f'Could not fetch owner for community {c.community_id}: {e}')

                    member_count = 0
                    try:
                        member_count = CommunityMember.query.filter_by(
                            community_id=c.community_id, status='Active'
                        ).count()
                    except Exception as e:
                        logger.warning(f'Could not count members for community {c.community_id}: {e}')

                    if last_seen and (now - last_seen).total_seconds() < 300:
                        live_status = 'ONLINE'
                    elif last_seen and (now - last_seen).total_seconds() < 1800:
                        live_status = 'IDLE'
                    else:
                        live_status = 'OFFLINE'

                    community_rows.append({
                        'community_id': c.community_id,
                        'name': c.name or 'Unknown',
                        'slug': c.slug,
                        'cad_name': c.cad_name or c.name or 'Unknown',
                        'owner_username': owner_username,
                        'member_count': member_count,
                        'online_users': active_sessions_count,
                        'last_active': _safe_isoformat(last_seen),
                        'status': live_status or 'OFFLINE',
                    })
                except Exception as e:
                    logger.warning(f'Error serializing community {getattr(c, "community_id", "unknown")}: {e}')
                    continue
            logger.info(f'Hydrated {len(community_rows)} communities')
        except Exception as e:
            logger.error(f'Failed to hydrate communities: {e}', exc_info=True)
            communities = []

        # --- Users ---
        logger.info('Hydrating users...')
        user_rows = []
        try:
            users = User.query.order_by(User.created_at.desc()).limit(200).all()
            for u in users:
                try:
                    last_login_iso = _safe_isoformat(u.last_login)
                    if u.last_login and (now - u.last_login).total_seconds() < 300:
                        online_status = 'ONLINE'
                    elif u.last_login and (now - u.last_login).total_seconds() < 1800:
                        online_status = 'IDLE'
                    else:
                        online_status = 'OFFLINE'

                    session_count = 0
                    try:
                        session_count = UserSession.query.filter_by(
                            user_id=u.id, active=True
                        ).count()
                    except Exception as e:
                        logger.warning(f'Could not count sessions for user {u.id}: {e}')

                    user_rows.append({
                        'id': u.id,
                        'username': u.username or 'Unknown',
                        'email': u.email or 'Unknown',
                        'platform_role': u.role or 'User',
                        'tenant_role': normalize_community_role((getattr(CommunityMember.query.filter_by(user_id=u.id, status='Active').first(), 'role', None))) or 'Unknown',
                        'last_login': last_login_iso,
                        'sessions': session_count,
                        'session_count': session_count,
                        'status': online_status,
                        'online_status': online_status,
                    })
                except Exception as e:
                    logger.warning(f'Error serializing user {getattr(u, "id", "unknown")}: {e}')
                    continue
            logger.info(f'Hydrated {len(user_rows)} users')
        except Exception as e:
            logger.error(f'Failed to hydrate users: {e}', exc_info=True)
            users = []

        # --- Activity feed ---
        logger.info('Hydrating activity feed...')
        recent_activity = []
        try:
            activity_logs = ActivityLog.query.order_by(
                ActivityLog.created_at.desc()
            ).limit(50).all()
            for a in activity_logs:
                try:
                    recent_activity.append({
                        'id': getattr(a, 'log_id', None),
                        'action': getattr(a, 'action', '') or '',
                        'officer': getattr(a, 'officer', '') or '',
                        'details': getattr(a, 'details', '') or '',
                        'timestamp': _safe_isoformat(getattr(a, 'created_at', None)),
                        # legacy keys used by some frontend versions
                        'type': getattr(a, 'action', 'activity') or 'activity',
                        'message': getattr(a, 'details', '') or getattr(a, 'action', '') or '',
                        'created_at': _safe_isoformat(getattr(a, 'created_at', None)),
                    })
                except Exception as e:
                    logger.warning(f'Error serializing activity log: {e}')
                    continue
            logger.info(f'Hydrated {len(recent_activity)} activity logs')
        except Exception as e:
            logger.error(f'Failed to hydrate activity feed: {e}', exc_info=True)

        # --- Aggregate metrics (each wrapped independently) ---
        def _safe_count(query_fn):
            try:
                return query_fn()
            except Exception as e:
                logger.warning(f'Count query failed: {e}')
                return 0

        total_communities = len(community_rows)
        total_users = len(user_rows)
        online_users = _safe_count(lambda: UserSession.query.filter_by(active=True).count())
        active_sessions = online_users
        total_arrests = _safe_count(lambda: Arrest.query.count())
        total_warrants = _safe_count(lambda: Warrant.query.count())
        total_civilians = _safe_count(lambda: Civilian.query.count())
        total_businesses = _safe_count(lambda: Business.query.count())
        total_officers = _safe_count(lambda: OfficerSession.query.count())
        total_bolos = _safe_count(lambda: Bolo.query.count())
        total_dispatch_calls = _safe_count(lambda: DispatchCall.query.count())
        total_hearings = _safe_count(lambda: Hearing.query.count())
        total_evidence_records = _safe_count(lambda: Evidence.query.count())

        logger.info('Platform admin overview hydrated successfully')
        return jsonify({'success': True, 'overview': {
            'total_communities': total_communities,
            'total_users': total_users,
            'online_users': online_users,
            'active_sessions': active_sessions,
            'total_arrests': total_arrests,
            'total_warrants': total_warrants,
            'total_civilians': total_civilians,
            'total_businesses': total_businesses,
            'total_officers': total_officers,
            'total_bolos': total_bolos,
            'total_dispatch_calls': total_dispatch_calls,
            'total_hearings': total_hearings,
            'total_evidence_records': total_evidence_records,
            'communities': community_rows,
            'users': user_rows,
            'activity': recent_activity,
        }})

    except Exception as e:
        logger.error(f'Platform admin overview failed: {e}', exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Failed to load platform overview',
            'details': str(e) if app.debug else 'Internal server error',
        }), 500


@app.route('/api/platform-admin/users/<int:user_id>/reset-password', methods=['POST'])
def platform_admin_reset_password(user_id):
    if not is_platform_owner():
        return jsonify({'success': False, 'error': 'Forbidden'}), 403
    data = request.get_json(silent=True) or {}
    user = User.query.get_or_404(user_id)
    user.password_hash = hash_password(data.get('new_password', ''))
    invalidate_user_sessions(user.id)
    log_platform_admin('platform_password_reset', target_user_id=user.id, tenant='*')
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/community-admin/overview', methods=['GET'])
@require_auth
def community_admin_overview():
    community_id = get_current_community_id()
    current_user_id = session.get('user_id')
    membership = CommunityMember.query.filter_by(user_id=current_user_id, community_id=community_id, status='Active').first()
    community = Community.query.filter_by(community_id=community_id).first()
    if not has_community_owner_access(current_user_id, community=community, membership=membership):
        return jsonify({'success': False, 'error': 'Forbidden'}), 403

    try:
        members = CommunityMember.query.filter_by(community_id=community_id, status='Active').all()
    except Exception as e:
        logger.warning(f'Community admin members hydration failed for {community_id}: {e}')
        members = []
    try:
        invites = CommunityInvite.query.filter_by(community_id=community_id, active=True).all()
    except Exception as e:
        logger.warning(f'Community admin invites hydration failed for {community_id}: {e}')
        invites = []
    try:
        officer_sessions = scoped_query(OfficerSession, community_id).order_by(OfficerSession.updated_at.desc()).all()
    except Exception as e:
        logger.warning(f'Community admin officer sessions hydration failed for {community_id}: {e}')
        officer_sessions = []
    try:
        activities = [activity_log_to_dict(a) for a in scoped_query(ActivityLog, community_id).order_by(ActivityLog.created_at.desc()).limit(50).all()]
    except Exception as e:
        logger.warning(f'Community admin activity hydration failed for {community_id}: {e}')
        activities = []

    user_map = {u.id: u for u in User.query.filter(User.id.in_([m.user_id for m in members])).all()} if members else {}
    session_map = {s.user_id: s for s in UserSession.query.filter(UserSession.user_id.in_(list(user_map.keys())), UserSession.active.is_(True)).all()} if user_map else {}

    owner_username = 'Unknown'
    if community and community.owner_user_id:
        try:
            owner = User.query.get(community.owner_user_id)
            owner_username = owner.username if owner and owner.username else 'Unknown'
        except Exception as e:
            logger.warning(f'Owner lookup failed for {community_id}: {e}')

    def _safe_count(query_fn):
        try:
            return query_fn()
        except Exception as e:
            logger.warning(f'Community admin count query failed for {community_id}: {e}')
            return 0

    return jsonify({'success': True, 'overview': {
        'community': {
            'community_id': community.community_id if community else community_id,
            'slug': community.slug if community else None,
            'name': community.name if community else 'Unknown',
            'cad_name': community.cad_name if community else 'Unknown',
            'owner_user_id': community.owner_user_id if community else None,
            'owner_username': owner_username,
            'status': community.status if community and community.status else 'OFFLINE',
        },
        'total_members': len(members),
        'online_members': _safe_count(lambda: UserSession.query.filter_by(tenant=community_id, active=True).count()),
        'officers': _safe_count(lambda: OfficerSession.query.filter_by(community_id=community_id).count()),
        'civilians': _safe_count(lambda: Civilian.query.filter_by(community_id=community_id).count()),
        'active_calls': _safe_count(lambda: DispatchCall.query.filter_by(community_id=community_id, status='Active').count()),
        'active_warrants': _safe_count(lambda: Warrant.query.filter_by(community_id=community_id, warrant_status='Active').count()),
        'members': [{
            'user_id': m.user_id,
            'username': user_map.get(m.user_id).username if user_map.get(m.user_id) else f'user-{m.user_id}',
            'role': m.role,
            'callsign': None,
            'department': None,
            'last_active': session_map.get(m.user_id).last_seen.isoformat() if session_map.get(m.user_id) and session_map.get(m.user_id).last_seen else None,
            'status': 'ONLINE' if session_map.get(m.user_id) else 'OFFLINE',
        } for m in members],
        'invites': [i.to_dict() for i in invites],
        'activity': activities,
        'officer_sessions': [officer_session_response(s) for s in officer_sessions],
    }})
