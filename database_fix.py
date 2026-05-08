#!/usr/bin/env python
"""Fix live PostgreSQL database schema."""

import os
import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def fix_database():
    """Fix live PostgreSQL database schema."""
    try:
        logger.info('=' * 80)
        logger.info('DATABASE FIX PROCEDURE')
        logger.info('=' * 80)
        
        from server import app
        from database import db
        
        with app.app_context():
            # Get connection
            connection = db.engine.raw_connection()
            cursor = connection.cursor()
            
            # 1. Check if civilians table exists
            logger.info('\n1. Checking civilians table...')
            cursor.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_name = 'civilians'
                )
            """)
            
            if not cursor.fetchone()[0]:
                logger.error('   ✗ civilians table does not exist!')
                logger.info('   Creating table from SQLAlchemy model...')
                cursor.close()
                connection.close()
                
                # Create all tables
                db.create_all()
                logger.info('   ✓ Table created')
                return True
            
            logger.info('   ✓ Table exists')
            
            # 2. Get live columns
            logger.info('\n2. Getting live columns...')
            cursor.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'civilians'
                ORDER BY ordinal_position
            """)
            
            live_columns = {row[0] for row in cursor.fetchall()}
            logger.info(f'   Found {len(live_columns)} columns')
            
            # 3. Get expected columns
            logger.info('\n3. Getting expected columns...')
            from models import Civilian
            
            expected_columns = {col.name for col in Civilian.__table__.columns}
            logger.info(f'   Expected {len(expected_columns)} columns')
            
            # 4. Find missing columns
            logger.info('\n4. Checking for missing columns...')
            missing = expected_columns - live_columns
            
            if not missing:
                logger.info('   ✓ No missing columns')
                cursor.close()
                connection.close()
                return True
            
            logger.warning(f'   ✗ Missing {len(missing)} columns: {missing}')
            
            # 5. Add missing columns
            logger.info('\n5. Adding missing columns...')
            
            # Define column definitions
            column_defs = {
                'date_of_birth': 'DATE',
                'gender': 'VARCHAR(64)',
                'phone_number': 'VARCHAR(64)',
                'address': 'VARCHAR(255)',
                'occupation': 'VARCHAR(255)',
                'gang_affiliation': "VARCHAR(255) DEFAULT 'None'",
                'emergency_contact_name': 'VARCHAR(255)',
                'emergency_contact_phone': 'VARCHAR(64)',
                'driver_license_status': "VARCHAR(64) DEFAULT 'Valid'",
                'firearm_license_status': "VARCHAR(64) DEFAULT 'None'",
                'business_license_status': "VARCHAR(64) DEFAULT 'None'",
                'vehicle_make': 'VARCHAR(255)',
                'vehicle_model': 'VARCHAR(255)',
                'vehicle_year': 'INTEGER',
                'vehicle_color': 'VARCHAR(64)',
                'plate_number': 'VARCHAR(64)',
                'insurance_status': "VARCHAR(64) DEFAULT 'Valid'",
                'criminal_background_notes': 'TEXT',
                'character_backstory': 'TEXT',
                'updated_at': 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP',
            }
            
            for col_name in missing:
                if col_name not in column_defs:
                    logger.warning(f'   ⚠ No definition for {col_name}, skipping')
                    continue
                
                col_def = column_defs[col_name]
                try:
                    sql = f'ALTER TABLE civilians ADD COLUMN IF NOT EXISTS {col_name} {col_def}'
                    cursor.execute(sql)
                    logger.info(f'   ✓ Added {col_name}')
                except Exception as e:
                    logger.error(f'   ✗ Failed to add {col_name}: {e}')
            
            connection.commit()
            logger.info('   ✓ All columns added')
            
            # 6. Verify fix
            logger.info('\n6. Verifying fix...')
            cursor.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'civilians'
                ORDER BY ordinal_position
            """)
            
            final_columns = {row[0] for row in cursor.fetchall()}
            final_missing = expected_columns - final_columns
            
            if final_missing:
                logger.error(f'   ✗ Still missing: {final_missing}')
                cursor.close()
                connection.close()
                return False
            
            logger.info(f'   ✓ All {len(final_columns)} columns present')
            
            # 7. Test INSERT
            logger.info('\n7. Testing INSERT...')
            try:
                cursor.execute("""
                    INSERT INTO civilians (
                        civilian_id, first_name, last_name, date_of_birth
                    ) VALUES (
                        'TEST-FIX-001', 'Test', 'Fix', '1990-01-01'
                    )
                """)
                connection.commit()
                logger.info('   ✓ INSERT succeeded')
                
                # Clean up
                cursor.execute("DELETE FROM civilians WHERE civilian_id='TEST-FIX-001'")
                connection.commit()
                logger.info('   ✓ Test record cleaned up')
                
            except Exception as e:
                logger.error(f'   ✗ INSERT failed: {e}')
                connection.rollback()
                cursor.close()
                connection.close()
                return False
            
            cursor.close()
            connection.close()
            
            logger.info('\n' + '=' * 80)
            logger.info('✓ DATABASE FIX COMPLETED SUCCESSFULLY')
            logger.info('=' * 80)
            return True
            
    except Exception as e:
        logger.error(f'Fix failed: {e}', exc_info=True)
        return False

if __name__ == '__main__':
    success = fix_database()
    sys.exit(0 if success else 1)
