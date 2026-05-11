#!/usr/bin/env python
"""Update admin user password hash and permissions."""

import os
import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def migrate_admin_password():
    """Update admin user password hash and permissions."""
    try:
        logger.info('=' * 80)
        logger.info('ADMIN PASSWORD AND PERMISSIONS MIGRATION')
        logger.info('=' * 80)

        from server import app
        from database import db

        with app.app_context():
            connection = db.engine.raw_connection()
            cursor = connection.cursor()

            # 1. Check if users table exists
            logger.info('\n1. Checking if users table exists...')
            cursor.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'users'
                )
            """)

            if not cursor.fetchone()[0]:
                logger.error('   ✗ users table does not exist')
                cursor.close()
                connection.close()
                return False

            logger.info('   ✓ users table exists')

            # 2. Check if admin user exists
            logger.info('\n2. Checking for admin user...')
            cursor.execute("""
                SELECT id, email, password_hash, role, platform_role, active
                FROM users
                WHERE email = 'admin@govdirect.org'
            """)

            admin_user = cursor.fetchone()
            if not admin_user:
                logger.error('   ✗ Admin user (admin@govdirect.org) not found')
                cursor.close()
                connection.close()
                return False

            user_id, email, current_hash, current_role, current_platform_role, current_active = admin_user
            logger.info(f'   ✓ Found user: {email}')
            logger.info(f'     Current role: {current_role}')
            logger.info(f'     Current platform_role: {current_platform_role}')
            logger.info(f'     Current active: {current_active}')
            if current_hash:
                logger.info(f'     Current password_hash: {current_hash[:20]}...')
            else:
                logger.info('     Current password_hash: None')

            # 3. Update admin user
            logger.info('\n3. Updating admin user...')
            new_password_hash = 'pbkdf2:sha256:1000000$cqcgUrSJTy4bVAs1$59ecfd1afb9fc7c659bcffd428d17c1c0778ceed03f1fa8d240c895f8eda0b17'

            try:
                cursor.execute("""
                    UPDATE users
                    SET
                        password_hash = %s,
                        role = 'PlatformOwner',
                        platform_role = 'PlatformOwner',
                        active = true
                    WHERE email = 'admin@govdirect.org'
                """, (new_password_hash,))

                rows_affected = cursor.rowcount
                connection.commit()
                logger.info(f'   ✓ Updated {rows_affected} row(s)')
            except Exception as e:
                logger.error(f'   ✗ Failed to update user: {e}')
                connection.rollback()
                cursor.close()
                connection.close()
                return False

            # 4. Verify update
            logger.info('\n4. Verifying update...')
            cursor.execute("""
                SELECT id, email, password_hash, role, platform_role, active
                FROM users
                WHERE email = 'admin@govdirect.org'
            """)

            updated_user = cursor.fetchone()
            if updated_user:
                user_id, email, new_hash, new_role, new_platform_role, new_active = updated_user
                logger.info(f'   ✓ User: {email}')
                logger.info(f'     New role: {new_role}')
                logger.info(f'     New platform_role: {new_platform_role}')
                logger.info(f'     New active: {new_active}')
                if new_hash:
                    logger.info(f'     New password_hash: {new_hash[:20]}...')
                else:
                    logger.info('     New password_hash: None')

                # Verify all fields are correct
                if (new_role == 'PlatformOwner' and
                        new_platform_role == 'PlatformOwner' and
                        new_active == True and
                        new_hash == new_password_hash):
                    logger.info('   ✓ Update verified successfully')
                else:
                    logger.error('   ✗ Update verification failed - fields do not match expected values')
                    cursor.close()
                    connection.close()
                    return False
            else:
                logger.error('   ✗ User not found after update')
                cursor.close()
                connection.close()
                return False

            cursor.close()
            connection.close()

            logger.info('\n' + '=' * 80)
            logger.info('✓ ADMIN PASSWORD AND PERMISSIONS MIGRATION COMPLETED SUCCESSFULLY')
            logger.info('=' * 80)
            logger.info('\nAdmin user can now login with:')
            logger.info('  Email: admin@govdirect.org')
            logger.info('  Password: [use the password that hashes to the above hash]')
            logger.info('  Role: PlatformOwner')
            logger.info('  Status: Active')
            return True

    except Exception as e:
        logger.error(f'Migration failed: {e}', exc_info=True)
        return False

if __name__ == '__main__':
    success = migrate_admin_password()
    sys.exit(0 if success else 1)
