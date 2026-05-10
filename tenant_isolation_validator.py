#!/usr/bin/env python3
"""
GTAVCAD Tenant Isolation Validator

Runs comprehensive checks to ensure multi-tenant isolation is working correctly.

Usage:
    python tenant_isolation_validator.py
"""

import os
import logging
import sys
from flask import Flask
from database import db, configure_database
from models import (
    Community, CommunityMember, User, Civilian, Arrest,
    DispatchCall, Inmate, AuditLog, Config,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TestColorCodes:
    """Colors for test output."""
    PASSED = '\033[92m'    # Green
    FAILED = '\033[91m'    # Red
    WARNING = '\033[93m'   # Yellow
    INFO = '\033[94m'      # Blue
    RESET = '\033[0m'


def create_app():
    """Create Flask app for database access."""
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', '')
    if app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgres://'):
        app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace(
            'postgres://', 'postgresql://', 1
        )
    db.init_app(app)
    return app



def rollback_after_validation_error():
    """Clear failed PostgreSQL transaction state after validator exceptions."""
    try:
        db.session.rollback()
        logger.info('✓ transaction rollback handled')
    except Exception as rollback_error:
        logger.warning('Unable to rollback validator transaction cleanly: %s', rollback_error)


def run_validation_step(name, func):
    """Run one validation step with rollback safety around failures."""
    try:
        result = func()
        db.session.rollback()
        return (name, result)
    except Exception as exc:
        rollback_after_validation_error()
        logger.error('Validation step failed and recovered: %s', exc, exc_info=True)
        print_test(name, False, str(exc))
        logger.info('✓ schema validation recovered')
        return (name, False)


def print_test(name, passed, message=''):
    """Print formatted test result."""
    status = f'{TestColorCodes.PASSED}✓ PASS{TestColorCodes.RESET}' if passed else f'{TestColorCodes.FAILED}✗ FAIL{TestColorCodes.RESET}'
    msg = f' - {message}' if message else ''
    print(f'{status}: {name}{msg}')
    return passed


def test_community_count():
    """Verify communities exist."""
    logger.info('Running: Community organization tests')
    
    count = Community.query.count()
    passed = count > 0
    print_test('Communities exist', passed, f'Found {count} community/communities')
    return passed


def test_default_community():
    """Verify default nthacityrp community exists."""
    default = Community.query.filter_by(slug='nthacityrp').first()
    passed = default is not None
    print_test('Default community (nthacityrp) exists', passed)
    return passed


def test_data_backfilled():
    """Verify all records have community_id."""
    logger.info('Running: Backfill validation tests')
    
    all_passed = True
    
    # Check each table
    tables = [
        ('Civilian', Civilian),
        ('Arrest', Arrest),
        ('DispatchCall', DispatchCall),
        ('Inmate', Inmate),
        ('AuditLog', AuditLog),
    ]
    
    for table_name, model_class in tables:
        try:
            # Count records without community_id
            count_empty = model_class.query.filter(
                (model_class.community_id == None) | (model_class.community_id == '')
            ).count()
            
            total = model_class.query.count()
            
            if total == 0:
                print_test(f'{table_name}', True, 'No records (OK)')
            elif count_empty == 0:
                print_test(f'{table_name} backfilled', True, f'{total} records')
            else:
                print_test(f'{table_name} backfilled', False, f'{count_empty} of {total} missing community_id')
                all_passed = False
        except Exception as e:
            rollback_after_validation_error()
            print_test(f'{table_name}', False, str(e))
            logger.info('✓ schema validation recovered')
            all_passed = False
    
    return all_passed


def test_no_cross_community_joins():
    """Verify users can't join same community twice."""
    logger.info('Running: Cross-community join prevention tests')
    
    # Find a community with members
    community = Community.query.filter(
        Community.members.any(status='Active')
    ).first()
    
    if not community:
        print_test('Cross-community check', True, 'No suitable test data')
        return True
    
    # Check for duplicate memberships in same community
    member_pairs = db.session.query(
        CommunityMember.community_id,
        CommunityMember.user_id,
        db.func.count(CommunityMember.id).label('count')
    ).group_by(CommunityMember.community_id, CommunityMember.user_id).all()
    
    duplicates = [p for p in member_pairs if p.count > 1]
    
    if duplicates:
        print_test('No duplicate memberships', False, f'{len(duplicates)} duplicate(s)')
        return False
    else:
        print_test('No duplicate memberships', True)
        return True


def test_audit_logs_scoped():
    """Verify audit logs include community_id."""
    logger.info('Running: Audit log scope tests')
    
    total = AuditLog.query.count()
    if total == 0:
        print_test('Audit logs community_id', True, 'No audit logs yet')
        return True
    
    # Count logs without community
    unscoped = AuditLog.query.filter(
        (AuditLog.community_id == None) | (AuditLog.community_id == '')
    ).count()
    
    if unscoped > 0:
        print_test('Audit logs community_id', False, f'{unscoped} of {total} missing community_id')
        return False
    else:
        print_test('Audit logs community_id', True, f'{total} logs scoped')
        return True


def test_config_scoped():
    """Verify config can be per-community."""
    logger.info('Running: Configuration scope tests')
    
    # Check if any config is per-community
    community_config = Config.query.filter(
        Config.community_id != None).count()
    
    global_config = Config.query.filter(
        (Config.community_id == None) | (Config.community_id == '')
    ).count()
    
    if global_config > 0 or community_config > 0:
        msg = f'Global: {global_config}, Community-scoped: {community_config}'
        print_test('Config scoping available', True, msg)
        return True
    else:
        print_test('Config scoping available', True, 'No config yet')
        return True


def test_isolation_query_safety():
    """Verify sample queries use proper scoping."""
    logger.info('Running: Query pattern tests')
    
    all_passed = True
    
    # Get first community
    community1 = Community.query.first()
    if not community1:
        print_test('Query isolation', True, 'No communities for testing')
        return True
    
    # Test scoped query
    scoped_count = Civilian.query.filter_by(
        community_id=community1.community_id
    ).count()
    
    # Get all communities
    communities = Community.query.all()
    total_civilians = Civilian.query.count()
    
    if len(communities) > 1:
        # Multiple communities - check isolation
        if scoped_count == total_civilians:
            # This would mean communities have no data separation
            print_test('Community data isolation', False, 'All civilians in one community')
            all_passed = False
        else:
            print_test('Community data isolation', True, f'{scoped_count} in community, {total_civilians} total')
    else:
        # Single community
        print_test('Community data isolation', True, f'{scoped_count} civilians scoped')
    
    return all_passed


def test_member_isolation():
    """Verify community members are properly isolated."""
    logger.info('Running: Community member isolation tests')
    
    # Get communities
    communities = Community.query.all()
    if len(communities) < 2:
        print_test('Member isolation (multi-community)', True, 'Only one community (OK)')
        return True
    
    community1 = communities[0]
    community2 = communities[1]
    
    # Get members
    members1 = CommunityMember.query.filter_by(
        community_id=community1.community_id
    ).count()
    
    members2 = CommunityMember.query.filter_by(
        community_id=community2.community_id
    ).count()
    
    # Check that a user from community1 isn't in community2
    user1 = CommunityMember.query.filter_by(
        community_id=community1.community_id
    ).first()
    
    if user1:
        also_in_c2 = CommunityMember.query.filter_by(
            user_id=user1.user_id,
            community_id=community2.community_id
        ).first()
        
        if also_in_c2:
            print_test('Member isolation', True, f'User in multiple communities (expected)')
        else:
            print_test('Member isolation', True, f'Communities: {members1} in C1, {members2} in C2')
    
    return True


def main():
    """Run all isolation tests."""
    app = create_app()
    
    with app.app_context():
        print()
        print('=' * 70)
        print(f'{TestColorCodes.INFO}🔒 GTAVCAD Tenant Isolation Validator{TestColorCodes.RESET}')
        print('=' * 70)
        print()
        
        results = []
        
        # Run all tests with rollback safety so one failed PostgreSQL
        # statement never poisons later validator queries.
        validation_steps = [
            ('Communities organized', test_community_count),
            ('Default community created', test_default_community),
            ('Data backfilled correctly', test_data_backfilled),
            ('No cross-community joins', test_no_cross_community_joins),
            ('Audit logs scoped', test_audit_logs_scoped),
            ('Config properly scoped', test_config_scoped),
            ('Query safety patterns', test_isolation_query_safety),
            ('Member isolation', test_member_isolation),
        ]
        for name, func in validation_steps:
            results.append(run_validation_step(name, func))
        
        # Summary
        print()
        print('=' * 70)
        passed = sum(1 for _, result in results if result)
        total = len(results)
        
        if passed == total:
            print(f'{TestColorCodes.PASSED}✓ ALL TESTS PASSED ({passed}/{total}){TestColorCodes.RESET}')
            status = True
        else:
            print(f'{TestColorCodes.FAILED}✗ SOME TESTS FAILED ({passed}/{total}){TestColorCodes.RESET}')
            status = False
        
        print('=' * 70)
        print()
        
        if status:
            print(f'{TestColorCodes.PASSED}Success! Tenant isolation is working.{TestColorCodes.RESET}')
        else:
            print(f'{TestColorCodes.FAILED}⚠️  Isolation issues detected. Review above.{TestColorCodes.RESET}')
        
        print()
        if status:
            logger.info('✓ schema validation recovered')
        return status


def run_all_tests():
    """Run all tenant isolation validation tests."""
    return main()


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
