import logging
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from flask import session, jsonify, request

logger = logging.getLogger(__name__)

ROLES = {
    'admin': ['read', 'write', 'delete', 'admin'],
    'dispatcher': ['read', 'write', 'dispatch'],
    'officer': ['read', 'write'],
    'supervisor': ['read', 'write', 'review'],
    'judge': ['read', 'review'],
    'civilian': ['read'],
    'viewer': ['read'],
}

def hash_password(password):
    """Hash a password using Werkzeug."""
    return generate_password_hash(password, method='pbkdf2:sha256')

def verify_password(password_hash, password):
    """Verify a password against its hash."""
    return check_password_hash(password_hash, password)

def require_role(*roles):
    """Decorator to require specific roles."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user_role = session.get('role', 'viewer')
            if user_role not in roles:
                return jsonify({'success': False, 'error': 'Insufficient permissions'}), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def require_auth(f):
    """Decorator to require authentication."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'success': False, 'error': 'Authentication required'}), 401
        return f(*args, **kwargs)
    return decorated_function

def get_user_permissions(role):
    """Get permissions for a role."""
    return ROLES.get(role, ['read'])

def has_permission(role, permission):
    """Check if a role has a permission."""
    permissions = get_user_permissions(role)
    return permission in permissions

def log_security_event(event_type, user_id, details):
    """Log security events."""
    logger.warning(f"SECURITY: {event_type} - User: {user_id} - Details: {details}")
