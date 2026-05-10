
// Frontend security helpers. Use textContent/safe DOM APIs for new code; this
// sanitizer protects legacy innerHTML templates from executing tenant data.
const NATIVE_INNERHTML_DESCRIPTOR = Object.getOwnPropertyDescriptor(Element.prototype, 'innerHTML');


function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function escapeAttr(value) {
  return escapeHtml(value).replace(/`/g, '&#096;');
}

window.escapeHtml = escapeHtml;
window.escapeAttr = escapeAttr;
window.GTAVCAD_CONTEXT = window.GTAVCAD_CONTEXT || {
  platformName: 'GTAVCAD',
  communityName: '',
  communitySlug: '',
  cadName: '',
  role: '',
  department: '',
  inviteCode: '',
  colors: {}
};

function safeText(value) {
  return String(value ?? '');
}

function createSafeElement(tagName, text = '', className = '') {
  const el = document.createElement(tagName);
  if (className) el.className = className;
  el.textContent = safeText(text);
  return el;
}

function sanitizeHTML(html) {
  const template = document.createElement('template');
  NATIVE_INNERHTML_DESCRIPTOR.set.call(template, String(html ?? ''));
  const blockedTags = new Set(['script', 'iframe', 'object', 'embed', 'svg', 'math', 'link', 'meta']);
  const walk = (node) => {
    Array.from(node.childNodes).forEach((child) => {
      if (child.nodeType !== Node.ELEMENT_NODE) return;
      const tag = child.tagName.toLowerCase();
      let unsafe = blockedTags.has(tag);
      Array.from(child.attributes).forEach((attr) => {
        const name = attr.name.toLowerCase();
        const value = String(attr.value || '').trim().toLowerCase();
        if ((name === 'href' || name === 'src' || name === 'xlink:href') && value.startsWith('javascript:')) {
          child.removeAttribute(attr.name);
        }
      });
      if (unsafe) {
        child.remove();
      } else {
        walk(child);
      }
    });
  };
  walk(template.content);
  return template.innerHTML;
}

(function installSafeInnerHTML() {
  const descriptor = NATIVE_INNERHTML_DESCRIPTOR;
  if (!descriptor || !descriptor.set || Element.prototype.__gtavcadSafeInnerHTML) return;
  Object.defineProperty(Element.prototype, 'innerHTML', {
    get: descriptor.get,
    set(value) { descriptor.set.call(this, sanitizeHTML(value)); },
    configurable: true,
    enumerable: descriptor.enumerable,
  });
  Element.prototype.__gtavcadSafeInnerHTML = true;
})();


const PLATFORM_CONTEXT = {
  name: 'GTAVCAD',
  domain: 'gtavcad.app',
  tagline: 'Multi-Community RP/CAD Platform',
  cta: 'Create or Join a Community'
};

function getCommunitySlugFromPath() {
  const parts = window.location.pathname.split('/').filter(Boolean);
  return parts[0] === 'c' && parts[1] ? parts[1] : null;
}

const CURRENT_COMMUNITY_SLUG = getCommunitySlugFromPath();

const OFFICER_CAD_ROLES = ['Owner', 'Admin', 'Police', 'EMS', 'Dispatch', 'DOJ', 'Staff', 'LEO'];
const CAD_ADMIN_BYPASS_ROLES = ['Owner', 'Admin'];

function normalizeRole(role) {
  return String(role || '').trim();
}

function canAccessOfficerCad() {
  return OFFICER_CAD_ROLES.includes(normalizeRole(window.GTAVCAD_CONTEXT?.role));
}

function isCadAdminBypass() {
  return CAD_ADMIN_BYPASS_ROLES.includes(normalizeRole(window.GTAVCAD_CONTEXT?.role));
}

function isOfficerCadPage() {
  const leaf = window.location.pathname.split('/').pop().toLowerCase();
  return leaf === 'police.html' || leaf === 'police' || leaf === 'cad.html' || leaf === 'cad';
}

function enforceCadRoleVisibility() {
  if (!isOfficerCadPage() || !document.body || document.body.dataset.platformPage === 'true') return true;
  const allowed = canAccessOfficerCad();
  document.body.classList.toggle('cad-police-access', allowed);
  document.body.classList.toggle('cad-admin-bypass', isCadAdminBypass());
  if (allowed) return true;
  const overlay = document.getElementById('officer-login-overlay');
  if (overlay) overlay.style.display = 'none';
  const main = document.querySelector('main');
  if (main) {
    main.innerHTML = `
      <section class="container section">
        <div class="card notice-card">
          <h1>Police CAD Restricted</h1>
          <p>Regular civilian accounts can use civilian registry, DMV, businesses, applications, complaints, and public rules. Police CAD tools require Owner, Admin, Police, EMS, Dispatch, DOJ, Staff, or approved LEO access.</p>
          <div class="hero-actions">
            <a class="button button-primary" href="civilian.html">Civilian Registry</a>
            <a class="button button-secondary" href="dmv.html">DMV</a>
            <a class="button button-secondary" href="businesses.html">Businesses</a>
          </div>
        </div>
      </section>`;
  }
  return false;
}

window.canAccessOfficerCad = canAccessOfficerCad;
window.isCadAdminBypass = isCadAdminBypass;
window.enforceCadRoleVisibility = enforceCadRoleVisibility;


if (CURRENT_COMMUNITY_SLUG && window.fetch) {
  const nativeFetch = window.fetch.bind(window);
  window.fetch = (input, init) => {
    let url = typeof input === 'string' ? input : input && input.url;
    if (url && url.startsWith('/api/')) {
      const separator = url.includes('?') ? '&' : '?';
      url = `${url}${separator}community_slug=${encodeURIComponent(CURRENT_COMMUNITY_SLUG)}`;
      if (typeof input === 'string') {
        input = url;
      } else {
        input = new Request(url, input);
      }
    }
    return nativeFetch(input, init);
  };
}

async function applyCommunityBranding() {
  if (!CURRENT_COMMUNITY_SLUG) return null;

  const buildCommunityHref = (target = '') => {
    if (!target || target === '/' || target === 'index' || target === 'index.html') {
      return `/c/${CURRENT_COMMUNITY_SLUG}/`;
    }
    const normalized = target.endsWith('.html') ? target : `${target}.html`;
    return `/c/${CURRENT_COMMUNITY_SLUG}/${normalized}`;
  };

  const communityLinks = document.querySelectorAll('[data-community-link]');
  communityLinks.forEach((link) => {
    const target = link.getAttribute('data-community-link') || '';
    link.href = buildCommunityHref(target);
  });

  const tenantPageMap = {
    '/': '',
    'rules.html': 'rules.html',
    'civilian.html': 'civilian.html',
    'police.html': 'police.html',
    'cad.html': 'cad.html',
    'dmv.html': 'dmv.html',
    'businesses.html': 'businesses.html',
    'applications.html': 'applications.html',
    'complaints.html': 'complaints.html',
    'donations.html': 'donations.html',
    'join.html': 'join.html',
    'index.html': '',
    'rules': 'rules.html',
    'civilian': 'civilian.html',
    'police': 'police.html',
    'cad': 'cad.html',
    'dmv': 'dmv.html',
    'businesses': 'businesses.html',
    'applications': 'applications.html',
    'complaints': 'complaints.html',
    'donations': 'donations.html',
    'join': 'join.html',
  };
  document.querySelectorAll('a[href]').forEach((link) => {
    const href = link.getAttribute('href');
    if (Object.prototype.hasOwnProperty.call(tenantPageMap, href)) {
      link.href = buildCommunityHref(tenantPageMap[href]);
    }
  });

  try {
    const res = await fetch('/api/communities/context');
    const data = await res.json();
    if (!res.ok || !data.success) return null;
    const community = data.community || {};
    const membership = data.membership || null;
    window.GTAVCAD_CONTEXT = {
      platformName: data.platform?.name || PLATFORM_CONTEXT.name,
      communityName: community.name || '',
      communitySlug: community.slug || CURRENT_COMMUNITY_SLUG,
      cadName: community.cad_name || community.name || '',
      role: membership?.role || '',
      department: membership?.department || '',
      inviteCode: data.invite_code || '',
      colors: {
        primary: community.primary_color || '#ff2d2d',
        secondary: community.secondary_color || '#8b0000',
      }
    };

    document.title = `${window.GTAVCAD_CONTEXT.cadName || window.GTAVCAD_CONTEXT.communityName} | ${window.GTAVCAD_CONTEXT.platformName}`;
    document.documentElement.style.setProperty('--accent', window.GTAVCAD_CONTEXT.colors.primary);
    document.documentElement.style.setProperty('--accent-dark', window.GTAVCAD_CONTEXT.colors.secondary);
    document.querySelectorAll('[data-community-name]').forEach((el) => { el.textContent = window.GTAVCAD_CONTEXT.communityName; });
    document.querySelectorAll('[data-community-cad-name]').forEach((el) => { el.textContent = window.GTAVCAD_CONTEXT.cadName; });
    document.querySelectorAll('.brand').forEach((el) => { el.textContent = window.GTAVCAD_CONTEXT.platformName; });
    const loginTitle = document.querySelector('.officer-login-title');
    if (loginTitle) loginTitle.textContent = window.GTAVCAD_CONTEXT.cadName || `${window.GTAVCAD_CONTEXT.platformName} CAD`;

    const pageHeroTitle = document.querySelector('.page-hero h1, header h1');
    if (pageHeroTitle && document.body.dataset.communityPage === 'true' && pageHeroTitle.dataset.keepTitle !== 'true') {
      if (pageHeroTitle.dataset.tenantTitle) {
        pageHeroTitle.textContent = pageHeroTitle.dataset.tenantTitle.replace('{community}', window.GTAVCAD_CONTEXT.communityName).replace('{cad}', window.GTAVCAD_CONTEXT.cadName);
      }
    }

    const communityCtxName = document.querySelector('[data-context-community]');
    if (communityCtxName) communityCtxName.textContent = window.GTAVCAD_CONTEXT.communityName || 'Unknown Community';
    const communityCtxCad = document.querySelector('[data-context-cad]');
    if (communityCtxCad) communityCtxCad.textContent = window.GTAVCAD_CONTEXT.cadName || 'CAD';
    const communityCtxRole = document.querySelector('[data-context-role]');
    if (communityCtxRole) communityCtxRole.textContent = membership ? window.GTAVCAD_CONTEXT.role : 'No membership';
    const communityCtxInvite = document.querySelector('[data-context-invite]');
    if (communityCtxInvite) communityCtxInvite.textContent = window.GTAVCAD_CONTEXT.inviteCode || 'Unavailable';
    document.querySelectorAll('[data-context-department]').forEach((el) => { el.textContent = window.GTAVCAD_CONTEXT.department || '—'; });
    enforceCadRoleVisibility();
    window.dispatchEvent(new CustomEvent('gtavcad:context-ready', { detail: window.GTAVCAD_CONTEXT }));

    document.querySelectorAll('[data-tenant-template]').forEach((el) => {
      const template = el.getAttribute('data-tenant-template') || '';
      el.textContent = template
        .replaceAll('{platform}', window.GTAVCAD_CONTEXT.platformName)
        .replaceAll('{community}', window.GTAVCAD_CONTEXT.communityName)
        .replaceAll('{cad}', window.GTAVCAD_CONTEXT.cadName)
        .replaceAll('{role}', window.GTAVCAD_CONTEXT.role || 'No membership')
        .replaceAll('{invite}', window.GTAVCAD_CONTEXT.inviteCode || 'Unavailable');
    });

    const header = document.querySelector('[data-tenant-header]');
    if (header && !header.querySelector('[data-copy-invite]')) {
      const canManageInvite = ['Owner', 'Admin'].includes(window.GTAVCAD_CONTEXT.role);
      const copyBtn = document.createElement('button');
      copyBtn.type = 'button';
      copyBtn.className = 'button button-ghost';
      copyBtn.dataset.copyInvite = 'true';
      copyBtn.textContent = 'Copy Invite';
      copyBtn.addEventListener('click', async () => {
        await navigator.clipboard.writeText(window.GTAVCAD_CONTEXT.inviteCode || '');
        copyBtn.textContent = 'Invite Copied';
        setTimeout(() => { copyBtn.textContent = 'Copy Invite'; }, 1600);
      });
      header.appendChild(copyBtn);
      if (canManageInvite) {
        const regenBtn = document.createElement('button');
        regenBtn.type = 'button';
        regenBtn.className = 'button button-secondary';
        regenBtn.textContent = 'Regenerate Invite';
        regenBtn.addEventListener('click', async () => {
          regenBtn.disabled = true;
          const regenRes = await fetch('/api/communities/invite', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ regenerate: true }),
          });
          const regenData = await regenRes.json();
          if (regenRes.ok && regenData.success) {
            window.GTAVCAD_CONTEXT.inviteCode = regenData.invite.invite_code;
            if (communityCtxInvite) communityCtxInvite.textContent = window.GTAVCAD_CONTEXT.inviteCode;
          }
          regenBtn.disabled = false;
        });
        header.appendChild(regenBtn);
      }
    }

    if (!membership && document.body.dataset.communityPage === 'true') {
      const target = document.querySelector('[data-tenant-header]') || document.querySelector('main') || document.body;
      if (!document.getElementById('tenant-membership-error')) {
        const error = document.createElement('div');
        error.id = 'tenant-membership-error';
        error.className = 'card';
        error.style.borderColor = 'var(--accent)';
        error.textContent = 'Membership not found for this community. Please join with an invite or ask an Owner/Admin to activate your access.';
        target.insertAdjacentElement(target.matches('main') ? 'afterbegin' : 'afterend', error);
      }
    }

    return community;
  } catch (error) {
    console.warn('Community branding load failed:', error);
    return null;
  }
}

const navToggle = document.querySelector('.nav-toggle');
const navMenu = document.querySelector('.global-nav');
const yearSpan = document.querySelectorAll('.current-year');

if (navToggle && navMenu) {
  navToggle.addEventListener('click', () => {
    navMenu.classList.toggle('show');
  });
}

const currentYear = new Date().getFullYear();
if (yearSpan.length) {
  yearSpan.forEach((node) => {
    node.textContent = currentYear;
  });
}

async function refreshAuthNavigation() {
  const navs = document.querySelectorAll('.global-nav');
  if (!navs.length || !window.fetch) return;
  try {
    const res = await fetch('/api/auth/session');
    if (!res.ok) return;
    const data = await res.json();
    if (!data.success) return;
    document.querySelectorAll('a[href="/login"]').forEach((link) => {
      link.textContent = `Logout (${data.user.username})`;
      link.href = '#logout';
      link.addEventListener('click', async (event) => {
        event.preventDefault();
        await fetch('/api/auth/logout', { method: 'POST' });
        window.location.href = '/login';
      }, { once: true });
    });
  } catch (error) {
    console.warn('Auth navigation refresh failed:', error);
  }
}

refreshAuthNavigation();

// Shared frontend data model
const GTAVCADData = {
  civilians: [],
  vehicles: [],
  licenses: [],
  warrants: [],
  arrests: [],
  incidents: [],
  evidence: [],
  trafficStops: [],
  calls911: [],
  officers: [
    { id: '1L-01', name: 'Chief Unit', status: 'Available', lastUpdate: new Date().toISOString() },
    { id: '2L-12', name: 'Patrol Unit', status: 'En Route', lastUpdate: new Date().toISOString() },
    { id: '3L-22', name: 'Traffic Unit', status: 'On Scene', lastUpdate: new Date().toISOString() },
    { id: 'D-04', name: 'Dispatch', status: 'Active', lastUpdate: new Date().toISOString() },
    { id: 'K9-02', name: 'K9 Unit', status: 'Available', lastUpdate: new Date().toISOString() }
  ],
  activityLog: []
};
const NThaCityData = GTAVCADData;
window.NThaCityData = GTAVCADData;

// Data persistence functions
const CAD_API_URL = '/api/cad';

function saveData() {
  fetch(CAD_API_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(GTAVCADData)
  }).catch((error) => {
    console.warn('CAD save failed:', error);
  });
}

async function loadData() {
  try {
    const res = await fetch(CAD_API_URL);
    if (res.ok) {
      const payload = await res.json();
      const data = payload && payload.data ? payload.data : payload;
      Object.assign(GTAVCADData, data);
      return;
    }
    console.warn('CAD load failed:', res.status);
  } catch (error) {
    console.warn('CAD load failed:', error);
  }
}

function generateId(prefix) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
}

// Add record functions
async function addCivilian(record) {
  const res = await fetch('/api/civilians', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(record),
  });
  const data = await res.json();
  if (!res.ok || !data.success) {
    throw new Error(data.error || 'Civilian save failed');
  }
  if (isOfficerCadPage() && canAccessOfficerCad()) await loadData();
  return data.civilian;
}

// PHASE 1 REPLACEMENT: Use dedicated /api/dmv/vehicles route instead of legacy saveData
async function addVehicle(record) {
  try {
    const payload = {
      plateNumber: record.plateNumber || record.plate,
      vehicleMake: record.vehicleMake || record.make,
      vehicleModel: record.vehicleModel || record.model,
      vehicleColor: record.vehicleColor || record.color,
      insuranceStatus: record.insuranceStatus || 'Valid',
      registrationStatus: record.registrationStatus || 'Valid',
      ownerName: record.ownerName || '',
      notes: record.notes || '',
      ownerCivilianId: record.ownerCivilianId || '',
    };
    
    const res = await fetch('/api/dmv/vehicles', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok || !data.success) {
      throw new Error(data.error || 'Vehicle registration failed');
    }
    // Refresh data from backend after success
    await loadData();
    return data.vehicle;
  } catch (error) {
    console.error('Vehicle registration error:', error);
    throw error;
  }
}

// PHASE 1 REPLACEMENT: Use dedicated /api/dmv/licenses route instead of legacy saveData
async function addLicense(record) {
  try {
    const payload = {
      licenseName: record.licenseName || record.ownerName,
      licenseClass: record.licenseClass || record.licenseType,
      testStatus: record.testStatus || 'Passed',
      licenseExpiration: record.licenseExpiration || record.expiryDate,
      restrictions: record.restrictions || '',
      status: record.status || 'Valid',
    };
    
    const res = await fetch('/api/dmv/licenses', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok || !data.success) {
      throw new Error(data.error || 'License application failed');
    }
    // Refresh data from backend after success
    await loadData();
    return data.license;
  } catch (error) {
    console.error('License application error:', error);
    throw error;
  }
}

// PHASE 1 REPLACEMENT: Use dedicated /api/dispatch/calls route instead of legacy saveData
async function add911Call(record) {
  try {
    const payload = {
      caller_name: record.callerName || record.caller || '',
      location: record.location || '',
      call_type: record.incidentType || record.callType || '',
      description: record.description || '',
      priority: record.priority || 'Medium',
    };
    
    if (!payload.caller_name || !payload.location || !payload.call_type) {
      throw new Error('Missing required fields: caller_name, location, call_type');
    }
    
    const res = await fetch('/api/dispatch/calls', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok || !data.success) {
      throw new Error(data.error || '911 call creation failed');
    }
    // Refresh data from backend after success
    await loadData();
    return data;
  } catch (error) {
    console.error('911 call error:', error);
    throw error;
  }
}

function addTrafficStop(record) {
  record.id = generateId('stop');
  record.createdAt = new Date().toISOString();
  GTAVCADData.trafficStops.push(record);
  saveData();
  return record;
}

async function addArrest(record) {
  const payload = { ...record, id: record.id || generateId('arr') };
  const res = await fetch('/api/cad/arrests', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok || !data.success) {
    throw new Error(data.error || 'Arrest report save failed');
  }
  await loadData();
  return data.arrest;
}

function addEvidence(record) {
  record.id = generateId('evd');
  record.createdAt = new Date().toISOString();
  GTAVCADData.evidence.push(record);
  saveData();
  return record;
}

function addWarrant(record) {
  record.id = generateId('wrn');
  record.createdAt = new Date().toISOString();
  GTAVCADData.warrants.push(record);
  saveData();
  return record;
}

function addIncident(record) {
  record.id = generateId('inc');
  record.createdAt = new Date().toISOString();
  GTAVCADData.incidents.push(record);
  saveData();
  return record;
}

function addActivity(type, message) {
  const activity = {
    id: generateId('act'),
    type: type,
    message: message,
    timestamp: new Date().toISOString()
  };
  GTAVCADData.activityLog.unshift(activity);
  // Keep only the last 50 activities
  if (GTAVCADData.activityLog.length > 50) {
    GTAVCADData.activityLog = GTAVCADData.activityLog.slice(0, 50);
  }
  saveData();
  renderActivityFeed();
}

// Lookup functions
async function lookupCivilian(query) {
  if (!query || query.trim() === '') return [];

  const params = new URLSearchParams({ q: query.trim() });
  const res = await fetch(`/api/civilians?${params.toString()}`);
  const data = await res.json();
  if (!res.ok || !data.success) {
    throw new Error(data.error || 'Civilian lookup failed');
  }
  return data.civilians || [];
}

function lookupVehiclePlate(plate) {
  if (!plate || plate.trim() === '') return [];

  const normalizedPlate = normalizePlate(plate);
  return GTAVCADData.vehicles.filter(veh =>
    normalizePlate(veh.plate) === normalizedPlate ||
    (veh.ownerName && veh.ownerName.toLowerCase().includes(plate.toLowerCase())) ||
    (veh.vehicleMake && veh.vehicleMake.toLowerCase().includes(plate.toLowerCase())) ||
    (veh.vehicleModel && veh.vehicleModel.toLowerCase().includes(plate.toLowerCase()))
  );
}

// Helper functions
function getFormData(form) {
  const data = {};
  const formData = new FormData(form);
  for (let [key, value] of formData.entries()) {
    data[key] = value;
  }
  return data;
}

function normalizePlate(plate) {
  return plate.toUpperCase().replace(/[^A-Z0-9]/g, '');
}

function formatDate(dateString) {
  return new Date(dateString).toLocaleDateString();
}

function showFormMessage(form, message, type = 'success') {
  const status = form.querySelector('.form-status');
  if (status) {
    status.textContent = message;
    status.className = `form-status ${type}`;
  }
}

// Render functions
function renderCivilianPreview(record) {
  const container = document.getElementById('civilian-preview');
  if (!container) return;

  container.innerHTML = `
    <div class="record-preview">
      <h3>Civilian Record Created</h3>
      <div class="record-grid">
        <div><strong>Name:</strong> ${record.firstName} ${record.lastName}</div>
        <div><strong>Civilian ID:</strong> ${record.id}</div>
        <div><strong>DOB:</strong> ${record.dob}</div>
        <div><strong>Phone:</strong> ${record.phone}</div>
        <div><strong>Discord:</strong> ${record.discord}</div>
        <div><strong>Address:</strong> ${record.address}</div>
        <div><strong>Occupation:</strong> ${record.occupation}</div>
        <div><strong>Driver License:</strong> ${record.driverLicense}</div>
        <div><strong>Vehicle:</strong> ${record.vehicleMake} ${record.vehicleModel} (${record.plate})</div>
        <div><strong>Created:</strong> ${formatDate(record.createdAt)}</div>
      </div>
    </div>
  `;
}

function renderLookupResults(container, results, type) {
  if (!container) return;

  if (results.length === 0) {
    container.innerHTML = `<div class="result-card"><div class="empty-state"><div class="empty-icon">🔍</div><h3>No ${type} records found</h3><p>No local records match your search criteria.</p></div></div>`;
    return;
  }

  const html = results.map(result => {
    if (type === 'civilian') {
      return `
        <div class="result-card">
          <div class="result-header">
            <div class="result-title">${result.firstName} ${result.lastName}</div>
            <div class="result-badge badge badge-primary">Civilian ID: ${result.id}</div>
          </div>
          <div class="result-grid">
            <div class="result-field">
              <div class="result-label">Full Name</div>
              <div class="result-value">${result.firstName} ${result.lastName}</div>
            </div>
            <div class="result-field">
              <div class="result-label">Date of Birth</div>
              <div class="result-value">${result.dob}</div>
            </div>
            <div class="result-field">
              <div class="result-label">Discord</div>
              <div class="result-value">${result.discord}</div>
            </div>
            <div class="result-field">
              <div class="result-label">Phone</div>
              <div class="result-value">${result.phone}</div>
            </div>
            <div class="result-field">
              <div class="result-label">Address</div>
              <div class="result-value">${result.address}</div>
            </div>
            <div class="result-field">
              <div class="result-label">Occupation</div>
              <div class="result-value">${result.occupation}</div>
            </div>
            <div class="result-field">
              <div class="result-label">Driver License</div>
              <div class="result-value">${result.driverLicense || 'None'}</div>
            </div>
            <div class="result-field">
              <div class="result-label">Firearm License</div>
              <div class="result-value">${result.firearmLicense || 'None'}</div>
            </div>
            <div class="result-field">
              <div class="result-label">Business License</div>
              <div class="result-value">${result.businessLicense || 'None'}</div>
            </div>
            <div class="result-field">
              <div class="result-label">Vehicle</div>
              <div class="result-value">${result.vehicleMake} ${result.vehicleModel} (${result.plate})</div>
            </div>
            <div class="result-field">
              <div class="result-label">Insurance</div>
              <div class="result-value">${result.insuranceStatus || 'Unknown'}</div>
            </div>
            <div class="result-notes">
              <div class="result-label">Criminal Background</div>
              <div class="result-value">${result.hasCriminalHistory ? 'Criminal record present. See related records below.' : (result.criminalNotes || 'No criminal history on file')}</div>
            </div>
          </div>
        </div>
      `;
    } else if (type === 'vehicle') {
      return `
        <div class="result-card">
          <div class="result-header">
            <div class="result-title">Plate: ${result.plate}</div>
            <div class="result-badge badge badge-primary">Vehicle ID: ${result.id}</div>
          </div>
          <div class="result-grid">
            <div class="result-field">
              <div class="result-label">Make/Model/Year</div>
              <div class="result-value">${result.vehicleMake} ${result.vehicleModel} (${result.vehicleYear})</div>
            </div>
            <div class="result-field">
              <div class="result-label">Color</div>
              <div class="result-value">${result.vehicleColor}</div>
            </div>
            <div class="result-field">
              <div class="result-label">Registered Owner</div>
              <div class="result-value">${result.ownerName}</div>
            </div>
            <div class="result-field">
              <div class="result-label">Civilian ID</div>
              <div class="result-value">${result.civilianId || 'Unknown'}</div>
            </div>
            <div class="result-field">
              <div class="result-label">Insurance Status</div>
              <div class="result-value">${result.insuranceStatus}</div>
            </div>
            <div class="result-field">
              <div class="result-label">Registration Status</div>
              <div class="result-value">${result.registrationStatus}</div>
            </div>
            <div class="result-notes">
              <div class="result-label">Notes/Flags</div>
              <div class="result-value">${result.notes || 'No additional notes'}</div>
            </div>
          </div>
        </div>
      `;
    }
    return '';
  }).join('');

  container.innerHTML = html;
}

// Render call queue
function renderCallQueue() {
  const container = document.getElementById('call-queue');
  if (!container) return;

  const activeCalls = GTAVCADData.calls911.filter(c => c.status !== 'Closed');

  if (activeCalls.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">📞</div>
        <h3>No active calls</h3>
        <p>All emergency calls have been resolved.</p>
      </div>
    `;
    return;
  }

  const html = activeCalls.map(call => {
    const priorityClass = call.priority ? `priority-${call.priority.toLowerCase()}` : 'priority-low';
    const statusClass = call.status ? `status-${call.status.toLowerCase().replace(' ', '-')}` : 'status-new';

    return `
      <div class="call-card">
        <div class="call-header">
          <span class="call-id">${call.id}</span>
          <span class="badge ${priorityClass}">${call.priority || 'Low'}</span>
        </div>
        <div class="call-details">
          <div><strong>Caller:</strong> ${call.callerName}</div>
          <div><strong>Location:</strong> ${call.location}</div>
          <div><strong>Type:</strong> ${call.incidentType}</div>
          <div><strong>Assigned:</strong> ${call.assignedUnit || 'Unassigned'}</div>
          <div><strong>Status:</strong> <span class="badge ${statusClass}">${call.status || 'New'}</span></div>
          <div><strong>Created:</strong> ${formatDate(call.createdAt)}</div>
        </div>
        <div class="call-description">
          ${call.description}
        </div>
        <div class="call-actions">
          <button class="button button-secondary" onclick="updateCallStatus('${call.id}', 'Assigned')">Mark Assigned</button>
          <button class="button button-secondary" onclick="updateCallStatus('${call.id}', 'En Route')">Mark En Route</button>
          <button class="button button-secondary" onclick="updateCallStatus('${call.id}', 'On Scene')">Mark On Scene</button>
          <button class="button button-primary" onclick="updateCallStatus('${call.id}', 'Closed')">Close Call</button>
        </div>
      </div>
    `;
  }).join('');

  container.innerHTML = html;
}

// Render activity feed
function renderActivityFeed() {
  const container = document.getElementById('activity-feed');
  if (!container) return;

  const activities = GTAVCADData.activityLog.slice(0, 10);

  if (activities.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">📋</div>
        <h3>No recent activity</h3>
        <p>System activity will appear here.</p>
      </div>
    `;
    return;
  }

  const html = activities.map(activity => `
    <div class="activity-item">
      <div class="activity-header">
        <span class="activity-type">${activity.type}</span>
        <span class="activity-time">${formatTime(activity.timestamp)}</span>
      </div>
      <div class="activity-message">${activity.message}</div>
    </div>
  `).join('');

  container.innerHTML = html;
}

// Render warrants table
function renderWarrantsTable(filter = 'active') {
  const tbody = document.getElementById('warrants-tbody');
  if (!tbody) return;

  let warrants = GTAVCADData.warrants;

  switch (filter) {
    case 'active':
      warrants = warrants.filter(w => w.status === 'Active');
      break;
    case 'served':
      warrants = warrants.filter(w => w.status === 'Served');
      break;
    case 'expired':
      warrants = warrants.filter(w => w.status === 'Expired');
      break;
    case 'withdrawn':
      warrants = warrants.filter(w => w.status === 'Withdrawn');
      break;
    case 'all':
      // Show all
      break;
  }

  if (warrants.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" class="empty-row">No ${filter} warrants found.</td></tr>`;
    return;
  }

  const html = warrants.map(warrant => `
    <tr>
      <td>${warrant.id}</td>
      <td>${warrant.suspectName}</td>
      <td>${warrant.charges}</td>
      <td>${warrant.issuer}</td>
      <td>${warrant.expiration}</td>
      <td><span class="badge badge-${warrant.status === 'Active' ? 'warning' : 'secondary'}">${warrant.status}</span></td>
      <td>${warrant.notes || 'None'}</td>
      <td class="table-actions">
        ${warrant.status === 'Active' ? `
          <button class="button button-success" onclick="updateWarrantStatus('${warrant.id}', 'Served')">Served</button>
          <button class="button button-warning" onclick="updateWarrantStatus('${warrant.id}', 'Expired')">Expired</button>
          <button class="button button-secondary" onclick="updateWarrantStatus('${warrant.id}', 'Withdrawn')">Withdraw</button>
        ` : warrant.status}
      </td>
    </tr>
  `).join('');

  tbody.innerHTML = html;
}

// Render arrests table
function renderArrestsTable() {
  const tbody = document.getElementById('arrests-tbody');
  if (!tbody) return;

  const arrests = GTAVCADData.arrests.sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));

  if (arrests.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" class="empty-row">No arrest records have been filed locally yet.</td></tr>`;
    return;
  }

  const html = arrests.map(arrest => `
    <tr>
      <td>${arrest.id}</td>
      <td>${arrest.suspectName}</td>
      <td>${arrest.charges}</td>
      <td>${arrest.arrestingOfficer}</td>
      <td>${arrest.location}</td>
      <td>${arrest.penalty}</td>
      <td>${arrest.evidenceAttached}</td>
      <td>${formatDate(arrest.createdAt)}</td>
    </tr>
  `).join('');

  tbody.innerHTML = html;
}

// Render traffic stops table
function renderTrafficTable() {
  const tbody = document.getElementById('traffic-tbody');
  if (!tbody) return;

  const stops = GTAVCADData.trafficStops.sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));

  if (stops.length === 0) {
    tbody.innerHTML = `<tr><td colspan="10" class="empty-row">No traffic stops logged yet.</td></tr>`;
    return;
  }

  const html = stops.map(stop => {
    let outcomeClass = 'badge-secondary';
    if (stop.outcome) {
      switch (stop.outcome.toLowerCase()) {
        case 'warning': outcomeClass = 'badge-warning'; break;
        case 'citation': outcomeClass = 'badge-warning'; break;
        case 'arrest': outcomeClass = 'badge-alert'; break;
        case 'vehicle impounded': outcomeClass = 'badge-warning'; break;
        case 'released': outcomeClass = 'badge-success'; break;
        default: outcomeClass = 'badge-secondary';
      }
    }
    return `
      <tr>
        <td>${stop.id}</td>
        <td>${stop.officerName}</td>
        <td>${stop.driverName}</td>
        <td>${stop.plate}</td>
        <td>${stop.vehicleInfo}</td>
        <td>${stop.location}</td>
        <td>${stop.reason}</td>
        <td><span class="badge ${outcomeClass}">${stop.outcome || 'Unknown'}</span></td>
        <td>${stop.notes || 'None'}</td>
        <td>${formatDate(stop.createdAt)}</td>
      </tr>
    `;
  }).join('');

  tbody.innerHTML = html;
}

// Render evidence table
function renderEvidenceTable() {
  const tbody = document.getElementById('evidence-tbody');
  if (!tbody) return;

  const evidence = GTAVCADData.evidence.sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));

  if (evidence.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" class="empty-row">No evidence submitted yet.</td></tr>`;
    return;
  }

  const html = evidence.map(item => {
    const storageClass = item.storageStatus ? `badge-${item.storageStatus.toLowerCase().replace(' ', '-')}` : 'badge-secondary';
    return `
      <tr>
        <td>${item.id}</td>
        <td>${item.caseNumber}</td>
        <td>${item.officer}</td>
        <td>${item.type}</td>
        <td>${item.description}</td>
        <td>${item.link ? `<a href="${item.link}" target="_blank">View Evidence</a>` : 'None'}</td>
        <td><span class="badge ${storageClass}">${item.storageStatus || 'Unknown'}</span></td>
        <td>${formatDate(item.createdAt)}</td>
      </tr>
    `;
  }).join('');

  tbody.innerHTML = html;
}

// Render officers board
function renderOfficersBoard() {
  const container = document.getElementById('officers-board');
  if (!container) return;

  const html = GTAVCADData.officers.map(officer => {
    const officerId = escapeHtml(officer.id);
    const officerStatus = String(officer.status || '');
    return `
    <div class="officer-card">
      <div class="officer-header">
        <span class="officer-callsign">${officerId}</span>
        <select class="officer-status-select" onchange="updateOfficerStatus('${officerId}', this.value)">
          <option value="Available" ${officerStatus === 'Available' ? 'selected' : ''}>Available</option>
          <option value="Assigned" ${officerStatus === 'Assigned' ? 'selected' : ''}>Assigned</option>
          <option value="En Route" ${officerStatus === 'En Route' ? 'selected' : ''}>En Route</option>
          <option value="On Scene" ${officerStatus === 'On Scene' ? 'selected' : ''}>On Scene</option>
          <option value="Busy" ${officerStatus === 'Busy' ? 'selected' : ''}>Busy</option>
          <option value="On Duty" ${officerStatus === 'On Duty' ? 'selected' : ''}>On Duty</option>
          <option value="Off Duty" ${officerStatus === 'Off Duty' ? 'selected' : ''}>Off Duty</option>
        </select>
      </div>
      <div class="officer-role">${escapeHtml(officer.name)}</div>
      <div class="officer-last-update">Updated: ${escapeHtml(formatTime(officer.lastUpdate))}</div>
    </div>
  `;
  }).join('');

  container.innerHTML = html;
}

// Helper functions
function formatTime(dateString) {
  const date = new Date(dateString);
  const now = new Date();
  const diff = now - date;
  const minutes = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days = Math.floor(diff / 86400000);

  if (minutes < 1) return 'Just now';
  if (minutes < 60) return `${minutes}m ago`;
  if (hours < 24) return `${hours}h ago`;
  return `${days}d ago`;
}

// Update call status
function updateCallStatus(callId, newStatus) {
  const call = GTAVCADData.calls911.find(c => c.id === callId);
  if (call) {
    call.status = newStatus;
    saveData();
    updateDashboard();
    renderCallQueue();
    addActivity('Call Update', `Call ${callId} status changed to ${newStatus}`);
    showToast(`Call ${callId} marked as ${newStatus}`, 'success');
  }
}

// Update warrant status
function updateWarrantStatus(warrantId, newStatus) {
  const warrant = GTAVCADData.warrants.find(w => w.id === warrantId);
  if (warrant) {
    warrant.status = newStatus;
    saveData();
    updateDashboard();
    renderWarrantsTable();
    addActivity('Warrant Update', `Warrant ${warrantId} marked as ${newStatus}`);
    showToast(`Warrant ${warrantId} marked as ${newStatus}`, 'success');
  }
}

// Update officer status
async function updateOfficerStatus(officerId, newStatus) {
  const officer = GTAVCADData.officers.find(o => o.id === officerId);
  if (officer) {
    officer.status = newStatus;
    officer.lastUpdate = new Date().toISOString();
    try {
      await fetch('/api/officer-status', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: officerId,
          status: newStatus,
          name: officer.name || officerId,
          department: officer.department || '',
        }),
      });
    } catch (error) {
      console.warn('Officer status update failed:', error);
    }
    saveData();
    updateDashboard();
    renderOfficersBoard();
    addActivity('Officer Status', `${officerId} status changed to ${newStatus}`);
    showToast(`${officerId} status updated to ${newStatus}`, 'info');
  }
}

// Toast notification system
function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `
    <div class="toast-icon">${getToastIcon(type)}</div>
    <div class="toast-content">
      <div class="toast-title">${getToastTitle(type)}</div>
      <div class="toast-message">${message}</div>
    </div>
    <button class="toast-close" onclick="this.parentElement.remove()">×</button>
  `;

  container.appendChild(toast);

  // Auto remove after 5 seconds
  setTimeout(() => {
    if (toast.parentElement) {
      toast.remove();
    }
  }, 5000);
}

function getToastIcon(type) {
  switch (type) {
    case 'success': return '✓';
    case 'warning': return '⚠';
    case 'error': return '✕';
    case 'info': return 'ℹ';
    default: return 'ℹ';
  }
}

function getToastTitle(type) {
  switch (type) {
    case 'success': return 'Success';
    case 'warning': return 'Warning';
    case 'error': return 'Error';
    case 'info': return 'Info';
    default: return 'Info';
  }
}

// Dashboard update function
function updateDashboard() {
  // Active Units - count officers that are not Off Duty
  const activeUnitsEl = document.getElementById('active-units');
  if (activeUnitsEl) {
    const activeUnits = GTAVCADData.officers.filter(o => o.status !== 'Off Duty').length;
    activeUnitsEl.textContent = activeUnits;
  }

  // Pending Calls - calls not closed
  const pendingCallsEl = document.getElementById('pending-calls');
  if (pendingCallsEl) {
    const pendingCalls = GTAVCADData.calls911.filter(c => c.status !== 'Closed').length;
    pendingCallsEl.textContent = pendingCalls;
  }

  // Critical Calls - calls with priority Critical
  const criticalCallsEl = document.getElementById('critical-calls');
  if (criticalCallsEl) {
    const criticalCalls = GTAVCADData.calls911.filter(c => c.priority === 'Critical' && c.status !== 'Closed').length;
    criticalCallsEl.textContent = criticalCalls;
  }

  // Active Warrants - warrants with status Active
  const activeWarrantsEl = document.getElementById('active-warrants');
  if (activeWarrantsEl) {
    const activeWarrants = GTAVCADData.warrants.filter(w => w.status === 'Active').length;
    activeWarrantsEl.textContent = activeWarrants;
  }

  // Recent Arrests - total arrests
  const recentArrestsEl = document.getElementById('recent-arrests');
  if (recentArrestsEl) {
    recentArrestsEl.textContent = GTAVCADData.arrests.length;
  }

  // Open Reports - total incidents
  const openReportsEl = document.getElementById('open-reports');
  if (openReportsEl) {
    openReportsEl.textContent = GTAVCADData.incidents.length;
  }

  // Evidence Items - total evidence
  const evidenceItemsEl = document.getElementById('evidence-items');
  if (evidenceItemsEl) {
    evidenceItemsEl.textContent = GTAVCADData.evidence.length;
  }

  // Traffic Stops - total traffic stops
  const trafficStopsEl = document.getElementById('traffic-stops');
  if (trafficStopsEl) {
    trafficStopsEl.textContent = GTAVCADData.trafficStops.length;
  }
}

// Form handlers
function handleCivilianForm() {
  const form = document.getElementById('civilian-form');
  if (!form) return;

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const raw = getFormData(form);

    // Send the Civilian Registration form payload to the API; PostgreSQL is the source of truth.
    const payload = { ...raw };

    const submitBtn = form.querySelector('[type="submit"]');
    if (submitBtn) submitBtn.disabled = true;
    showFormMessage(form, 'Saving civilian profile…');

    try {
      const res = await fetch('/api/civilians', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();

      if (res.ok && data.success) {
        const record = data.civilian || { id: data.civilian_id, ...raw };
        renderCivilianPreview({ ...record, discord: raw.discord || '' });
        showFormMessage(form, `✅ Civilian registered — ID: ${data.civilian_id}`);
        showToast(`Civilian saved to database — ID: ${data.civilian_id}`, 'success');
        await loadData();
        form.reset();
      } else {
        showFormMessage(form, `❌ Error: ${data.error || 'Registration failed'}`, 'error');
      }
    } catch (err) {
      showFormMessage(form, `❌ Network error: ${err.message}`, 'error');
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
  });
}

function handle911Form() {
  const form = document.getElementById('dispatch-form');
  if (!form) return;

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const statusEl = document.getElementById('dispatch-status');
    const submitButton = form.querySelector('button[type="submit"]');
    
    try {
      submitButton.disabled = true;
      if (statusEl) {
        statusEl.textContent = 'Creating dispatch call...';
        statusEl.style.color = 'var(--muted)';
        statusEl.style.display = 'block';
      }
      
      const data = getFormData(form);
      await add911Call(data);
      
      updateDashboard();
      renderCallQueue();
      addActivity('911 Call', `New call created: ${data.incidentType} at ${data.location}`);
      showToast('911 call logged successfully', 'success');
      
      if (statusEl) {
        statusEl.textContent = 'Call sent to dispatch successfully!';
        statusEl.style.color = '#4caf50';
      }
      form.reset();
    } catch (error) {
      if (statusEl) {
        statusEl.textContent = `Error: ${error.message}`;
        statusEl.style.color = '#ff6b6b';
        statusEl.style.display = 'block';
      }
      showToast(`911 call failed: ${error.message}`, 'error');
    } finally {
      submitButton.disabled = false;
    }
  });
}

function handleTrafficForm() {
  const form = document.getElementById('traffic-form');
  if (!form) return;

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const data = getFormData(form);
    addTrafficStop(data);
    updateDashboard();
    renderTrafficTable();
    addActivity('Traffic Stop', `Traffic stop logged for ${data.driverName} (${data.plate})`);
    showToast('Traffic stop logged successfully', 'success');
    form.reset();
  });
}

function handleArrestForm() {
  const form = document.getElementById('arrest-form');
  if (!form) return;

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const data = getFormData(form);
    const submitButton = form.querySelector('[type="submit"]');
    if (submitButton) submitButton.disabled = true;
    try {
      const arrest = await addArrest(data);
      updateDashboard();
      renderArrestsTable();
      addActivity('Arrest Report', `Arrest filed for ${arrest.suspectName || data.suspectName} - ${arrest.charges || data.charges}`);
      showToast('Arrest report filed successfully', 'success');
      if (typeof loadCourtHearings === 'function') await loadCourtHearings();
      if (typeof loadJail === 'function') await loadJail();
      const recordInput = document.getElementById('criminal-record-input');
      if (recordInput && recordInput.value.trim()) document.getElementById('criminal-record-btn')?.click();
      form.reset();
    } catch (err) {
      showToast(err.message || 'Arrest report save failed', 'error');
    } finally {
      if (submitButton) submitButton.disabled = false;
    }
  });
}

function handleEvidenceForm() {
  const form = document.getElementById('evidence-form');
  if (!form) return;

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const data = getFormData(form);
    addEvidence(data);
    updateDashboard();
    renderEvidenceTable();
    addActivity('Evidence', `Evidence submitted for case ${data.caseNumber}`);
    showToast('Evidence submitted successfully', 'success');
    form.reset();
  });
}

function handleWarrantForm() {
  const form = document.getElementById('warrant-form');
  if (!form) return;

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const data = getFormData(form);
    addWarrant(data);
    updateDashboard();
    renderWarrantsTable();
    addActivity('Warrant', `Warrant issued for ${data.suspectName} - ${data.charges}`);
    showToast('Warrant added successfully', 'success');
    form.reset();
  });
}

function handleCivilianLookupForm() {
  const form = document.getElementById('civilian-lookup-form');
  if (!form) return;

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const nameQuery = form.querySelector('[name="lookupName"]').value.trim();
    const dobQuery = (form.querySelector('[name="lookupDob"]')?.value || '').trim();
    const licenseQuery = (form.querySelector('[name="lookupLicense"]')?.value || '').trim();
    const query = [nameQuery, licenseQuery].filter(Boolean).join(' ').trim();
    const resultsContainer = document.getElementById('civilian-lookup-results');
    const statusEl = document.getElementById('civilian-lookup-status');

    if ((!query || query.length < 2) && !dobQuery) {
      if (statusEl) { statusEl.textContent = 'Enter at least 2 characters or a DOB to search.'; statusEl.className = 'form-status error'; }
      return;
    }

    if (statusEl) { statusEl.textContent = 'Searching database…'; statusEl.className = 'form-status'; }

    try {
      const res = await fetch('/api/civilian/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, name: nameQuery, dob: dobQuery }),
      });
      const data = await res.json();

      if (data.success) {
        const results = data.results || [];
        const mapped = results.map(r => ({
          id: r.civilian_id || r.id,
          firstName: r.firstName || r.first_name || '',
          lastName: r.lastName || r.last_name || '',
          phone: r.phone || r.phone_number || '',
          address: r.address || '',
          discord: '',
          dob: r.dob || r.date_of_birth || '',
          occupation: r.occupation || '',
          driverLicense: r.driverLicense || r.driver_license_status || '',
          firearmLicense: r.firearmLicense || r.firearm_license_status || '',
          businessLicense: r.businessLicense || r.business_license_status || '',
          vehicleMake: r.vehicleMake || r.vehicle_make || '',
          vehicleModel: r.vehicleModel || r.vehicle_model || '',
          vehicleYear: r.vehicleYear || r.vehicle_year || '',
          vehicleColor: r.vehicleColor || r.vehicle_color || '',
          plate: r.plate || r.plate_number || '',
          insuranceStatus: r.insurance || r.insurance_status || '',
          hasCriminalHistory: Boolean(r.hasCriminalHistory),
          criminalNotes: r.background || r.criminal_background_notes || (r.hasCriminalHistory ? 'Criminal record present. See related records below.' : 'No criminal history on file'),
        }));
        renderLookupResults(resultsContainer, mapped, 'civilian');
        addActivity('Civilian Lookup', `Civilian lookup performed for "${query}"`);
        showToast(`Found ${results.length} civilian record(s)`, 'info');
        if (statusEl) { statusEl.textContent = `Found ${results.length} record(s)`; statusEl.className = 'form-status success'; }
      } else {
        if (resultsContainer) resultsContainer.innerHTML = `<div class="result-card"><p style="color:var(--accent);">${data.error || 'Search failed'}</p></div>`;
        if (statusEl) { statusEl.textContent = data.error || 'Search failed'; statusEl.className = 'form-status error'; }
      }
    } catch (err) {
      if (resultsContainer) resultsContainer.innerHTML = `<div class="result-card"><p style="color:var(--accent);">Network error: ${err.message}</p></div>`;
      if (statusEl) { statusEl.textContent = `Network error: ${err.message}`; statusEl.className = 'form-status error'; }
    }
  });
}

function handlePlateLookupForm() {
  const form = document.getElementById('plate-lookup-form');
  if (!form) return;

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const plate = form.querySelector('[name="plateLookup"]').value;
    const results = lookupVehiclePlate(plate);
    renderLookupResults(document.getElementById('plate-lookup-results'), results, 'vehicle');
    addActivity('Vehicle Lookup', `Vehicle lookup performed for plate "${plate}"`);
    showToast(`Found ${results.length} vehicle record(s)`, 'info');
  });
}

function handleLicenseForm() {
  const form = document.getElementById('license-form');
  if (!form) return;

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const statusEl = document.getElementById('license-status');
    const submitButton = form.querySelector('button[type="submit"]');
    
    try {
      submitButton.disabled = true;
      statusEl.textContent = 'Submitting...';
      statusEl.style.color = 'var(--muted)';
      statusEl.style.display = 'block';
      
      const data = getFormData(form);
      const result = await addLicense(data);
      
      statusEl.textContent = 'License application submitted successfully!';
      statusEl.style.color = '#4caf50';
      showToast('License submitted successfully', 'success');
      form.reset();
    } catch (error) {
      statusEl.textContent = `Error: ${error.message}`;
      statusEl.style.color = '#ff6b6b';
      showToast(`License submission failed: ${error.message}`, 'error');
    } finally {
      submitButton.disabled = false;
    }
  });
}

function handleVehicleForm() {
  const form = document.getElementById('vehicle-form');
  if (!form) return;

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const statusEl = document.getElementById('vehicle-status');
    const submitButton = form.querySelector('button[type="submit"]');
    
    try {
      submitButton.disabled = true;
      statusEl.textContent = 'Submitting...';
      statusEl.style.color = 'var(--muted)';
      statusEl.style.display = 'block';
      
      const data = getFormData(form);
      const result = await addVehicle(data);
      
      statusEl.textContent = 'Vehicle registered successfully!';
      statusEl.style.color = '#4caf50';
      showToast('Vehicle registered successfully', 'success');
      form.reset();
    } catch (error) {
      statusEl.textContent = `Error: ${error.message}`;
      statusEl.style.color = '#ff6b6b';
      showToast(`Vehicle registration failed: ${error.message}`, 'error');
    } finally {
      submitButton.disabled = false;
    }
  });
}

function handleDMVPlateForm() {
  const form = document.getElementById('dmv-plate-form');
  if (!form) return;

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const plate = form.querySelector('[name="plateSearch"]').value;
    const results = lookupVehiclePlate(plate);
    renderLookupResults(document.getElementById('dmv-plate-results'), results, 'vehicle');
    showFormMessage(form, `Found ${results.length} vehicle record(s).`);
  });
}

// PHASE 1: Business persistence via dedicated /api/businesses route
async function createBusiness(record) {
  try {
    const payload = {
      businessName: record.businessName || record.name,
      businessType: record.businessType || record.type,
      licenseStatus: record.licenseStatus || 'Active',
      address: record.desiredLocation || record.address || '',
      ownerCivilianId: record.ownerCivilianId || '',
      employees: parseInt(record.employees) || 0,
      inspectionNotes: record.inspectionNotes || '',
      legalFlags: record.illegalDisclosure || record.legalFlags || '',
    };
    
    const res = await fetch('/api/businesses', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok || !data.success) {
      throw new Error(data.error || 'Business registration failed');
    }
    // Refresh data from backend after success
    await loadData();
    return data.business;
  } catch (error) {
    console.error('Business registration error:', error);
    throw error;
  }
}

function handleBusinessForm() {
  const form = document.getElementById('business-form');
  if (!form) return;

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const statusEl = document.getElementById('business-status');
    const submitButton = form.querySelector('button[type="submit"]');
    
    try {
      submitButton.disabled = true;
      statusEl.textContent = 'Processing business request...';
      statusEl.style.color = 'var(--muted)';
      statusEl.style.display = 'block';
      
      const data = getFormData(form);
      const result = await createBusiness(data);
      
      statusEl.textContent = 'Business request submitted successfully! Staff will review it shortly.';
      statusEl.style.color = '#4caf50';
      showToast('Business request submitted successfully', 'success');
      form.reset();
    } catch (error) {
      statusEl.textContent = `Error: ${error.message}`;
      statusEl.style.color = '#ff6b6b';
      showToast(`Business submission failed: ${error.message}`, 'error');
    } finally {
      submitButton.disabled = false;
    }
  });
}

// Map filter behavior
const filterButtons = document.querySelectorAll('.filter-btn');
const pins = document.querySelectorAll('.map-pin');

filterButtons.forEach((button) => {
  button.addEventListener('click', () => {
    filterButtons.forEach((item) => item.classList.remove('active'));
    button.classList.add('active');
    const filter = button.dataset.filter;

    pins.forEach((pin) => {
      if (filter === 'all') {
        pin.style.display = 'inline-flex';
      } else {
        pin.style.display = pin.dataset.category === filter ? 'inline-flex' : 'none';
      }
    });
  });
});

// Map pin click handlers
pins.forEach((pin) => {
  pin.addEventListener('click', () => {
    const location = pin.dataset.location;
    showMapDetails(location);
  });
});

// Warrant filter handlers
const warrantFilterButtons = document.querySelectorAll('.warrants-panel .filter-btn');
warrantFilterButtons.forEach((button) => {
  button.addEventListener('click', () => {
    warrantFilterButtons.forEach((item) => item.classList.remove('active'));
    button.classList.add('active');
    const filter = button.dataset.filter;
    renderWarrantsTable(filter);
  });
});

// Map details
function showMapDetails(location) {
  const detailsContainer = document.getElementById('map-details');
  if (!detailsContainer) return;

  const locationData = getLocationData(location);
  if (!locationData) return;

  detailsContainer.innerHTML = `
    <div class="location-header">
      <div class="location-name">${locationData.name}</div>
      <div class="location-category badge badge-primary">${locationData.category}</div>
    </div>
    <div class="location-info">
      <div><strong>Purpose:</strong> ${locationData.purpose}</div>
      ${locationData.discord ? `<div class="location-discord">${locationData.discord}</div>` : ''}
    </div>
  `;
}

function getLocationData(location) {
  const locations = {
    'police-dept': {
      name: 'Police Department',
      category: 'Police',
      purpose: 'Officer staging, reports, booking, evidence processing.',
      discord: '#police-evidence-lock-up'
    },
    'dmv': {
      name: 'DMV',
      category: 'Government',
      purpose: 'Vehicle registration, license issuance, and civilian services.',
      discord: '#dmv-services'
    },
    'court': {
      name: 'Court / City Hall',
      category: 'Government',
      purpose: 'Legal proceedings, city administration, and public services.',
      discord: '#court-proceedings'
    },
    'hospital': {
      name: 'Hospital / EMS',
      category: 'Emergency',
      purpose: 'Medical treatment, emergency response, and healthcare services.',
      discord: '#ems-dispatch'
    },
    'dealership': {
      name: 'Dealership',
      category: 'Business',
      purpose: 'Vehicle sales, maintenance, and automotive services.',
      discord: '#business-services'
    },
    'bank': {
      name: 'Bank',
      category: 'Business',
      purpose: 'Financial services, loans, and banking operations.',
      discord: '#business-services'
    },
    'gang-territory': {
      name: 'Gang Territory',
      category: 'Criminal',
      purpose: 'High-crime area requiring increased police presence.',
      discord: '#gang-activity'
    },
    'business-hub': {
      name: 'Business Hub',
      category: 'Business',
      purpose: 'Commercial district with multiple businesses and services.',
      discord: '#business-services'
    },
    'jail': {
      name: 'Jail',
      category: 'Police',
      purpose: 'Detention facility for arrested individuals and prisoner processing.',
      discord: '#jail-processing'
    }
  };

  return locations[location];
}

// Initialize
async function initApp() {
  await applyCommunityBranding();
  if (document.body && document.body.dataset.platformPage === 'true') {
    setActiveNav();
    return;
  }
  if (isOfficerCadPage() && !enforceCadRoleVisibility()) {
    setActiveNav();
    return;
  }
  const shouldLoadCadData = isOfficerCadPage() && canAccessOfficerCad();
  if (shouldLoadCadData) await loadData();
  handleCivilianForm();
  handle911Form();
  handleTrafficForm();
  handleArrestForm();
  handleEvidenceForm();
  handleWarrantForm();
  handleCivilianLookupForm();
  handlePlateLookupForm();
  handleLicenseForm();
  handleVehicleForm();
  handleDMVPlateForm();
  handleBusinessForm();

  // Initialize police CAD components only for authorized officer CAD pages.
  if (shouldLoadCadData) {
    updateDashboard();
    renderCallQueue();
    renderActivityFeed();
    renderWarrantsTable();
    renderArrestsTable();
    renderTrafficTable();
    renderEvidenceTable();
    renderOfficersBoard();
  }

  setActiveNav();
}

const setActiveNav = () => {
  const links = document.querySelectorAll('.global-nav a');
  const path = window.location.pathname;
  const leaf = window.location.pathname.split('/').pop();
  links.forEach((link) => {
    if (link.getAttribute('href') === path || link.getAttribute('href') === leaf || (leaf === '' && link.getAttribute('href') === 'index.html')) {
      link.classList.add('active-link');
    }
  });
};

initApp();

function showCommunityCreatedModal() {
  if (!CURRENT_COMMUNITY_SLUG || !window.sessionStorage) return;
  const rawPayload = sessionStorage.getItem('gtavcadCommunityCreated');
  if (!rawPayload) return;

  let payload;
  try {
    payload = JSON.parse(rawPayload);
  } catch (error) {
    sessionStorage.removeItem('gtavcadCommunityCreated');
    return;
  }

  if (!payload || payload.communitySlug !== CURRENT_COMMUNITY_SLUG) return;
  sessionStorage.removeItem('gtavcadCommunityCreated');

  const overlay = document.createElement('div');
  overlay.className = 'success-modal-overlay';
  overlay.setAttribute('role', 'dialog');
  overlay.setAttribute('aria-modal', 'true');
  overlay.setAttribute('aria-labelledby', 'community-created-title');

  const modal = document.createElement('section');
  modal.className = 'success-modal card';

  const eyebrow = createSafeElement('p', 'Community Created Successfully', 'eyebrow');
  const title = createSafeElement('h2', payload.communityName || 'New Community');
  title.id = 'community-created-title';

  const communityLabel = createSafeElement('p', 'Community:', 'success-modal-label');
  const communityName = createSafeElement('p', payload.communityName || 'Community', 'success-modal-value');
  const inviteLabel = createSafeElement('p', 'Invite Code:', 'success-modal-label');
  const inviteCode = createSafeElement('p', payload.inviteCode || 'Unavailable', 'invite-code-display');

  const actions = document.createElement('div');
  actions.className = 'hero-actions success-modal-actions';

  const enterCad = document.createElement('a');
  enterCad.className = 'button button-primary';
  enterCad.href = payload.redirectUrl || `/c/${CURRENT_COMMUNITY_SLUG}/`;
  enterCad.textContent = 'Enter CAD';

  const copyInvite = document.createElement('button');
  copyInvite.className = 'button button-secondary';
  copyInvite.type = 'button';
  copyInvite.textContent = 'Copy Invite Code';
  copyInvite.addEventListener('click', async () => {
    if (!payload.inviteCode || !navigator.clipboard) return;
    await navigator.clipboard.writeText(payload.inviteCode);
    copyInvite.textContent = 'Invite Code Copied';
  });

  const manage = document.createElement('a');
  manage.className = 'button button-ghost';
  manage.href = `/c/${CURRENT_COMMUNITY_SLUG}/cad`;
  manage.textContent = 'Manage Community';

  const close = document.createElement('button');
  close.className = 'modal-close-button';
  close.type = 'button';
  close.setAttribute('aria-label', 'Close success message');
  close.textContent = '×';
  close.addEventListener('click', () => overlay.remove());

  actions.append(enterCad, copyInvite, manage);
  modal.append(close, eyebrow, title, communityLabel, communityName, inviteLabel, inviteCode, actions);
  overlay.appendChild(modal);
  document.body.appendChild(overlay);
}

showCommunityCreatedModal();

window.GTAVCADData = GTAVCADData;
