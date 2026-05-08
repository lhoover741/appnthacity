import logging
import secrets
from datetime import datetime
from database import db
from models import Civilian, AuditLog, AIGenerationLog

logger = logging.getLogger(__name__)


def check_name_uniqueness(first_name, last_name):
    """Check if a name already exists in the database."""
    existing = Civilian.query.filter(
        (Civilian.first_name.ilike(first_name)) &
        (Civilian.last_name.ilike(last_name))
    ).first()
    return existing is None


def find_similar_names(first_name, last_name):
    """Find similar names using fuzzy matching."""
    from difflib import SequenceMatcher

    similar = []
    all_civilians = Civilian.query.all()

    for civ in all_civilians:
        first_ratio = SequenceMatcher(None, first_name.lower(), (civ.first_name or '').lower()).ratio()
        last_ratio = SequenceMatcher(None, last_name.lower(), (civ.last_name or '').lower()).ratio()

        if first_ratio > 0.8 or last_ratio > 0.8:
            similar.append({
                'name': f'{civ.first_name} {civ.last_name}',
                'similarity': max(first_ratio, last_ratio)
            })

    return similar


def create_civilian_from_ai(ai_data):
    """Create a civilian record from AI-generated data."""
    civilian_id = f"CIV-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3)}"

    dob = None
    raw_dob = ai_data.get('date_of_birth', '')
    if raw_dob:
        try:
            dob = datetime.strptime(raw_dob, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            dob = None

    # Normalise JSON-array fields — accept list or string
    def _json_field(val):
        if val is None:
            return None
        if isinstance(val, list):
            import json as _json
            return _json.dumps(val)
        return str(val)

    civilian = Civilian(
        civilian_id=civilian_id,
        first_name=ai_data.get('first_name', ''),
        last_name=ai_data.get('last_name', ''),
        full_name=f"{ai_data.get('first_name', '')} {ai_data.get('last_name', '')}".strip(),
        date_of_birth=dob,
        phone_number=ai_data.get('phone_number', ''),
        address=ai_data.get('address', ''),
        occupation=ai_data.get('occupation', ''),
        biography=ai_data.get('biography', ''),
        # Support both legacy key (mental_state_notes) and new key (mental_state)
        mental_state_notes=ai_data.get('mental_state_notes') or ai_data.get('mental_state', ''),
        race=ai_data.get('ethnicity') or ai_data.get('race', ''),
        age=ai_data.get('age'),
        gender=ai_data.get('gender', ''),
        # Advanced character engine fields (non-criminal)
        nickname=ai_data.get('nickname', ''),
        aliases=_json_field(ai_data.get('aliases')),
        employment_history=ai_data.get('employment_history', ''),
        habits=_json_field(ai_data.get('habits')),
        social_behavior=ai_data.get('social_behavior', ''),
        ai_generated=True,

        # CLEAN RECORD ENFORCEMENT — hardcoded, never read from ai_data
        criminal_background='No criminal history on file',
        gang_affiliation='None',
        gang_rank='None',
        parole_status='None',
        probation_status='None',
        warrant_risk='None',
        risk_level='Low',
        officer_safety_notes='No known issues. Clean background.',
        violence_history='None',
        weapon_access='None',
        addiction_status='None',
        addiction_severity='None',
        weapon_permit=False,
        insurance_status='Valid',
        driver_license_status='Valid',
    )

    try:
        db.session.add(civilian)
        db.session.commit()
        return civilian
    except Exception as e:
        db.session.rollback()
        raise e


def log_audit(officer_name, action, record_type, record_id, before_state=None, after_state=None, ip_address=None):
    """Create an audit log entry."""
    log_id = f"AUD-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3)}"

    audit = AuditLog(
        log_id=log_id,
        officer_name=officer_name,
        action=action,
        record_type=record_type,
        record_id=record_id,
        before_state=before_state,
        after_state=after_state,
        ip_address=ip_address,
    )

    try:
        db.session.add(audit)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f'Audit log failed: {e}')


def log_ai_generation(generation_type, input_params, output_summary, tokens_used=0, cost=0.0, status='Success', error_message=None):
    """Log AI generation for tracking and cost analysis."""
    log_id = f"AI-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3)}"

    ai_log = AIGenerationLog(
        log_id=log_id,
        generation_type=generation_type,
        input_params=str(input_params),
        output_summary=output_summary,
        tokens_used=tokens_used,
        cost=cost,
        status=status,
        error_message=error_message,
    )

    try:
        db.session.add(ai_log)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f'AI log failed: {e}')
