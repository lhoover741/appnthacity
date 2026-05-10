"""
GTAVCAD Community Context Service

Handles:
- Community resolution from request context
- Community membership validation
- Community context injection into request
- Query scoping helpers
"""

import logging
from functools import wraps
from flask import request, session, g, abort, jsonify
from models import Community, CommunityMember, User
from platform_config import DEFAULT_COMMUNITY_ID

logger = logging.getLogger(__name__)


# ========================================
# Community Context Extraction
# ========================================

def get_current_community_id():
    """
    Get the current community_id for the request.
    
    Resolution order:
    1. From URL/query tenant slug (explicit /c/<slug>/ context)
    2. From request middleware context
    3. From session['selected_community_id'] for non-tenant APIs
    4. From default (nthacityrp) during compatibility mode
    
    Behind MULTI_TENANT_ENABLED feature flag.
    """
    # 1. Explicit tenant routing/query context must win over an older selected session.
    community_slug = request.args.get('community_slug') or resolve_community_slug_from_path()
    if community_slug:
        community = Community.query.filter_by(slug=community_slug).first()
        if community:
            return community.community_id

    # 2. Use request middleware context when present.
    if hasattr(g, 'community_id') and g.community_id:
        return g.community_id

    # 3. Check session selection for non-tenant API calls.
    if 'selected_community_id' in session:
        return session['selected_community_id']

    # 4. Fallback to the migrated default tenant for legacy API compatibility
    return DEFAULT_COMMUNITY_ID


def resolve_community_slug_from_path():
    """Extract community slug from request path like /c/metro-rp/cad."""
    path_parts = request.path.strip('/').split('/')
    if len(path_parts) >= 2 and path_parts[0] == 'c':
        return path_parts[1]
    return None


def community_context_middleware():
    """
    Middleware to inject current community context into request.
    
    Sets:
    - g.community_id: Current community ID
    - g.user_communities: User's community memberships
    - g.current_user: Current user (if authenticated)
    """
    # Resolve current community
    community_slug = resolve_community_slug_from_path()

    if community_slug:
        # Resolve from URL slug
        community = Community.query.filter_by(slug=community_slug).first()
        if not community:
            abort(404, description=f'Community {community_slug} not found')
        g.community_id = community.community_id
        g.community = community
    elif 'selected_community_id' in session:
        # Use the tenant explicitly selected by the authenticated user.
        g.community_id = session['selected_community_id']
        g.community = Community.query.filter_by(community_id=g.community_id).first()
    else:
        # Global platform pages intentionally have no tenant context.
        g.community_id = None
        g.community = None

    # Validate user membership if authenticated
    user_id = session.get('user_id')
    if user_id:
        user = User.query.get(user_id)
        if user:
            g.current_user = user

            # Get user's memberships
            memberships = CommunityMember.query.filter_by(user_id=user_id).all()
            g.user_communities = {m.community_id: m for m in memberships}

            # Check membership in current community
            current_membership = g.user_communities.get(g.community_id)
            if current_membership:
                g.current_membership = current_membership
                g.current_role = current_membership.role
                g.current_department = current_membership.department
            else:
                # User not a member of this community
                g.current_membership = None
                g.current_role = None
                g.current_department = None
        else:
            g.user_communities = {}
            g.current_user = None


# ========================================
# Community-Scoped Query Helpers
# ========================================

def scope_query_to_community(query_obj, model_class, community_id=None):
    """
    Filter a query to only include records for the specified community.
    
    Usage:
        civilians = scope_query_to_community(
            Civilian.query, Civilian, DEFAULT_COMMUNITY_ID
        ).all()
    """
    if community_id is None:
        community_id = get_current_community_id()

    if not hasattr(model_class, 'community_id'):
        # Model doesn't support community scoping
        logger.warning(f'Model {model_class.__name__} does not have community_id field')
        return query_obj

    return query_obj.filter_by(community_id=community_id)


# ========================================
# Decorators
# ========================================

def community_required(f):
    """Decorator ensuring request has valid community context."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if (not hasattr(g, 'community_id') or not g.community_id) and kwargs.get('community_id'):
            g.community_id = kwargs['community_id']
            g.community = Community.query.filter_by(community_id=g.community_id).first()
        if not hasattr(g, 'community_id') or not g.community_id:
            return jsonify({'error': 'Invalid community context'}), 400
        return f(*args, **kwargs)
    return decorated_function


def community_member_required(f):
    """Decorator ensuring user is a member of current community."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = session.get('user_id')
        target_community_id = kwargs.get('community_id') or getattr(g, 'community_id', None)
        if target_community_id and user_id and (not hasattr(g, 'current_membership') or not g.current_membership):
            membership = CommunityMember.query.filter_by(
                user_id=user_id,
                community_id=target_community_id,
                status='Active'
            ).first()
            if membership:
                g.community_id = target_community_id
                g.current_membership = membership
                g.current_role = membership.role
                g.current_department = membership.department
        if not hasattr(g, 'current_membership') or not g.current_membership:
            return jsonify({'error': 'Not a member of this community'}), 403
        return f(*args, **kwargs)
    return decorated_function


def community_admin_required_scoped(f):
    """Decorator ensuring user is Owner/Admin in the current community."""
    return community_admin_required(f)


def community_admin_required(f):
    """Decorator ensuring user is admin in current community."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = session.get('user_id')
        target_community_id = kwargs.get('community_id') or getattr(g, 'community_id', None)
        if target_community_id and user_id and (not hasattr(g, 'current_role') or not g.current_role):
            membership = CommunityMember.query.filter_by(
                user_id=user_id,
                community_id=target_community_id,
                status='Active'
            ).first()
            if membership:
                g.community_id = target_community_id
                g.current_membership = membership
                g.current_role = membership.role
        if not hasattr(g, 'current_role') or not g.current_role:
            return jsonify({'error': 'No community role'}), 403

        if g.current_role not in ['Owner', 'Admin']:
            return jsonify({'error': 'Admin access required for this community'}), 403

        return f(*args, **kwargs)
    return decorated_function


# ========================================
# Community Helpers
# ========================================

def get_user_communities(user_id):
    """Get all communities a user belongs to."""
    memberships = CommunityMember.query.filter_by(user_id=user_id).all()
    return {m.community_id: m for m in memberships}


def get_community_members(community_id, role=None):
    """Get members of a community, optionally filtered by role."""
    query = CommunityMember.query.filter_by(community_id=community_id, status='Active')
    if role:
        query = query.filter_by(role=role)
    return query.all()


def can_user_access_community(user_id, community_id):
    """Check if user is a member of the community."""
    membership = CommunityMember.query.filter_by(
        user_id=user_id,
        community_id=community_id,
        status='Active'
    ).first()
    return membership is not None


def get_user_role_in_community(user_id, community_id):
    """Get user's role in a specific community."""
    membership = CommunityMember.query.filter_by(
        user_id=user_id,
        community_id=community_id
    ).first()
    return membership.role if membership else None


# ========================================
# Export
# ========================================

__all__ = [
    'get_current_community_id',
    'resolve_community_slug_from_path',
    'community_context_middleware',
    'scope_query_to_community',
    'community_required',
    'community_member_required',
    'community_admin_required',
    'community_admin_required_scoped',
    'get_user_communities',
    'get_community_members',
    'can_user_access_community',
    'get_user_role_in_community',
]
