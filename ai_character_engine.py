import os
import json
import logging
import requests
import random
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY', '')
OPENROUTER_BASE_URL = 'https://openrouter.ai/api/v1'

# Realistic data for GTA RP
ETHNICITIES = ['African American', 'Hispanic/Latino', 'Caucasian', 'Asian', 'Middle Eastern', 'Mixed']
GANG_AFFILIATIONS = ['None', 'Grove Street Families', 'Ballas', 'Vagos', 'Mafia', 'Triads', 'Bikers', 'Street Crew']
OCCUPATIONS = [
    'Construction Worker', 'Mechanic', 'Taxi Driver', 'Security Guard', 'Bartender',
    'Waiter/Waitress', 'Retail Clerk', 'Delivery Driver', 'Bouncer', 'Stripper',
    'Drug Dealer', 'Hustler', 'Prostitute', 'Thief', 'Enforcer', 'Unemployed',
    'Truck Driver', 'Electrician', 'Plumber', 'Carpenter', 'Painter', 'Cleaner',
    'Fast Food Worker', 'Cashier', 'Janitor', 'Security Officer', 'Bodyguard'
]
NEIGHBORHOODS = [
    'Grove Street', 'Ballas Territory', 'Downtown', 'Vinewood', 'Pillbox Hill',
    'Del Perro', 'Vespucci', 'Sandy Shores', 'Paleto Bay', 'Grapeseed',
    'Chumash', 'Blaine County', 'Mirror Park', 'Rockford Hills', 'Maze Bank'
]
STREET_NAMES = [
    'Grove Street', 'Integrity Way', 'Magellan Avenue', 'Pillbox Avenue',
    'Del Perro Boulevard', 'Vespucci Boulevard', 'Innocence Boulevard',
    'Prosperity Street', 'Cougar Avenue', 'Ginger Street', 'Amarillo Avenue'
]
MENTAL_STATES = [
    'Stable', 'Anxious', 'Paranoid', 'Aggressive', 'Depressed',
    'Manic', 'Calm', 'Volatile', 'Suicidal ideation', 'Substance abuse issues'
]
RISK_FACTORS = [
    'None', 'Violent history', 'Weapons access', 'Gang ties', 'Drug addiction',
    'Mental illness', 'Suicidal', 'Homicidal', 'Escape risk', 'Assault history'
]
VEHICLE_MAKES = [
    'Baller', 'Blista', 'Dilettante', 'Fugitive', 'Granger', 'Habanero',
    'Jackal', 'Khamelion', 'Landstalker', 'Oracle', 'Patriot', 'Rocoto',
    'Rumpo', 'Serrano', 'Tailgater', 'Tornado', 'Warrener', 'Washington'
]
VEHICLE_COLORS = [
    'Black', 'White', 'Gray', 'Silver', 'Red', 'Blue', 'Green', 'Yellow',
    'Orange', 'Purple', 'Brown', 'Gold', 'Lime', 'Cyan', 'Pink'
]


def generate_realistic_address(neighborhood):
    """Generate a realistic GTA-style address."""
    street = random.choice(STREET_NAMES)
    number = random.randint(100, 9999)
    return f"{number} {street}, {neighborhood}"


def generate_plate():
    """Generate a realistic GTA-style license plate."""
    formats = [
        lambda: f"{random.randint(1,9)}{random.randint(0,9)}{random.randint(0,9)} {random.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ')}{random.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ')}{random.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ')}",
        lambda: f"{random.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ')}{random.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ')}{random.randint(10,99)} {random.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ')}{random.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ')}{random.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ')}",
    ]
    return random.choice(formats)()


def generate_character_prompt(age, gender, race, personality_traits, criminal_history_level,
                              gang_affiliation, occupation_type, risk_level, vehicle_preference, neighborhood):
    """Generate detailed character generation prompt."""

    return f"""You are an expert GTA RP character designer. Generate a DEEPLY REALISTIC, IMMERSIVE character with complex background.

PARAMETERS:
- Age: {age}
- Gender: {gender}
- Ethnicity: {race}
- Personality: {personality_traits}
- Criminal History: {criminal_history_level}
- Gang Affiliation: {gang_affiliation}
- Occupation: {occupation_type}
- Risk Level: {risk_level}
- Vehicle Preference: {vehicle_preference}
- Neighborhood: {neighborhood}

CRITICAL REQUIREMENTS:
1. Generate UNIQUE names - NEVER use generic names (John Doe, Jane Doe, Mike Smith, Marcus Smith)
2. Use diverse, realistic names appropriate for ethnicity
3. Create complex, believable character with depth
4. Generate realistic GTA-style addresses
5. Create realistic employment history
6. Generate realistic vehicle with plate
7. Create believable social connections
8. Generate realistic warrants/charges if applicable
9. Create officer safety warnings based on history
10. Make character feel like a real person with real problems

Return ONLY valid JSON (no markdown, no code blocks):
{{
  "first_name": "unique first name",
  "last_name": "unique last name",
  "nickname": "street name or nickname",
  "date_of_birth": "YYYY-MM-DD",
  "age": {age},
  "gender": "{gender}",
  "ethnicity": "{race}",
  "phone_number": "555-XXXX",
  "address": "realistic GTA address",
  "occupation": "specific job title",
  "employment_history": "2-3 previous jobs with dates",
  "biography": "3-4 sentence detailed RP biography",
  "criminal_background": "detailed criminal history or 'Clean record'",
  "known_associates": ["name1", "name2", "name3"],
  "aliases": ["alias1", "alias2"],
  "gang_affiliation": "{gang_affiliation}",
  "gang_rank": "member/lieutenant/captain or 'None'",
  "mental_state": "mental health assessment",
  "habits": ["habit1", "habit2", "habit3"],
  "social_behavior": "how they interact with others",
  "vehicle_make": "vehicle make",
  "vehicle_model": "vehicle model",
  "vehicle_color": "vehicle color",
  "vehicle_plate": "realistic plate format",
  "vehicle_vin": "realistic VIN",
  "warrants": ["charge1", "charge2"],
  "parole_status": "None/Active/Expired",
  "probation_status": "None/Active/Expired",
  "warrant_risk": "Low/Medium/High",
  "officer_safety_notes": "specific safety concerns or 'No known issues'",
  "dispatch_lookup_summary": "one-line dispatch summary",
  "risk_factors": ["factor1", "factor2"],
  "weapon_access": "None/Suspected/Confirmed",
  "violence_history": "None/Minor/Moderate/Severe"
}}

Make this character FEEL REAL. Include contradictions, flaws, and depth. Avoid stereotypes."""


def generate_character(age, gender, race, personality_traits, criminal_history_level,
                       gang_affiliation, occupation_type, risk_level, vehicle_preference, neighborhood):
    """Generate a deeply realistic AI character."""

    if not OPENROUTER_API_KEY:
        logger.error('OPENROUTER_API_KEY not configured')
        return {'error': 'AI service not configured'}

    prompt = generate_character_prompt(age, gender, race, personality_traits, criminal_history_level,
                                       gang_affiliation, occupation_type, risk_level, vehicle_preference, neighborhood)

    try:
        response = requests.post(
            f'{OPENROUTER_BASE_URL}/chat/completions',
            headers={
                'Authorization': f'Bearer {OPENROUTER_API_KEY}',
                'Content-Type': 'application/json',
                'HTTP-Referer': 'https://nthacityrp.com',
                'X-Title': 'NThaCityRP Police CAD',
            },
            json={
                'model': 'openrouter/auto',
                'messages': [
                    {'role': 'user', 'content': prompt}
                ],
                'temperature': 0.85,
                'max_tokens': 1500,
            },
            timeout=30
        )

        if response.status_code != 200:
            logger.error(f'OpenRouter API error: {response.status_code} {response.text}')
            return {'error': f'API error: {response.status_code}'}

        data = response.json()
        content = data['choices'][0]['message']['content'].strip()

        # Extract JSON from response
        try:
            # Remove markdown code blocks if present
            if content.startswith('```'):
                content = content.split('```')[1]
                if content.startswith('json'):
                    content = content[4:]

            character_data = json.loads(content)
            return character_data
        except json.JSONDecodeError as e:
            logger.error(f'Failed to parse AI response: {content[:200]}... Error: {e}')
            return {'error': 'Failed to parse AI response'}

    except requests.RequestException as e:
        logger.error(f'OpenRouter request failed: {e}')
        return {'error': f'Request failed: {str(e)}'}


def generate_narrative(narrative_type, context):
    """Generate AI narratives for reports."""

    if not OPENROUTER_API_KEY:
        return {'error': 'AI service not configured'}

    narrative_prompts = {
        'probable_cause': f"""Generate a professional, court-defensible probable cause statement.

Context: {context}

Return JSON:
{{
  "probable_cause": "detailed probable cause statement",
  "charges_justified": ["charge1", "charge2"],
  "evidence_summary": "summary of evidence"
}}""",

        'arrest_narrative': f"""Generate a professional arrest report narrative.

Context: {context}

Return JSON:
{{
  "narrative": "detailed arrest narrative",
  "charges": ["charge1", "charge2"],
  "summary": "one-paragraph summary"
}}""",

        'dispatch_summary': f"""Generate a dispatch summary for active call.

Context: {context}

Return JSON:
{{
  "dispatch_code": "10-XX code",
  "summary": "brief dispatch summary",
  "priority": "Low/Medium/High/Critical",
  "units_needed": ["unit type1", "unit type2"]
}}""",

        'witness_statement': f"""Generate a realistic witness statement.

Context: {context}

Return JSON:
{{
  "statement": "detailed witness account",
  "credibility": "High/Medium/Low",
  "key_details": ["detail1", "detail2"]
}}""",

        'use_of_force_narrative': f"""Generate a court-defensible use-of-force narrative.

Context: {context}

Return JSON:
{{
  "narrative": "detailed use-of-force narrative",
  "justification": "why force was necessary",
  "injuries": "injuries sustained",
  "force_type": "type of force used"
}}""",
    }

    prompt = narrative_prompts.get(narrative_type, narrative_prompts['arrest_narrative'])

    try:
        response = requests.post(
            f'{OPENROUTER_BASE_URL}/chat/completions',
            headers={
                'Authorization': f'Bearer {OPENROUTER_API_KEY}',
                'Content-Type': 'application/json',
                'HTTP-Referer': 'https://nthacityrp.com',
                'X-Title': 'NThaCityRP Police CAD',
            },
            json={
                'model': 'openrouter/auto',
                'messages': [
                    {'role': 'user', 'content': prompt}
                ],
                'temperature': 0.7,
                'max_tokens': 1000,
            },
            timeout=30
        )

        if response.status_code != 200:
            logger.error(f'OpenRouter API error: {response.status_code}')
            return {'error': f'API error: {response.status_code}'}

        data = response.json()
        content = data['choices'][0]['message']['content'].strip()

        try:
            if content.startswith('```'):
                content = content.split('```')[1]
                if content.startswith('json'):
                    content = content[4:]

            narrative_data = json.loads(content)
            return narrative_data
        except json.JSONDecodeError:
            logger.error(f'Failed to parse narrative response: {content[:200]}')
            return {'error': 'Failed to parse response'}

    except requests.RequestException as e:
        logger.error(f'OpenRouter request failed: {e}')
        return {'error': f'Request failed: {str(e)}'}
