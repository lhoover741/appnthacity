#!/usr/bin/env python
"""Safely sync PostgreSQL schema with SQLAlchemy model."""

import os
import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def sync_schema():
    """Sync PostgreSQL schema with SQLAlchemy model."""
    try:
        logger.info('Starting schema sync...')

        from server import app
        from database import db

        with app.app_context():
            # Get database connection
            connection = db.engine.raw_connection()
            cursor = connection.cursor()

            # Define columns that should exist (matching the Civilian SQLAlchemy model)
            columns_to_add = [
                ('date_of_birth', 'DATE'),
                ('gender', 'VARCHAR(64)'),
                ('phone_number', 'VARCHAR(64)'),
                ('address', 'VARCHAR(255)'),
                ('occupation', 'VARCHAR(255)'),
                ('gang_affiliation', "VARCHAR(255) DEFAULT 'None'"),
                ('emergency_contact_name', 'VARCHAR(255)'),
                ('emergency_contact_phone', 'VARCHAR(64)'),
                ('driver_license_status', "VARCHAR(64) DEFAULT 'Valid'"),
                ('firearm_license_status', "VARCHAR(64) DEFAULT 'None'"),
                ('business_license_status', "VARCHAR(64) DEFAULT 'None'"),
                ('vehicle_make', 'VARCHAR(255)'),
                ('vehicle_model', 'VARCHAR(255)'),
                ('vehicle_year', 'INTEGER'),
                ('vehicle_color', 'VARCHAR(64)'),
                ('plate_number', 'VARCHAR(64)'),
                ('insurance_status', "VARCHAR(64) DEFAULT 'Valid'"),
                ('criminal_background_notes', 'TEXT'),
                ('character_backstory', 'TEXT'),
                ('updated_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
            ]

            # Check and add missing columns
            logger.info('Checking for missing columns...')
            missing_columns = []

            for col_name, col_type in columns_to_add:
                try:
                    cursor.execute("""
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name='civilians' AND column_name=%s
                    """, (col_name,))

                    if not cursor.fetchone():
                        missing_columns.append((col_name, col_type))
                        logger.info(f'  Missing: {col_name}')
                    else:
                        logger.info(f'  \u2713 {col_name} exists')
                except Exception as e:
                    logger.warning(f'  Error checking {col_name}: {e}')

            # Add missing columns
            if missing_columns:
                logger.info(f'Adding {len(missing_columns)} missing columns...')
                for col_name, col_type in missing_columns:
                    try:
                        sql = f'ALTER TABLE civilians ADD COLUMN IF NOT EXISTS {col_name} {col_type}'
                        cursor.execute(sql)
                        logger.info(f'  \u2713 Added {col_name}')
                    except Exception as e:
                        logger.error(f'  \u2717 Failed to add {col_name}: {e}')

                connection.commit()
                logger.info('\u2713 All missing columns added')
            else:
                logger.info('\u2713 All columns already exist')

            cursor.close()
            connection.close()

            logger.info('\u2713 Schema sync completed successfully')
            return True

    except Exception as e:
        logger.error(f'\u2717 Schema sync failed: {e}', exc_info=True)
        return False


if __name__ == '__main__':
    success = sync_schema()
    sys.exit(0 if success else 1)
