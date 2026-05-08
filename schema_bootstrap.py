#!/usr/bin/env python
"""Bootstrap database schema on startup."""

import os
import sys
import logging
from datetime import datetime

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
            # Import database
            from database import db

            # Create all tables from models
            logger.info('Creating database tables from models...')
            db.create_all()
            logger.info('✓ Database tables created/verified')

            # Run diagnostic
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

            logger.info('✓ Schema bootstrap completed successfully')
            return True

    except Exception as e:
        logger.error(f'✗ Schema bootstrap failed: {e}', exc_info=True)
        return False

if __name__ == '__main__':
    success = bootstrap_schema()
    sys.exit(0 if success else 1)
