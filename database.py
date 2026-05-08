import os
import logging
from flask_sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get('DATABASE_URL', '')

if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

db = SQLAlchemy()


def configure_database(app):
    """Configure database and create tables if needed."""
    if DATABASE_URL:
        app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)

        with app.app_context():
            try:
                # Create all tables from models
                db.create_all()
                logger.info('✓ Database tables created/verified')
            except Exception as e:
                logger.error(f'Failed to create tables: {e}')

        return True
    return False
