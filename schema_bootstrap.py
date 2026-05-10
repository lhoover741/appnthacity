#!/usr/bin/env python
"""Bootstrap database schema on startup."""

import sys
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def bootstrap_schema():
    """Bootstrap database schema."""
    try:
        logger.info('Starting schema bootstrap...')

        # Import Flask app
        from server import app

        with app.app_context():
            from database import db
            from bootstrap_multi_tenant import create_default_community, initialize_default_config
            from tenant_schema import (
                backfill_default_community,
                ensure_tenant_community_columns,
                ensure_tenant_indexes,
            )

            # 1. Create all tables, including Community.
            logger.info('Creating database tables from models...')
            db.create_all()
            logger.info('✓ Community table verified')
            logger.info('✓ Database tables created/verified')

            # 2. Ensure the default community exists before assigning records to it.
            create_default_community(db.session)
            logger.info('✓ Default nthacityrp community verified')

            connection = db.engine.raw_connection()
            cursor = connection.cursor()
            try:
                # 3. Add nullable community_id columns idempotently.
                ensure_tenant_community_columns(cursor)
                connection.commit()

                # 4. Backfill only records where community_id IS NULL.
                backfill_default_community(cursor)
                connection.commit()
                logger.info('✓ community_id backfill complete')

                # 5. Create tenant indexes safely.
                ensure_tenant_indexes(cursor)
                connection.commit()
                logger.info('✓ Tenant indexes created')
            finally:
                cursor.close()
                connection.close()

            # Initialize community-scoped defaults after config.community_id exists.
            initialize_default_config(db.session, 'nthacityrp')

            # Run diagnostic and legacy schema fix for civilian compatibility.
            logger.info('Running database diagnostic...')
            from database_diagnostic import diagnose_database
            if diagnose_database():
                logger.info('✓ Database diagnostic passed')
            else:
                logger.warning('⚠ Database diagnostic found issues, running fix...')
                from database_fix import fix_database
                if fix_database():
                    logger.info('✓ Database fix completed')
                else:
                    logger.error('✗ Database fix failed')
                    return False

            # Run tenant validation if available. Failures are returned to abort
            # invalid deploys, but already-applied idempotent migrations remain safe.
            logger.info('Running tenant validation...')
            from tenant_isolation_validator import run_all_tests
            if run_all_tests():
                logger.info('✓ Tenant validation passed')
            else:
                logger.error('✗ Tenant validation failed')
                return False

            logger.info('✓ Multi-tenant bootstrap complete')
            logger.info('✓ Schema bootstrap completed successfully')
            return True

    except Exception as e:
        logger.error(f'✗ Schema bootstrap failed: {e}', exc_info=True)
        return False


if __name__ == '__main__':
    success = bootstrap_schema()
    sys.exit(0 if success else 1)
