import os
import sys
import psycopg2

DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    print('DATABASE_URL not set; skipping schema bootstrap')
    sys.exit(0)

if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

CIVILIAN_COLUMNS = [
    ('full_name', 'TEXT'),
    ('date_of_birth', 'TEXT'),
    ('age', 'INTEGER'),
    ('race', 'TEXT'),
    ('phone_number', 'TEXT'),
    ('gang_affiliation', 'TEXT DEFAULT \'None\''),
    ('risk_level', 'TEXT DEFAULT \'Low\''),
    ('parole_status', 'TEXT DEFAULT \'None\''),
    ('probation_status', 'TEXT DEFAULT \'None\''),
    ('weapon_permit', 'BOOLEAN DEFAULT FALSE'),
    ('driver_license_status', 'TEXT'),
    ('ai_generated', 'BOOLEAN DEFAULT FALSE'),
    ('last_known_location', 'TEXT'),
    ('biography', 'TEXT'),
    ('criminal_background', 'TEXT DEFAULT \'Clean record\''),
    ('mental_state_notes', 'TEXT'),
    ('officer_safety_notes', 'TEXT DEFAULT \'No known issues\''),
    ('warrant_risk', 'TEXT DEFAULT \'None\''),
    ('nickname', 'TEXT'),
    ('aliases', 'TEXT'),
    ('employment_history', 'TEXT'),
    ('gang_rank', 'TEXT DEFAULT \'None\''),
    ('habits', 'TEXT'),
    ('social_behavior', 'TEXT'),
    ('weapon_access', 'TEXT DEFAULT \'None\''),
    ('violence_history', 'TEXT DEFAULT \'None\''),
    ('addiction_status', 'TEXT DEFAULT \'None\''),
    ('addiction_severity', 'TEXT DEFAULT \'None\''),
    ('weapon_permit_type', 'TEXT DEFAULT \'None\''),
    ('driving_history', 'TEXT DEFAULT \'None\''),
    ('insurance_status', 'TEXT'),
    ('emergency_contact_name', 'TEXT'),
    ('emergency_contact_phone', 'TEXT'),
    ('emergency_contact_relationship', 'TEXT'),
    ('medical_conditions', 'TEXT DEFAULT \'None\''),
    ('medications', 'TEXT DEFAULT \'None\''),
    ('allergies', 'TEXT DEFAULT \'None\''),
    ('dob', 'TEXT'),
    ('phone', 'TEXT'),
    ('updated_at', 'TIMESTAMP'),
]

BOLO_COLUMNS = [
    ('suspect_name', 'TEXT'),
    ('description', 'TEXT'),
    ('last_location', 'TEXT'),
    ('vehicle', 'TEXT'),
    ('charges', 'TEXT'),
    ('threat_level', 'TEXT'),
    ('issued_by', 'TEXT'),
    ('status', 'TEXT DEFAULT \'Active\''),
    ('auto_generated', 'BOOLEAN DEFAULT FALSE'),
    ('updated_at', 'TIMESTAMP'),
]


def add_columns(cur, table, columns):
    for name, col_type in columns:
        cur.execute(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {col_type};')


def main():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute('''
                CREATE TABLE IF NOT EXISTS civilians (
                    id SERIAL PRIMARY KEY,
                    civilian_id VARCHAR(64) UNIQUE NOT NULL,
                    first_name TEXT,
                    last_name TEXT,
                    gender TEXT,
                    address TEXT,
                    occupation TEXT,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            ''')
            add_columns(cur, 'civilians', CIVILIAN_COLUMNS)

            cur.execute('''
                CREATE TABLE IF NOT EXISTS bolos (
                    id SERIAL PRIMARY KEY,
                    bolo_id VARCHAR(64) UNIQUE NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            ''')
            add_columns(cur, 'bolos', BOLO_COLUMNS)

            cur.execute("UPDATE civilians SET criminal_background = 'Clean record' WHERE criminal_background IS NULL OR criminal_background = '';")
            cur.execute("UPDATE civilians SET gang_affiliation = 'None' WHERE gang_affiliation IS NULL OR gang_affiliation = '';")
            cur.execute("UPDATE civilians SET parole_status = 'None' WHERE parole_status IS NULL OR parole_status = '';")
            cur.execute("UPDATE civilians SET probation_status = 'None' WHERE probation_status IS NULL OR probation_status = '';")
            cur.execute("UPDATE civilians SET warrant_risk = 'None' WHERE warrant_risk IS NULL OR warrant_risk = '';")
            cur.execute("UPDATE civilians SET officer_safety_notes = 'No known issues' WHERE officer_safety_notes IS NULL OR officer_safety_notes = '';")
        print('Schema bootstrap completed successfully')
    finally:
        conn.close()


if __name__ == '__main__':
    main()
