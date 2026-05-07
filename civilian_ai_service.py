import json
import os
import random
import secrets
import urllib.request
from datetime import datetime

FIRST = ['Marcus','Darnell','Sofia','Isaac','Jamal','Elena','Andre','Camila','Trevon','Maya','Rafael','Bianca','DeShawn','Nadia','Victor','Aaliyah','Malik','Isabella','Julian','Keisha']
LAST = ['Rivera','Hayes','Velasquez','Brooks','Moreno','Bennett','Santos','Carter','Mendoza','Washington','Torres','Reed','Coleman','Navarro','Harris','Castillo','Price','Vega','Owens','Flores']
STREETS = ['Forum Drive','Davis Avenue','Grove Street','Carson Avenue','Innocence Boulevard','Jamestown Street','Strawberry Avenue','Vespucci Boulevard','Power Street','Alta Street']
JOBS = ['tow yard dispatcher','nightclub security worker','auto shop assistant','warehouse loader','barber apprentice','delivery driver','mechanic','street vendor','club promoter','construction laborer']
VEHICLES = ['black Dominator partial plate 7QZ','silver Kuruma partial plate 5ZT','blue Sultan partial plate R82','red Baller partial plate 3KJ','white Oracle partial plate 9VN']


def unique_name(existing):
    used = {x.lower().strip() for x in existing if x}
    for _ in range(75):
        name = f"{random.choice(FIRST)} {random.choice(LAST)}"
        if name.lower() not in used:
            return name
    return f"{random.choice(FIRST)} {random.choice(LAST)} {secrets.token_hex(2).upper()}"


def fallback_profile(data, existing=None):
    existing = existing or []
    name = unique_name(existing)
    age = int(data.get('age') or random.randint(21, 45))
    risk = data.get('riskLevel') or data.get('criminalHistoryLevel') or random.choice(['Low','Medium','High'])
    gang = data.get('gangAffiliation') or 'None reported'
    traits = data.get('personalityTraits') or 'guarded, street-smart, reactive under pressure'
    year = datetime.utcnow().year - age
    address = f"{random.randint(100, 9900)} {random.choice(STREETS)}, Los Santos"
    vehicle = data.get('vehiclePreference') or random.choice(VEHICLES)
    return {
        'civilianId': f"CIV-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3).upper()}",
        'fullName': name,
        'dateOfBirth': f"{random.randint(1,12):02d}/{random.randint(1,28):02d}/{year}",
        'age': age,
        'gender': data.get('gender') or 'Not specified',
        'race': data.get('race') or data.get('ethnicity') or 'Not specified',
        'phoneNumber': f"555-{random.randint(200,999)}-{random.randint(1000,9999)}",
        'address': address,
        'occupation': data.get('occupationType') or random.choice(JOBS),
        'gangAffiliation': gang,
        'riskLevel': risk,
        'paroleStatus': 'Possible' if risk == 'High' else 'None known',
        'probationStatus': 'Review recommended' if risk in ['Medium','High'] else 'None known',
        'weaponPermit': 'Unknown',
        'driverLicenseStatus': random.choice(['Valid','Suspended','Expired','Unknown']),
        'vehicleSuggestion': vehicle,
        'knownAssociates': [unique_name(existing + [name]), unique_name(existing + [name])],
        'officerSafetyNotes': f"Use caution. Risk: {risk}. Traits: {traits}.",
        'dispatchLookupSummary': f"{name}, age {age}, last known near {address}. Vehicle: {vehicle}.",
        'biography': f"{name} is a Los Santos resident working as a {data.get('occupationType') or random.choice(JOBS)}. Gang affiliation: {gang}. Personality: {traits}.",
        'notes': 'AI-assisted civilian profile generated for RP use.',
        'aiGenerated': True,
        'lastKnownLocation': data.get('neighborhood') or random.choice(STREETS),
    }


def generate_civilian_profile(data, existing=None):
    existing = existing or []
    api_key = os.environ.get('OPENROUTER_API_KEY')
    fallback = fallback_profile(data, existing)
    if not api_key:
        return fallback
    prompt = 'Return one fictional GTA RP civilian as JSON only. Avoid duplicate names: ' + ', '.join(existing[-50:]) + '. Constraints: ' + json.dumps(data)
    body = {'model': os.environ.get('OPENROUTER_MODEL','openai/gpt-4o-mini'), 'messages': [{'role':'system','content':'Return valid JSON only.'}, {'role':'user','content':prompt}], 'temperature': 0.9}
    try:
        req = urllib.request.Request('https://openrouter.ai/api/v1/chat/completions', data=json.dumps(body).encode(), headers={'Content-Type':'application/json','Authorization':'Bearer '+api_key}, method='POST')
        with urllib.request.urlopen(req, timeout=25) as resp:
            out = json.loads(resp.read().decode())
        text = out['choices'][0]['message']['content'].strip().replace('```json','').replace('```','').strip()
        profile = json.loads(text)
        if not profile.get('fullName') or profile['fullName'].lower() in {x.lower() for x in existing}:
            return fallback
        profile['aiGenerated'] = True
        return profile
    except Exception:
        return fallback
