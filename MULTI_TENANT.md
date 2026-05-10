# GTAVCAD Phase 4: Multi-Tenant Architecture

## Overview

GTAVCAD Phase 4 converts the single-community NThaCityRP application into a true multi-tenant RP/CAD platform. Multiple independent communities can operate within a single GTAVCAD deployment while maintaining complete data isolation.

**Platform Rebranding:**
- **Platform**: GTAVCAD (global)
- **Default Community**: NThaCityRP (community instance)
- **Other Communities**: Metro RP, DOJ RP, Blaine County RP, etc.

---

## Key Concepts

### Community (Tenant)
A community is an independent tenant within GTAVCAD. Each community has:
- Unique slug (e.g., `nthacityrp`, `metro-rp`)
- Branding (name, colors, logo)
- Owner and members
- Isolated data (civilians, arrests, dispatch, etc.)
- Community-scoped configuration
- Community-scoped audit logs

### Community Member
Users belong to communities with specific roles:
- **Owner**: Full control over community
- **Admin**: Community administration
- **Police**: Police operations
- **Dispatch**: Dispatch operations
- **Judge**: Court operations
- **DMV**: DMV operations
- **Civilian**: Basic access
- **BusinessOwner**: Business operations

A single user can belong to multiple communities with different roles.

### Tenant-Scoped Data
All operational data is scoped to a community:
- Civilians
- Arrests, Warrants, Incidents
- Dispatch Calls
- DMV Records
- Jail/Court Records
- Audit Logs
- Configuration

### Global Data
Not scoped to communities:
- Users (can belong to multiple communities)
- Communities
- Community Invites

---

## Data Model

### Community
```python
class Community(db.Model):
    community_id      # Unique: e.g., 'nthacityrp', 'community_abc123'
    name              # Display: 'NThaCityRP', 'Metro RP'
    slug              # URL-safe: 'nthacityrp', 'metro-rp' (unique)
    cad_name          # 'NThaCityRP CAD'
    owner_user_id     # User who owns the community
    logo_url
    primary_color     # Hex for branding
    secondary_color   # Hex for branding
    status            # 'Active', 'Inactive', 'Suspended'
    created_at
    updated_at
```

### CommunityMember
```python
class CommunityMember(db.Model):
    community_id      # FK to Community
    user_id           # FK to User
    role              # 'Owner', 'Admin', 'Police', 'Dispatch', etc.
    department        # e.g., 'LSPD', 'Dispatch'
    callsign          # Officer callsign
    status            # 'Active', 'Inactive', 'Suspended'
    joined_at
    updated_at
    
    # Unique constraint: (community_id, user_id)
    # A user can only have one membership per community
```

### CommunityInvite
```python
class CommunityInvite(db.Model):
    invite_code       # Unique: generated token
    community_id      # FK to Community
    role              # Default role for invitees
    department        # Optional pre-assigned department
    created_by        # User who created invite
    expires_at        # Optional: when invite expires
    max_uses          # Optional: max number of uses
    uses              # Current number of uses
    active            # Can be revoked
    created_at
```

### All Tenant-Owned Tables
Tables with `community_id` field (nullable initially, backfilled to 'nthacityrp'):
- Civilian
- Warrant, Arrest, Incident, Evidence
- TrafficStop, Citation
- Call911, DispatchCall
- Inmate, Hearing, JailBooking
- OfficerSession, RadioLog
- Alert, ActivityLog
- Business, Vehicle, License
- Application, Complaint
- UseOfForceReport, OfficerNote, CaseFile
- AIGenerationLog, AuditLog
- KnownAssociate
- Config (special: per-community or global)

---

## API Endpoints

### Community Management

#### List User's Communities
```
GET /api/communities

Response:
{
    "success": true,
    "communities": [
        {
            "community": { "community_id": "...", "name": "...", ... },
            "membership": { "role": "Owner", "department": "...", ... }
        }
    ],
    "current_community_id": "nthacityrp"
}
```

#### Create Community
```
POST /api/communities

Body:
{
    "name": "Metro RP",
    "slug": "metro-rp",           (unique, URL-safe)
    "cad_name": "Metro CAD",
    "logo_url": "https://...",    (optional)
    "primary_color": "#1a1a1a",   (optional)
    "secondary_color": "#0066cc"  (optional)
}

Response: Community object + membership as Owner
```

#### Select Active Community
```
POST /api/communities/select

Body:
{
    "community_id": "nthacityrp"
}

Response:
{
    "success": true,
    "message": "Selected community: NThaCityRP",
    "community_id": "nthacityrp"
}
```

#### Join Community via Invite
```
POST /api/communities/join

Body:
{
    "invite_code": "abc123def456"
}

Response: Community + membership objects
```

#### Get Community Details
```
GET /api/communities/<community_id>

Response:
{
    "success": true,
    "community": { ... },
    "is_member": true,
    "user_role": "Admin"
}
```

#### List Community Members (Member Only)
```
GET /api/communities/<community_id>/members

Response:
{
    "success": true,
    "members": [ { "user_id": ..., "role": "Police", ... } ],
    "count": 5
}
```

#### Create Invite Code (Admin Only)
```
POST /api/communities/<community_id>/invites

Body:
{
    "role": "Civilian",          (optional, default: 'Civilian')
    "department": "LSPD",        (optional)
    "max_uses": 5,               (optional)
    "expires_in_days": 7         (optional)
}

Response:
{
    "success": true,
    "invite": {
        "invite_code": "abc123def456",
        "community_id": "nthacityrp",
        "role": "Civilian",
        "valid": true
    }
}
```

#### List Invite Codes (Admin Only)
```
GET /api/communities/<community_id>/invites

Response:
{
    "success": true,
    "invites": [ { ... } ],
    "count": 3
}
```

#### Revoke Invite Code (Admin Only)
```
DELETE /api/communities/<community_id>/invites/<invite_code>

Response:
{
    "success": true,
    "message": "Invite code revoked"
}
```

---

## Query Scoping Pattern

### ❌ UNSAFE (Cross-Community Data Leak!)
```python
# NEVER do this - returns all communities' data
civilians = Civilian.query.all()
arrests = Arrest.query.filter_by(status='Active').all()
```

### ✅ CORRECT (Tenant-Scoped)
```python
from community_service import get_current_community_id, scope_query_to_community

community_id = get_current_community_id()  # From session or request

# Method 1: Direct filter
civilians = Civilian.query.filter_by(
    community_id=community_id
).all()

# Method 2: Using scope helper
civilians = scope_query_to_community(
    Civilian.query, Civilian, community_id
).all()

# Method 3: In routes with middleware (preferred)
@app.route('/api/civilians')
@require_auth
@community_required
def get_civilians():
    # g.community_id is automatically set by middleware
    civilians = Civilian.query.filter_by(
        community_id=g.community_id
    ).all()
    return jsonify({'civilians': [c.to_dict() for c in civilians]})
```

---

## Write Operations (Creating Records)

### ✅ CORRECT: Backend-Derived Community ID
```python
from flask import g, session

@app.route('/api/civilians', methods=['POST'])
@require_auth
@community_required
def create_civilian():
    data = request.get_json()
    
    # IMPORTANT: Never trust frontend-provided community_id
    # Always derive from authenticated session + community context
    
    civilian = Civilian(
        civilian_id=generate_id('CIV'),
        community_id=g.community_id,  # ← From middleware, not frontend!
        first_name=data['first_name'],
        last_name=data['last_name'],
        # ... other fields
    )
    db.session.add(civilian)
    db.session.commit()
    
    return jsonify({'success': True, 'civilian': civilian.to_dict()}), 201
```

### ❌ DANGEROUS: Trusting Frontend
```python
# NEVER do this
civilian = Civilian(
    community_id=request.json.get('community_id'),  # ← NEVER!
    # User could set this to any community!
)
```

---

## Middleware Integration

### Community Context Middleware
```python
from community_service import community_context_middleware
from flask import g

@app.before_request
def inject_community_context():
    """Called before every request to set up community context."""
    community_context_middleware()

# After this runs:
# g.community_id     = current community ID
# g.community        = Community object
# g.current_user     = User object (if authenticated)
# g.current_membership = CommunityMember (if user is member)
# g.current_role     = User's role in community
# g.user_communities = Dict of user's all memberships
```

### Route Decorators
```python
from community_service import (
    community_required,
    community_member_required,
    community_admin_required,
)
from security_service import (
    community_admin_required_scoped,
    community_police_required_scoped,
    community_member_required_scoped,
)

@app.route('/api/admin/settings', methods=['GET'])
@require_auth
@community_admin_required_scoped
def admin_settings():
    # User must be authenticated, member of community, AND Admin/Owner role
    return jsonify({'settings': {...}})
```

---

## Configuration Management

### Global Config (Null Community ID)
```python
config = Config.query.filter_by(
    key='max_players',
    community_id=None  # Global
).first()
```

### Community-Scoped Config
```python
config = Config.query.filter_by(
    key='server_name',
    community_id='nthacityrp'  # Per-community
).first()

# Each community can have own server name, departments, etc.
```

### Config Lookup Hierarchy
1. Look for community-scoped config: `(key, community_id)`
2. Fall back to global config: `(key, null)`

---

## Migration Strategy

### Phase 4 Bootstrap
Run **once** after deploying this code:

```bash
python bootstrap_multi_tenant.py
```

This script:
1. Creates `Community` table
2. Creates `CommunityMember` table
3. Creates `CommunityInvite` table
4. Creates default community: `nthacityrp`
5. Backfills all existing records with `community_id = 'nthacityrp'`
6. Initializes default config for community

### Backward Compatibility

During transition, enable compatibility mode:

```bash
MULTI_TENANT_ENABLED=false
```

When disabled:
- All queries default to `community_id = 'nthacityrp'`
- Existing code works without modification
- Gradual migration of routes to community-scoped decorators

When enabled:
```bash
MULTI_TENANT_ENABLED=true
```

Strict enforcement:
- All queries must be explicitly scoped
- Multi-tenant routes required

---

## Security Requirements

### Tenant Isolation Checklist

- [ ] All reads filter by `community_id`
- [ ] All writes set `community_id` from backend context (not frontend)
- [ ] RBAC decorators check role + community
- [ ] No global queries across communities
- [ ] User membership validated before access
- [ ] Audit logs include `community_id`
- [ ] Config is per-community where applicable
- [ ] Invite codes cannot be reused across communities
- [ ] Cross-community joins impossible

### Prevent Data Leaks

**Critical Rules:**
1. ❌ Never use `.all()` or query without community filter
2. ❌ Never accept `community_id` from frontend
3. ❌ Never mix data from different communities in responses
4. ❌ Never allow role escalation across communities
5. ✅ Always derive community from `g.community_id`
6. ✅ Always validate user membership first
7. ✅ Always filter by community before returning data

---

## Testing Tenant Isolation

### Create Test Communities

```python
# Community A: Alpha RP
POST /api/communities
{
    "name": "Alpha RP",
    "slug": "alpha-rp",
    "cad_name": "Alpha CAD"
}

# Community B: Metro RP
POST /api/communities
{
    "name": "Metro RP",
    "slug": "metro-rp",
    "cad_name": "Metro CAD"
}
```

### Test Data Isolation

```python
# In Alpha RP:
POST /api/civilians
{
    "first_name": "Alpha",
    "last_name": "Test"
}
# Creates: Civilian with ID=CIV_xxx, community_id='alpha_community_id'

# In Metro RP:
POST /api/civilians
{
    "first_name": "Metro",
    "last_name": "Test"
}
# Creates: Civilian with ID=CIV_yyy, community_id='metro_community_id'

# GET /api/civilians as Alpha admin
# ✓ Should only see "Alpha Test"
# ✗ Should NOT see "Metro Test"

# GET /api/civilians as Metro admin
# ✓ Should only see "Metro Test"
# ✗ Should NOT see "Alpha Test"
```

### Leak Detection

**CRITICAL: If any of these appear, PHASE 4 IS NOT COMPLETE:**

1. Cross-community civilian searches
2. Cross-community arrest records visible
3. Cross-community dispatch calls
4. Cross-community audit logs showing other community's actions
5. DMV records from different communities in same result
6. Config values from other communities
7. Officer sessions from other communities visible

---

## Deployment Checklist

- [ ] Add `community_id` column to all tenant tables
- [ ] Run `bootstrap_multi_tenant.py`
- [ ] Verify default community created
- [ ] Verify all records backfilled
- [ ] Deploy `community_service.py`
- [ ] Deploy `community_routes.py`
- [ ] Update `server.py` to register community routes
- [ ] Add middleware: `@app.before_request`
- [ ] Test community endpoints
- [ ] Manual cross-community isolation test
- [ ] Verify audit logs show community
- [ ] Update frontend to show community context
- [ ] Set `MULTI_TENANT_ENABLED=true` (if ready, or keep false for compatibility)
- [ ] Monitor audit logs for isolation violations

---

## Troubleshooting

### Users See Data From Other Communities
**Problem:** Queries missing community filter
**Fix:** Check query uses `filter_by(community_id=community_id)`

### Cross-Community Joins
**Problem:** Users can join other communities without invite
**Fix:** `can_user_access_community()` check not enforced

### Audit Logs Missing Community
**Problem:** Community field null in audit logs
**Fix:** Always set `audit_log.community_id = g.community_id` at write time

### Invites Reused Across Communities
**Problem:** Same invite code works for multiple communities
**Fix:** Verify unique constraint `(invite_code, community_id)` exists

### Stale Community Context
**Problem:** `g.community_id` incorrect between requests
**Fix:** Middleware runs `community_context_middleware()` before every request

---

## Next Steps

1. **Manual Testing** (ops team)
   - Create test communities
   - Test isolation
   - Verify no data leaks

2. **Gradual Route Migration**
   - Scope queries one endpoint at a time
   - Test after each change
   - Keep deploying to production

3. **Enable Feature Flag**
   - Set `MULTI_TENANT_ENABLED=true` when confident
   - Enforce all new routes are community-scoped

4. **Monitor**
   - Watch audit logs
   - Monitor for isolation violations
   - Alert on suspicious cross-community patterns

5. **New Communities**
   - Marketing/sales onboards new communities
   - Create via `POST /api/communities`
   - Share invite codes with initial admins

---

## Reference: Route Protection Patterns

### Pattern 1: Community-Aware Listing
```python
@app.route('/api/civilians')
@require_auth
@community_required
def list_civilians():
    civilians = Civilian.query.filter_by(
        community_id=g.community_id
    ).all()
    return jsonify({'civilians': [c.to_dict() for c in civilians]})
```

### Pattern 2: Admin-Only Operations
```python
@app.route('/api/community/settings', methods=['PUT'])
@require_auth
@community_admin_required_scoped
def update_community_settings():
    # User is admin in their community
    community = g.community
    # ... update settings
    return jsonify({'success': True})
```

### Pattern 3: Cross-Community Prevention
```python
@app.route('/api/civilians/<civilian_id>', methods=['GET'])
@require_auth
@community_required
def get_civilian(civilian_id):
    civilian = Civilian.query.filter_by(
        civilian_id=civilian_id,
        community_id=g.community_id  # ← Prevents cross-community access!
    ).first()
    
    if not civilian:
        return jsonify({'error': 'Civilian not found'}), 404
    
    return jsonify({'civilian': civilian.to_dict()})
```

---

## Support & Questions

For issues or questions about multi-tenant architecture, see:
- [SECURITY.md](SECURITY.md) - Tenant isolation security model
- [CONFIG.md](CONFIG.md) - Community configuration
- [DEPLOYMENT.md](DEPLOYMENT.md) - Deployment procedures
