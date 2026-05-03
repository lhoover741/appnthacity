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

// Shared frontend data model
const NThaCityData = {
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

// Data persistence functions
function saveData() {
  localStorage.setItem('NThaCityData', JSON.stringify(NThaCityData));
}

function loadData() {
  const data = localStorage.getItem('NThaCityData');
  if (data) {
    Object.assign(NThaCityData, JSON.parse(data));
  }
}

function generateId(prefix) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
}

// Add record functions
function addCivilian(record) {
  record.id = generateId('civ');
  record.createdAt = new Date().toISOString();
  NThaCityData.civilians.push(record);
  saveData();
  return record;
}

function addVehicle(record) {
  record.id = generateId('veh');
  record.createdAt = new Date().toISOString();
  NThaCityData.vehicles.push(record);
  saveData();
  return record;
}

function addLicense(record) {
  record.id = generateId('lic');
  record.createdAt = new Date().toISOString();
  NThaCityData.licenses.push(record);
  saveData();
  return record;
}

function add911Call(record) {
  record.id = generateId('911');
  record.createdAt = new Date().toISOString();
  NThaCityData.calls911.push(record);
  saveData();
  return record;
}

function addTrafficStop(record) {
  record.id = generateId('stop');
  record.createdAt = new Date().toISOString();
  NThaCityData.trafficStops.push(record);
  saveData();
  return record;
}

function addArrest(record) {
  record.id = generateId('arr');
  record.createdAt = new Date().toISOString();
  NThaCityData.arrests.push(record);
  saveData();
  return record;
}

function addEvidence(record) {
  record.id = generateId('evd');
  record.createdAt = new Date().toISOString();
  NThaCityData.evidence.push(record);
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
  NThaCityData.activityLog.unshift(activity);
  // Keep only the last 50 activities
  if (NThaCityData.activityLog.length > 50) {
    NThaCityData.activityLog = NThaCityData.activityLog.slice(0, 50);
  }
  saveData();
  renderActivityFeed();
}

// Lookup functions
function lookupCivilian(query) {
  if (!query || query.trim() === '') return [];

  const lowerQuery = query.toLowerCase().trim();
  return NThaCityData.civilians.filter(civ =>
    (civ.firstName && civ.firstName.toLowerCase().includes(lowerQuery)) ||
    (civ.lastName && civ.lastName.toLowerCase().includes(lowerQuery)) ||
    (civ.discord && civ.discord.toLowerCase().includes(lowerQuery)) ||
    (civ.id && civ.id.toLowerCase().includes(lowerQuery)) ||
    (civ.phone && civ.phone.includes(query)) ||
    (civ.dob && civ.dob === query)
  );
}

function lookupVehiclePlate(plate) {
  if (!plate || plate.trim() === '') return [];

  const normalizedPlate = normalizePlate(plate);
  return NThaCityData.vehicles.filter(veh =>
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
              <div class="result-value">${result.criminalNotes || 'No known criminal background'}</div>
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

  const activeCalls = NThaCityData.calls911.filter(c => c.status !== 'Closed');

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

  const activities = NThaCityData.activityLog.slice(0, 10);

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

  let warrants = NThaCityData.warrants;

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

  const arrests = NThaCityData.arrests.sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));

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

  const stops = NThaCityData.trafficStops.sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));

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

  const evidence = NThaCityData.evidence.sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));

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

  const html = NThaCityData.officers.map(officer => `
    <div class="officer-card">
      <div class="officer-header">
        <span class="officer-callsign">${officer.id}</span>
        <select class="officer-status-select" onchange="updateOfficerStatus('${officer.id}', this.value)">
          <option value="Available" ${officer.status === 'Available' ? 'selected' : ''}>Available</option>
          <option value="Assigned" ${officer.status === 'Assigned' ? 'selected' : ''}>Assigned</option>
          <option value="En Route" ${officer.status === 'En Route' ? 'selected' : ''}>En Route</option>
          <option value="On Scene" ${officer.status === 'On Scene' ? 'selected' : ''}>On Scene</option>
          <option value="Busy" ${officer.status === 'Busy' ? 'selected' : ''}>Busy</option>
          <option value="Off Duty" ${officer.status === 'Off Duty' ? 'selected' : ''}>Off Duty</option>
        </select>
      </div>
      <div class="officer-role">${officer.name}</div>
      <div class="officer-last-update">Updated: ${formatTime(officer.lastUpdate)}</div>
    </div>
  `).join('');

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
  const call = NThaCityData.calls911.find(c => c.id === callId);
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
  const warrant = NThaCityData.warrants.find(w => w.id === warrantId);
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
function updateOfficerStatus(officerId, newStatus) {
  const officer = NThaCityData.officers.find(o => o.id === officerId);
  if (officer) {
    officer.status = newStatus;
    officer.lastUpdate = new Date().toISOString();
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
    const activeUnits = NThaCityData.officers.filter(o => o.status !== 'Off Duty').length;
    activeUnitsEl.textContent = activeUnits;
  }

  // Pending Calls - calls not closed
  const pendingCallsEl = document.getElementById('pending-calls');
  if (pendingCallsEl) {
    const pendingCalls = NThaCityData.calls911.filter(c => c.status !== 'Closed').length;
    pendingCallsEl.textContent = pendingCalls;
  }

  // Critical Calls - calls with priority Critical
  const criticalCallsEl = document.getElementById('critical-calls');
  if (criticalCallsEl) {
    const criticalCalls = NThaCityData.calls911.filter(c => c.priority === 'Critical' && c.status !== 'Closed').length;
    criticalCallsEl.textContent = criticalCalls;
  }

  // Active Warrants - warrants with status Active
  const activeWarrantsEl = document.getElementById('active-warrants');
  if (activeWarrantsEl) {
    const activeWarrants = NThaCityData.warrants.filter(w => w.status === 'Active').length;
    activeWarrantsEl.textContent = activeWarrants;
  }

  // Recent Arrests - total arrests
  const recentArrestsEl = document.getElementById('recent-arrests');
  if (recentArrestsEl) {
    recentArrestsEl.textContent = NThaCityData.arrests.length;
  }

  // Open Reports - total incidents
  const openReportsEl = document.getElementById('open-reports');
  if (openReportsEl) {
    openReportsEl.textContent = NThaCityData.incidents.length;
  }

  // Evidence Items - total evidence
  const evidenceItemsEl = document.getElementById('evidence-items');
  if (evidenceItemsEl) {
    evidenceItemsEl.textContent = NThaCityData.evidence.length;
  }

  // Traffic Stops - total traffic stops
  const trafficStopsEl = document.getElementById('traffic-stops');
  if (trafficStopsEl) {
    trafficStopsEl.textContent = NThaCityData.trafficStops.length;
  }
}

// Form handlers
function handleCivilianForm() {
  const form = document.getElementById('civilian-form');
  if (!form) return;

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const data = getFormData(form);
    const record = addCivilian(data);
    renderCivilianPreview(record);
    showFormMessage(form, 'Civilian profile registered successfully.');
    form.reset();
  });
}

function handle911Form() {
  const form = document.getElementById('dispatch-form');
  if (!form) return;

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const data = getFormData(form);
    add911Call(data);
    updateDashboard();
    renderCallQueue();
    addActivity('911 Call', `New call created: ${data.incidentType} at ${data.location}`);
    showToast('911 call logged successfully', 'success');
    form.reset();
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

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const data = getFormData(form);
    addArrest(data);
    updateDashboard();
    renderArrestsTable();
    addActivity('Arrest Report', `Arrest filed for ${data.suspectName} - ${data.charges}`);
    showToast('Arrest report filed successfully', 'success');
    form.reset();
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

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const query = form.querySelector('[name="lookupName"]').value;
    const results = lookupCivilian(query);
    renderLookupResults(document.getElementById('civilian-lookup-results'), results, 'civilian');
    addActivity('Civilian Lookup', `Civilian lookup performed for "${query}"`);
    showToast(`Found ${results.length} civilian record(s)`, 'info');
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

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const data = getFormData(form);
    addLicense(data);
    showFormMessage(form, 'License application submitted successfully.');
    form.reset();
  });
}

function handleVehicleForm() {
  const form = document.getElementById('vehicle-form');
  if (!form) return;

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const data = getFormData(form);
    addVehicle(data);
    showFormMessage(form, 'Vehicle registered successfully.');
    form.reset();
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
loadData();
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

// Initialize new components
updateDashboard();
renderCallQueue();
renderActivityFeed();
renderWarrantsTable();
renderArrestsTable();
renderTrafficTable();
renderEvidenceTable();
renderOfficersBoard();

const setActiveNav = () => {
  const links = document.querySelectorAll('.global-nav a');
  const path = window.location.pathname.split('/').pop();
  links.forEach((link) => {
    if (link.getAttribute('href') === path || (path === '' && link.getAttribute('href') === 'index.html')) {
      link.classList.add('active-link');
    }
  });
};

setActiveNav();
