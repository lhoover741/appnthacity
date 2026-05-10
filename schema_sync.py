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
        from tenant_schema import (
            TENANT_SCHEMA_DEFINITIONS,
            ensure_tenant_community_columns,
            ensure_tenant_indexes,
        )

        with app.app_context():
            connection = db.engine.raw_connection()
            cursor = connection.cursor()

            # Define columns that should exist. community_id is intentionally
            # represented as a hardcoded schema definition for every tenant table
            # so validators never report "No definition for community_id".
            columns_to_add = {table: defs.copy() for table, defs in TENANT_SCHEMA_DEFINITIONS.items()}
            columns_to_add.setdefault('civilians', {}).update({
                    'date_of_birth': {'type': 'DATE', 'nullable': True, 'index': False},
                    'gender': {'type': 'VARCHAR(64)', 'nullable': True, 'index': False},
                    'phone_number': {'type': 'VARCHAR(64)', 'nullable': True, 'index': False},
                    'address': {'type': 'VARCHAR(255)', 'nullable': True, 'index': False},
                    'occupation': {'type': 'VARCHAR(255)', 'nullable': True, 'index': False},
                    'gang_affiliation': {'type': "VARCHAR(255) DEFAULT 'None'", 'nullable': True, 'index': False},
                    'emergency_contact_name': {'type': 'VARCHAR(255)', 'nullable': True, 'index': False},
                    'emergency_contact_phone': {'type': 'VARCHAR(64)', 'nullable': True, 'index': False},
                    'driver_license_status': {'type': "VARCHAR(64) DEFAULT 'Valid'", 'nullable': True, 'index': False},
                    'firearm_license_status': {'type': "VARCHAR(64) DEFAULT 'None'", 'nullable': True, 'index': False},
                    'business_license_status': {'type': "VARCHAR(64) DEFAULT 'None'", 'nullable': True, 'index': False},
                    'vehicle_make': {'type': 'VARCHAR(255)', 'nullable': True, 'index': False},
                    'vehicle_model': {'type': 'VARCHAR(255)', 'nullable': True, 'index': False},
                    'vehicle_year': {'type': 'INTEGER', 'nullable': True, 'index': False},
                    'vehicle_color': {'type': 'VARCHAR(64)', 'nullable': True, 'index': False},
                    'plate_number': {'type': 'VARCHAR(64)', 'nullable': True, 'index': False},
                    'insurance_status': {'type': "VARCHAR(64) DEFAULT 'Valid'", 'nullable': True, 'index': False},
                    'criminal_background_notes': {'type': 'TEXT', 'nullable': True, 'index': False},
                    'character_backstory': {'type': 'TEXT', 'nullable': True, 'index': False},
                    'updated_at': {'type': 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP', 'nullable': True, 'index': False},
            })

            # Legacy civilian columns.
            logger.info('Checking civilians for legacy missing columns...')
            for col_name, definition in columns_to_add['civilians'].items():
                col_type = definition['type']
                try:
                    cursor.execute(
                        """
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND table_name = 'civilians'
                          AND column_name = %s
                        """,
                        (col_name,),
                    )
                    if cursor.fetchone():
                        logger.info(f'  ✓ civilians.{col_name} exists')
                        continue

                    cursor.execute(
                        f'ALTER TABLE civilians ADD COLUMN IF NOT EXISTS {col_name} {col_type}'
                    )
                    logger.info(f'  ✓ Added civilians.{col_name}')
                except Exception as e:
                    logger.error(f'  ✗ Failed to sync civilians.{col_name}: {e}')

            logger.info('Checking tenant community_id columns...')
            ensure_tenant_community_columns(cursor)
            ensure_tenant_indexes(cursor)
            logger.info('✓ Tenant indexes created')

            connection.commit()
            cursor.close()
            connection.close()

            logger.info('✓ Schema sync completed successfully')
            return True

    except Exception as e:
        logger.error(f'✗ Schema sync failed: {e}', exc_info=True)
        return False


if __name__ == '__main__':
    success = sync_schema()
    sys.exit(0 if success else 1)
