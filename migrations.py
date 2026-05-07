import os
from database import db
from sqlalchemy import text

def run_migrations():
    """Run database migrations to add missing columns to bolos table."""
    
    migrations = [
        "ALTER TABLE bolos ADD COLUMN IF NOT EXISTS suspect_name TEXT;",
        "ALTER TABLE bolos ADD COLUMN IF NOT EXISTS description TEXT;",
        "ALTER TABLE bolos ADD COLUMN IF NOT EXISTS last_seen_location TEXT;",
        "ALTER TABLE bolos ADD COLUMN IF NOT EXISTS threat_level TEXT;",
        "ALTER TABLE bolos ADD COLUMN IF NOT EXISTS issued_by TEXT;",
        "ALTER TABLE bolos ADD COLUMN IF NOT EXISTS auto_generated BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE bolos ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP;",
    ]
    
    try:
        for migration in migrations:
            db.session.execute(text(migration))
            print(f"✓ Executed: {migration}")
        db.session.commit()
        print("✓ All migrations completed successfully!")
    except Exception as e:
        db.session.rollback()
        print(f"✗ Migration failed: {e}")
        raise

if __name__ == '__main__':
    from server import app
    with app.app_context():
        run_migrations()
