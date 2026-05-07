import os
import json
import logging
import requests
from datetime import datetime

logger = logging.getLogger(__name__)

OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY', '')
OPENROUTER_BASE_URL = 'https://openrouter.ai/api/v1'


def generate_civilian(age, gender, race, personality_traits, criminal_history_level, gang_affiliation,
                      occupation_type, risk_level, vehicle_preference, neighborhood):
    """Generate a unique AI civilian using OpenRouter."""

    if not OPENROUTER_API_KEY:
        logger.error('OPENROUTER_API_KEY not configured')
        return {'error': 'AI service not configured'}

    prompt = f"""Generate a unique, realistic GTA RP civilian character with the following parameters:
- Age: {age}
- Gender: {gender}
- Race/Ethnicity: {race}
- Personality Traits: {personality_traits}
- Criminal History Level: {criminal_history_level}
- Gang Affiliation: {gang_affiliation}
- Occupation Type: {occupation_type}
- Risk Level: {risk_level}
- Vehicle Preference: {vehicle_preference}
- Neighborhood/Last Known Area: {neighborhood}

Generate UNIQUE names - avoid generic names like John Doe, Jane Doe, Mike Smith, Marcus Smith.
Use diverse, realistic names appropriate for the race/ethnicity specified.

Return a JSON object with:
{{
  "first_name": "unique first name",
  "last_name": "unique last name",
  "date_of_birth": "YYYY-MM-DD",
  "phone_number": "555-XXXX",
  "address": "street address in neighborhood",
  "occupation": "specific job title",
  "biography": "2-3 sentence RP-friendly biography",
  "criminal_background": "criminal history summary or 'Clean record'",
  "known_associates": ["name1", "name2"],
  "vehicle_suggestion": "make model color",
  "warrant_risk": "Low/Medium/High",
  "parole_status": "None/Active/Expired",
  "probation_status": "None/Active/Expired",
  "mental_state_notes": "any mental health notes or 'Stable'",
  "officer_safety_notes": "any safety concerns or 'No known issues'",
  "dispatch_lookup_summary": "one-line dispatch summary"
}}

Make the character feel real and RP-appropriate. Avoid stereotypes."""

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
                'temperature': 0.8,
                'max_tokens': 1000,
            },
            timeout=30
        )

        if response.status_code != 200:
            logger.error(f'OpenRouter API error: {response.status_code} {response.text}')
            return {'error': f'API error: {response.status_code}'}

        data = response.json()
        content = data['choices'][0]['message']['content']

        # Extract JSON from response
        try:
            json_start = content.find('{')
            json_end = content.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                json_str = content[json_start:json_end]
                civilian_data = json.loads(json_str)
                return civilian_data
        except json.JSONDecodeError:
            logger.error(f'Failed to parse AI response: {content}')
            return {'error': 'Failed to parse AI response'}

    except requests.RequestException as e:
        logger.error(f'OpenRouter request failed: {e}')
        return {'error': f'Request failed: {str(e)}'}


def generate_bolo(suspect_name, description, last_location, charges, threat_level):
    """Generate AI BOLO text."""

    if not OPENROUTER_API_KEY:
        return {'error': 'AI service not configured'}

    prompt = f"""Generate a professional BOLO (Be On The Lookout) alert for law enforcement.

Suspect: {suspect_name}
Description: {description}
Last Location: {last_location}
Charges: {charges}
Threat Level: {threat_level}

Return a JSON object with:
{{
  "bolo_summary": "professional 2-3 sentence BOLO summary",
  "dispatch_alert": "urgent dispatch alert text",
  "officer_briefing": "officer briefing notes"
}}"""

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
                'max_tokens': 500,
            },
            timeout=30
        )

        if response.status_code != 200:
            logger.error(f'OpenRouter API error: {response.status_code}')
            return {'error': f'API error: {response.status_code}'}

        data = response.json()
        content = data['choices'][0]['message']['content']

        try:
            json_start = content.find('{')
            json_end = content.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                json_str = content[json_start:json_end]
                bolo_data = json.loads(json_str)
                return bolo_data
        except json.JSONDecodeError:
            logger.error(f'Failed to parse BOLO response: {content}')
            return {'error': 'Failed to parse response'}

    except requests.RequestException as e:
        logger.error(f'OpenRouter request failed: {e}')
        return {'error': f'Request failed: {str(e)}'}


def generate_report(report_type, notes):
    """Generate AI report from rough notes."""

    if not OPENROUTER_API_KEY:
        return {'error': 'AI service not configured'}

    report_prompts = {
        'arrest': 'Generate a professional arrest report from these notes',
        'incident': 'Generate a professional incident report from these notes',
        'use_of_force': 'Generate a court-defensible use-of-force report from these notes',
        'probable_cause': 'Generate a probable cause statement from these notes',
    }

    prompt = f"""{report_prompts.get(report_type, 'Generate a professional report from these notes')}:

{notes}

Return a JSON object with:
{{
  "report_title": "report title",
  "report_body": "professional, objective, chronological report text",
  "summary": "one-paragraph summary"
}}"""

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
                'temperature': 0.6,
                'max_tokens': 1500,
            },
            timeout=30
        )

        if response.status_code != 200:
            logger.error(f'OpenRouter API error: {response.status_code}')
            return {'error': f'API error: {response.status_code}'}

        data = response.json()
        content = data['choices'][0]['message']['content']

        try:
            json_start = content.find('{')
            json_end = content.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                json_str = content[json_start:json_end]
                report_data = json.loads(json_str)
                return report_data
        except json.JSONDecodeError:
            logger.error(f'Failed to parse report response: {content}')
            return {'error': 'Failed to parse response'}

    except requests.RequestException as e:
        logger.error(f'OpenRouter request failed: {e}')
        return {'error': f'Request failed: {str(e)}'}
