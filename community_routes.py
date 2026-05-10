"""
GTAVCAD Community Management Endpoints

Provides:
- Community creation/management
- Community joining
- Invite code system
- Member management
- Community selection
"""

import secrets
import logging
from datetime import datetime, timedelta
from flask import Blueprint, request, session, jsonify, g
from database import db
from models import (
    User, Community, CommunityMember, CommunityInvite
)
from community_service import (
    get_current_community_id, get_user_communities,
    community_required,community_member_required,
    community_admin_required_scoped,
)
from security_service import require_auth

logger = logging.getLogger(__name__)

# Create blueprint
community_bp = Blueprint('communities', __name__, url_prefix='/api/communities')


# ========================================
# User Community Management
# ========================================

@community_bp.route('', methods=['GET'])
@require_auth
def list_user_communities():
    """
    GET /api/communities
    
    List all communities for the current user.
    """
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Not authenticated'}), 401

    memberships = CommunityMember.query.filter_by(
        user_id=user_id,
        status='Active'
    ).all()

    communities_data = []
    for membership in memberships:
        community = Community.query.filter_by(
            community_id=membership.community_id
        ).first()
        if community:
            communities_data.append({
                'community': community.to_dict(),
                'membership': membership.to_dict(),
            })

    return jsonify({
        'success': True,
        'communities': communities_data,
        'count': len(communities_data),
        'current_community_id': get_current_community_id(),
    }), 200


@community_bp.route('/select', methods=['POST'])
@require_auth
def select_community():
    """
    POST /api/communities/select
    
    Select active community for the user session.
    
    Body:
    {
        "community_id": "nthacityrp"
    }
    """
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Not authenticated'}), 401

    data = request.get_json() or {}
    community_id = data.get('community_id')

    if not community_id:
        return jsonify({'error': 'community_id required'}), 400

    # Verify user is a member
    membership = CommunityMember.query.filter_by(
        user_id=user_id,
        community_id=community_id,
        status='Active'
    ).first()

    if not membership:
        return jsonify({
            'error': f'You are not a member of community {community_id}'
        }), 403

    # Set in session
    session['selected_community_id'] = community_id
    session.modified = True

    community = Community.query.filter_by(community_id=community_id).first()

    return jsonify({
        'success': True,
        'message': f'Selected community: {community.name if community else community_id}',
        'community_id': community_id,
    }), 200


# ========================================
# Community Creation
# ========================================

@community_bp.route('', methods=['POST'])
@require_auth
def create_community():
    """
    POST /api/communities
    
    Create a new community.
    
    Body:
    {
        "name": "Metro RP",
        "slug": "metro-rp",
        "cad_name": "Metro CAD",
        "logo_url": "https://...",
        "primary_color": "#1a1a1a",
        "secondary_color": "#0066cc"
    }
    """
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Not authenticated'}), 401

    data = request.get_json() or {}

    # Validate input
    required_fields = ['name', 'slug', 'cad_name']
    for field in required_fields:
        if not data.get(field):
            return jsonify({'error': f'{field} is required'}), 400

    name = data['name'].strip()
    slug = data['slug'].strip().lower()
    cad_name = data['cad_name'].strip()

    # Validate slug format
    if not slug or not all(c.isalnum() or c == '-' for c in slug):
        return jsonify({'error': 'Slug must be alphanumeric with hyphens only'}), 400

    # Check slug uniqueness
    existing = Community.query.filter_by(slug=slug).first()
    if existing:
        return jsonify({'error': f'Slug {slug} already taken'}), 409

    # Create community
    try:
        community_id = f'community_{secrets.token_hex(6)}'

        community = Community(
            community_id=community_id,
            name=name,
            slug=slug,
            cad_name=cad_name,
            owner_user_id=user_id,
            logo_url=data.get('logo_url'),
            primary_color=data.get('primary_color', '#1a1a1a'),
            secondary_color=data.get('secondary_color', '#0066cc'),
            status='Active',
        )
        db.session.add(community)
        db.session.commit()

        # Add creator as Owner
        membership = CommunityMember(
            community_id=community_id,
            user_id=user_id,
            role='Owner',
            status='Active',
        )
        db.session.add(membership)
        db.session.commit()

        # Set as selected community
        session['selected_community_id'] = community_id
        session.modified = True

        logger.info(f'✅ Created community {slug} (ID: {community_id}) by user {user_id}')

        return jsonify({
            'success': True,
            'message': 'Community created successfully',
            'community': community.to_dict(),
        }), 201

    except Exception as e:
        db.session.rollback()
        logger.error(f'Error creating community: {e}')
        return jsonify({'error': str(e)}), 500


# ========================================
# Community Details
# ========================================

@community_bp.route('/<community_id>', methods=['GET'])
@require_auth
@community_required
def get_community(community_id):
    """
    GET /api/communities/<community_id>
    
    Get community details.
    """
    community = Community.query.filter_by(community_id=community_id).first()
    if not community:
        return jsonify({'error': 'Community not found'}), 404

    # Check membership
    user_id = session.get('user_id')
    membership = CommunityMember.query.filter_by(
        user_id=user_id,
        community_id=community_id
    ).first()

    is_member = membership is not None
    role = membership.role if membership else None

    return jsonify({
        'success': True,
        'community': community.to_dict(),
        'is_member': is_member,
        'user_role': role,
    }), 200


# ========================================
# Invite System
# ========================================

@community_bp.route('/join', methods=['POST'])
@require_auth
def join_with_invite():
    """
    POST /api/communities/join
    
    Join a community via invite code.
    
    Body:
    {
        "invite_code": "abc123def456"
    }
    """
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Not authenticated'}), 401

    data = request.get_json() or {}
    invite_code = data.get('invite_code', '').strip()

    if not invite_code:
        return jsonify({'error': 'invite_code required'}), 400

    # Find invite
    invite = CommunityInvite.query.filter_by(invite_code=invite_code).first()
    if not invite:
        return jsonify({'error': 'Invalid invite code'}), 404

    # Check if valid
    if not invite.is_valid():
        return jsonify({'error': 'Invite code is no longer valid'}), 410

    community_id = invite.community_id

    # Check if user already a member
    existing = CommunityMember.query.filter_by(
        user_id=user_id,
        community_id=community_id
    ).first()

    if existing:
        return jsonify({
            'error': 'You are already a member of this community'
        }), 409

    # Create membership
    try:
        membership = CommunityMember(
            community_id=community_id,
            user_id=user_id,
            role=invite.role,
            department=invite.department,
            status='Active',
        )
        db.session.add(membership)

        # Increment invite uses
        invite.uses += 1
        if invite.max_uses and invite.uses >= invite.max_uses:
            invite.active = False
        db.session.commit()

        # Set as selected community
        session['selected_community_id'] = community_id
        session.modified = True

        community = Community.query.filter_by(community_id=community_id).first()

        logger.info(
            f'✅ User {user_id} joined community {community_id} via invite'
        )

        return jsonify({
            'success': True,
            'message': f'Joined community: {community.name}',
            'community': community.to_dict(),
            'membership': membership.to_dict(),
        }), 201

    except Exception as e:
        db.session.rollback()
        logger.error(f'Error joining community: {e}')
        return jsonify({'error': str(e)}), 500


# ========================================
# Community Admin Functions
# ========================================

@community_bp.route('/<community_id>/members', methods=['GET'])
@require_auth
@community_member_required
def list_community_members(community_id):
    """
    GET /api/communities/<community_id>/members
    
    List members of a community.
    """
    members = CommunityMember.query.filter_by(
        community_id=community_id,
        status='Active'
    ).all()

    return jsonify({
        'success': True,
        'members': [m.to_dict() for m in members],
        'count': len(members),
    }), 200


@community_bp.route('/<community_id>/invites', methods=['GET'])
@require_auth
@community_admin_required_scoped
def list_community_invites(community_id):
    """
    GET /api/communities/<community_id>/invites
    
    List active invite codes for community (admin only).
    """
    invites = CommunityInvite.query.filter_by(community_id=community_id).all()

    return jsonify({
        'success': True,
        'invites': [i.to_dict() for i in invites],
        'count': len(invites),
    }), 200


@community_bp.route('/<community_id>/invites', methods=['POST'])
@require_auth
@community_admin_required_scoped
def create_invite_code(community_id):
    """
    POST /api/communities/<community_id>/invites
    
    Create a new invite code (admin only).
    
    Body:
    {
        "role": "Civilian",
        "department": "LSPD",
        "max_uses": 5,
        "expires_in_days": 7
    }
    """
    user_id = session.get('user_id')
    data = request.get_json() or {}

    role = data.get('role', 'Civilian')
    department = data.get('department')
    max_uses = data.get('max_uses')
    expires_in_days = data.get('expires_in_days')

    try:
        invite_code = secrets.token_urlsafe(32)

        expires_at = None
        if expires_in_days:
            expires_at = datetime.utcnow() + timedelta(days=expires_in_days)

        invite = CommunityInvite(
            invite_code=invite_code,
            community_id=community_id,
            role=role,
            department=department,
            created_by=user_id,
            expires_at=expires_at,
            max_uses=max_uses,
            uses=0,
            active=True,
        )
        db.session.add(invite)
        db.session.commit()

        logger.info(f'✅ Created invite code for community {community_id}')

        return jsonify({
            'success': True,
            'message': 'Invite code created',
            'invite': invite.to_dict(),
        }), 201

    except Exception as e:
        db.session.rollback()
        logger.error(f'Error creating invite: {e}')
        return jsonify({'error': str(e)}), 500


@community_bp.route('/<community_id>/invites/<invite_code>', methods=['DELETE'])
@require_auth
@community_admin_required_scoped
def revoke_invite_code(community_id, invite_code):
    """
    DELETE /api/communities/<community_id>/invites/<invite_code>
    
    Revoke an invite code (admin only).
    """
    invite = CommunityInvite.query.filter_by(
        community_id=community_id,
        invite_code=invite_code
    ).first()

    if not invite:
        return jsonify({'error': 'Invite not found'}), 404

    try:
        invite.active = False
        db.session.commit()

        logger.info(f'✅ Revoked invite code {invite_code}')

        return jsonify({
            'success': True,
            'message': 'Invite code revoked',
        }), 200

    except Exception as e:
        db.session.rollback()
        logger.error(f'Error revoking invite: {e}')
        return jsonify({'error': str(e)}), 500


# ========================================
# Export
# ========================================

def register_community_routes(app):
    """Register community blueprint with Flask app."""
    app.register_blueprint(community_bp)
    logger.info('✓ Community management routes registered')
