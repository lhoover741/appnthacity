import random
import secrets
import logging
import json
from datetime import datetime, timedelta
from database import db
from models import Civilian

logger = logging.getLogger(__name__)


def check_name_exists(first_name, last_name):
    """Check if name already exists in database."""
    civilian = Civilian.query.filter(
        (Civilian.first_name.ilike(first_name)) &
        (Civilian.last_name.ilike(last_name))
    ).first()
    return civilian is not None


def generate_ai_civilian(params):
    """Generate civilian using AI with fallback to local generator."""
    from ai_character_engine import generate_character
    from world_realism_service import generate_name, generate_address, generate_vehicle

    # Try AI generation first
    try:
        ai_result = generate_character(
            params.get('age', random.randint(18, 70)),
            params.get('gender', 'random'),
            params.get('ethnicity', 'random'),
            params.get('personality_traits', 'realistic'),
            criminal_history_level='clean',  # FORCE clean record
            gang_affiliation='None',          # FORCE no gang affiliation
            occupation_type=params.get('occupation_type', 'random'),
            risk_level='Low',                 # FORCE low risk
            vehicle_preference=params.get('vehicle_preference', 'random'),
            neighborhood=params.get('neighborhood', 'random'),
        )

        if 'error' not in ai_result:
            return ai_result, 'ai'
    except Exception as e:
        logger.warning(f'AI generation failed, using fallback: {e}')

    # Fallback to local generator with clean record
    name = generate_name(params.get('gender', 'random'))

    # Check for duplicates and regenerate if needed
    attempts = 0
    while check_name_exists(name['first_name'], name['last_name']) and attempts < 5:
        name = generate_name(params.get('gender', 'random'))
        attempts += 1

    address = generate_address(params.get('neighborhood'))
    vehicle = generate_vehicle()

    return {
        'first_name': name['first_name'],
        'last_name': name['last_name'],
        'full_name': name['full_name'],
        'date_of_birth': (datetime.now() - timedelta(days=random.randint(18 * 365, 70 * 365))).strftime('%Y-%m-%d'),
        'age': random.randint(18, 70),
        'gender': name['gender'],
        'ethnicity': params.get('ethnicity', 'random'),
        'phone_number': f"555-{random.randint(1000, 9999)}",
        'address': address,
        'occupation': params.get('occupation_type', 'random'),
        'biography': f"New resident of {params.get('neighborhood', 'the city')}. Just arrived looking for opportunities.",

        # CLEAN RECORD - NO EXCEPTIONS
        'criminal_background': 'Clean record',
        'gang_affiliation': 'None',
        'gang_rank': 'None',
        'parole_status': 'None',
        'probation_status': 'None',
        'warrant_risk': 'None',
        'risk_level': 'Low',
        'officer_safety_notes': 'No known issues. Clean background.',
        'violence_history': 'None',
        'weapon_access': 'None',
        'addiction_status': 'None',
        'addiction_severity': 'None',
        'weapon_permit': False,
        'insurance_status': 'Valid',
        'driver_license_status': 'Valid',

        # VEHICLE (randomized)
        'vehicle_make': vehicle['make'],
        'vehicle_model': vehicle['make'],
        'vehicle_color': vehicle['color'],
        'vehicle_plate': vehicle['plate'],
        'vehicle_vin': vehicle['vin'],
    }, 'fallback'


def save_generated_civilian(ai_data):
    """Save generated civilian to database."""
    from cad_helpers import create_civilian_from_ai, log_ai_generation

    try:
        civilian = create_civilian_from_ai(ai_data)
        log_ai_generation('ai_assist', str(ai_data), f'Created {civilian.civilian_id}', status='Success')
        return civilian
    except Exception as e:
        db.session.rollback()
        logger.error(f'Failed to save civilian: {e}')
        log_ai_generation('ai_assist', str(ai_data), 'Failed', status='Error', error_message=str(e))
        raise
