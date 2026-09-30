/**
 * Newtonite Operations Coordinator — Premium Frontend v2
 * Vanilla ES6+ with rich animations, counter animations, and polished UX
 */

'use strict';

// =====================================================================
// STATE
// =====================================================================
let currentUser = null;
let allUsers = [];
let allTeams = [];
let currentTab = 'dashboard';
let currentItemDetail = null;
let dashboardPollTimer = null;

// Pagination state
let currentOffset = 0;
const PAGE_SIZE = 15;
let currentFilters = {
  status: '', priority: '', category: '',
  assigned_team: '', assignee_id: '',
  sla_risk_level: '', unassigned_only: false, search: ''
};

// =====================================================================
// INIT
// =====================================================================
document.addEventListener('DOMContentLoaded', async () => {
  await loadUsersAndTeams();
  setupEventListeners();
  switchTab('dashboard');
});

// =====================================================================
// TOAST NOTIFICATIONS — Premium with icons
// =====================================================================
function showToast(message, type = 'success') {
  const container = document.getElementById('toastContainer');
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;

  const icons = { success: '✅', error: '❌', warn: '⚠️', info: 'ℹ️' };
  toast.innerHTML = `
    <span class="toast-icon" aria-hidden="true">${icons[type] || '●'}</span>
    <span class="toast-msg">${escapeHtml(message)}</span>
  `;

  container.appendChild(toast);

  // Auto-dismiss with fade
  setTimeout(() => {
    toast.style.transition = 'all 0.35s ease';
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(110%)';
    setTimeout(() => toast.remove(), 380);
  }, 4200);
}

// =====================================================================
// ANIMATED COUNTER — Smoothly counts up KPI numbers
// =====================================================================
function animateCounter(elementId, targetValue) {
  const el = document.getElementById(elementId);
  if (!el) return;
  const start = parseInt(el.textContent) || 0;
  const target = parseInt(targetValue) || 0;
  if (start === target) return;

  const duration = 600;
  const startTime = performance.now();
  const easeOut = t => 1 - Math.pow(1 - t, 3);

  const tick = (now) => {
    const elapsed = now - startTime;
    const progress = Math.min(elapsed / duration, 1);
    el.textContent = Math.round(start + (target - start) * easeOut(progress));
    if (progress < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

// =====================================================================
// USER & PERSONA SWITCHER
// =====================================================================
async function loadUsersAndTeams() {
  try {
    const [uRes, tRes] = await Promise.all([
      fetch('/api/users'),
      fetch('/api/teams')
    ]);
    allUsers = await uRes.json();
    allTeams = await tRes.json();

    const sel = document.getElementById('personaSelect');
    sel.innerHTML = '';
    allUsers.forEach(u => {
      const opt = document.createElement('option');
      opt.value = u.id;
      opt.textContent = `${u.name} (${u.title})`;
      sel.appendChild(opt);
    });

    const savedId = localStorage.getItem('newtonite_user_id') || 'usr_alice';
    sel.value = savedId;
    await setCurrentUser(savedId);
  } catch (err) {
    console.error('Failed to initialise users/teams:', err);
    showToast('Failed to initialise user directory', 'error');
  }
}

async function setCurrentUser(userId) {
  currentUser = allUsers.find(u => u.id === userId) || allUsers[0];
  if (!currentUser) return;
  localStorage.setItem('newtonite_user_id', currentUser.id);

  document.getElementById('userAvatarInitial').textContent = currentUser.name.charAt(0).toUpperCase();

  const teamsEl = document.getElementById('userTeamsBadges');
  teamsEl.innerHTML = '';
  currentUser.teams.forEach(t => {
    const pill = document.createElement('span');
    pill.className = 'team-pill';
    pill.textContent = t.replace(/_/g, ' ');
    teamsEl.appendChild(pill);
  });

  // Refresh active view
  if (currentTab === 'dashboard') loadDashboard();
  else if (currentTab === 'items') loadWorkItems();
}

// =====================================================================
// TAB SWITCHING
// =====================================================================
function switchTab(tabId) {
  currentTab = tabId;

  // Stop polling when leaving dashboard
  if (dashboardPollTimer && tabId !== 'dashboard') {
    clearInterval(dashboardPollTimer);
    dashboardPollTimer = null;
  }

  document.querySelectorAll('.nav-tab-btn').forEach(btn => {
    const active = btn.dataset.tab === tabId;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-selected', active);
  });

  const tabs = ['dashboard', 'items', 'simulator', 'async'];
  tabs.forEach(t => {
    const el = document.getElementById(t === 'dashboard' ? 'tabDashboard' :
                                       t === 'items'     ? 'tabItems'     :
                                       t === 'simulator' ? 'tabSimulator' :
                                                           'tabAsyncJobs');
    if (el) el.style.display = t === tabId ? 'block' : 'none';
  });

  if (tabId === 'dashboard') loadDashboard();
  if (tabId === 'items')     loadWorkItems();
  if (tabId === 'async')     loadAsyncJobs();
}

// =====================================================================
// API HELPER — injects X-User-Id header automatically
// =====================================================================
async function apiFetch(url, options = {}) {
  options.headers = options.headers || {};
  if (currentUser) options.headers['X-User-Id'] = currentUser.id;
  return fetch(url, options);
}

// =====================================================================
// DASHBOARD
// =====================================================================
async function loadDashboard() {
  try {
    const res = await apiFetch('/api/dashboard');
    if (!res.ok) throw new Error('Dashboard fetch failed');
    const data = await res.json();
    const kpis = data.kpis;

    // Animate KPI counters
    animateCounter('kpiActiveCount',       kpis.total_active           || 0);
    animateCounter('kpiTriageCount',       kpis.triage_count           || 0);
    animateCounter('kpiPendingApprovals',  kpis.pending_approvals_count || 0);
    animateCounter('kpiSlaBreaches',       kpis.sla_breach_count       || 0);
    animateCounter('kpiMyItems',           kpis.my_assigned_count      || 0);

    // Header live count
    const liveCount = document.getElementById('headerLiveCount');
    if (liveCount) {
      liveCount.innerHTML = `<span>${kpis.total_active || 0} Active · ${kpis.sla_breach_count || 0} SLA Breached</span>`;
    }

    // Priority breakdown bar
    renderPriorityBar(kpis.by_priority || {}, kpis.total_active || 1);

    // Queues
    renderQueueList('queueTriageList',    data.queues.triage,    '📭',  'No items in triage queue');
    renderQueueList('queueApprovalsList', data.queues.approvals, '✅',  'No items pending approval');
    renderQueueList('queueSlaList',       data.queues.sla_risks, '🟢',  'No SLA risks detected');
    renderQueueList('queueMyItemsList',   data.queues.my_items,  '👋',  'No items assigned to you');

    // Badge counts
    setQueueBadge('triageBadgeCount',   data.queues.triage?.length    || 0);
    setQueueBadge('approvalsBadgeCount',data.queues.approvals?.length  || 0);
    setQueueBadge('slaBadgeCount',      data.queues.sla_risks?.length  || 0);
    setQueueBadge('myItemsBadgeCount',  data.queues.my_items?.length   || 0);

  } catch (err) {
    console.error(err);
    showToast('Error loading dashboard overview', 'error');
  }
}

function setQueueBadge(id, count) {
  const el = document.getElementById(id);
  if (el) el.textContent = count;
}

function renderPriorityBar(byPriority, totalActive) {
  const bar = document.getElementById('priorityBreakdownBar');
  const labels = document.getElementById('priorityBreakdownLabels');
  if (!bar || !labels) return;

  const segs = bar.querySelectorAll('.priority-bar-segment');
  const priorities = ['P0','P1','P2','P3'];
  const classes = ['pb-p0','pb-p1','pb-p2','pb-p3'];

  let labelHtml = '';
  priorities.forEach((p, i) => {
    const count = byPriority[p] || 0;
    const pct = totalActive > 0 ? Math.max((count / totalActive) * 100, count > 0 ? 3 : 0) : 0;
    if (segs[i]) {
      segs[i].style.width = pct + '%';
      segs[i].title = `${p}: ${count} items`;
    }
    labelHtml += `<span>${p}: <strong>${count}</strong></span>`;
  });
  labels.innerHTML = labelHtml;
}

function renderQueueList(containerId, items, emptyIcon, emptyMessage) {
  const container = document.getElementById(containerId);
  if (!container) return;
  container.innerHTML = '';

  if (!items || items.length === 0) {
    container.innerHTML = `
      <div class="queue-empty">
        <span class="queue-empty-icon">${emptyIcon}</span>
        <span>${emptyMessage}</span>
      </div>`;
    return;
  }

  items.forEach(item => {
    const row = document.createElement('div');
    row.className = 'queue-item-row';
    row.setAttribute('role', 'listitem');
    row.setAttribute('tabindex', '0');
    row.onclick = () => openItemDetail(item.id);
    row.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openItemDetail(item.id); } };

    const prio = prioBadge(item.priority);
    const sla  = slaBadge(item.sla_risk_level);
    const assigneeText = item.assignee_name
      ? `<span>${item.assignee_name}</span>`
      : `<span class="text-cyan" style="font-weight:700;">Unassigned</span>`;

    row.innerHTML = `
      <div class="queue-item-top">
        <div style="display:flex;align-items:center;gap:0.4rem;overflow:hidden;flex:1;">
          ${prio}
          <span class="queue-item-title" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</span>
        </div>
        ${sla}
      </div>
      <div class="queue-item-meta">
        ${statusBadge(item.status)}
        <span>·</span>
        <span title="Team">${escapeHtml(item.assigned_team_name || item.assigned_team)}</span>
        <span>·</span>
        ${assigneeText}
      </div>`;
    container.appendChild(row);
  });
}

// =====================================================================
// WORK ITEMS TABLE
// =====================================================================
async function loadWorkItems() {
  const tbody = document.getElementById('workItemsTableBody');
  if (!tbody) return;

  // Show loading skeletons
  tbody.innerHTML = Array(5).fill(0).map(() => `
    <tr>
      <td><div class="skeleton" style="width:36px;height:18px;border-radius:4px;"></div></td>
      <td><div class="skeleton" style="width:80%;height:14px;border-radius:4px;"></div></td>
      <td><div class="skeleton" style="width:90px;height:14px;border-radius:4px;"></div></td>
      <td><div class="skeleton" style="width:90px;height:18px;border-radius:4px;"></div></td>
      <td><div class="skeleton" style="width:110px;height:14px;border-radius:4px;"></div></td>
      <td><div class="skeleton" style="width:90px;height:14px;border-radius:4px;"></div></td>
      <td><div class="skeleton" style="width:65px;height:18px;border-radius:4px;"></div></td>
    </tr>`).join('');

  try {
    const params = new URLSearchParams();
    params.set('limit', PAGE_SIZE);
    params.set('offset', currentOffset);
    if (currentFilters.status)        params.set('status',        currentFilters.status);
    if (currentFilters.priority)      params.set('priority',      currentFilters.priority);
    if (currentFilters.category)      params.set('category',      currentFilters.category);
    if (currentFilters.assigned_team) params.set('assigned_team', currentFilters.assigned_team);
    if (currentFilters.sla_risk_level)params.set('sla_risk_level',currentFilters.sla_risk_level);
    if (currentFilters.unassigned_only) params.set('unassigned_only','true');
    if (currentFilters.search)        params.set('search',        currentFilters.search);

    const res = await apiFetch(`/api/work-items?${params.toString()}`);
    if (!res.ok) throw new Error('Failed to fetch items');
    const data = await res.json();

    tbody.innerHTML = '';

    if (data.items.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="7">
            <div class="empty-state">
              <span class="empty-state-icon">🔍</span>
              <div class="empty-state-title">No work items found</div>
              <div class="empty-state-desc">Try adjusting filters or search terms</div>
            </div>
          </td>
        </tr>`;
    } else {
      data.items.forEach(item => {
        const tr = document.createElement('tr');
        tr.onclick = () => openItemDetail(item.id);
        tr.setAttribute('tabindex', '0');
        tr.onkeydown = (e) => { if (e.key === 'Enter') openItemDetail(item.id); };
        tr.setAttribute('title', 'Click to open details');

        const avatarLetter = (item.assignee_name || 'U')[0].toUpperCase();
        const assigneeCell = item.assignee_name
          ? `<div class="assignee-cell">
               <div class="user-avatar-sm" title="${escapeHtml(item.assignee_name)}">${avatarLetter}</div>
               <span>${escapeHtml(item.assignee_name)}</span>
             </div>`
          : `<span class="text-cyan" style="font-weight:700;font-size:0.8rem;">Unassigned</span>`;

        const categoryDisplay = item.category.replace(/_/g, ' ')
          .replace(/\b\w/g, l => l.toUpperCase());

        tr.innerHTML = `
          <td>${prioBadge(item.priority)}</td>
          <td class="item-title-cell truncate" style="max-width:320px;" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</td>
          <td style="font-size:0.78rem;color:var(--text-muted);">${categoryDisplay}</td>
          <td>${statusBadge(item.status)}</td>
          <td style="font-size:0.8rem;">${escapeHtml(item.assigned_team_name || item.assigned_team)}</td>
          <td>${assigneeCell}</td>
          <td>${slaBadge(item.sla_risk_level)}</td>`;
        tbody.appendChild(tr);
      });
    }

    // Pagination
    const start = data.total === 0 ? 0 : currentOffset + 1;
    const end   = Math.min(currentOffset + PAGE_SIZE, data.total);
    document.getElementById('paginationInfo').textContent =
      data.total === 0 ? 'No items found' : `Showing ${start}–${end} of ${data.total} items`;

    const prevBtn = document.getElementById('btnPrevPage');
    const nextBtn = document.getElementById('btnNextPage');
    prevBtn.disabled = currentOffset === 0;
    nextBtn.disabled = !data.has_more;

  } catch (err) {
    console.error(err);
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--text-muted);padding:2rem;">Failed to load items. Please try again.</td></tr>`;
    showToast('Failed to load work items', 'error');
  }
}

// =====================================================================
// ITEM DETAIL DRAWER
// =====================================================================
async function openItemDetail(itemId) {
  const modal = document.getElementById('itemDetailModal');
  modal.style.display = 'flex';

  // Show loading state immediately
  document.getElementById('detailTitle').textContent = 'Loading…';
  document.getElementById('detailDescription').textContent = '';
  document.getElementById('nextActionsContainer').innerHTML = '<span style="color:var(--text-muted);font-size:0.85rem;">Loading actions…</span>';
  document.getElementById('auditTimelineList').innerHTML = '';

  try {
    const res = await apiFetch(`/api/work-items/${itemId}`);
    if (!res.ok) throw new Error('Failed to load item');
    const item = await res.json();
    currentItemDetail = item;

    // Header meta row
    document.getElementById('detailHeaderMeta').innerHTML =
      `${prioBadge(item.priority)} ${statusBadge(item.status)} <span style="font-size:0.72rem;color:var(--text-muted);font-weight:600;text-transform:uppercase;letter-spacing:0.05em;">${item.category.replace(/_/g,' ')}</span>`;

    document.getElementById('detailTitle').textContent = item.title;
    document.getElementById('detailDescription').textContent = item.description;

    // Meta grid
    document.getElementById('detailStatus').innerHTML   = statusBadge(item.status);
    document.getElementById('detailPriority').innerHTML = prioBadge(item.priority);
    document.getElementById('detailTeam').textContent   = item.assigned_team_name || item.assigned_team;
    document.getElementById('detailAssignee').innerHTML = item.assignee_name
      ? `<div class="assignee-cell" style="gap:0.35rem;">
           <div class="user-avatar-sm">${item.assignee_name[0].toUpperCase()}</div>
           <span>${escapeHtml(item.assignee_name)}</span>
         </div>`
      : `<span class="text-cyan" style="font-weight:700;">Unassigned</span>`;
    document.getElementById('detailVersion').textContent = `v${item.version}`;
    document.getElementById('detailCreated').textContent = formatDateRelative(item.created_at);
    document.getElementById('detailSla').innerHTML = `
      ${item.target_sla_minutes} min ${slaBadge(item.sla_risk_level)}`;

    renderNextActions(item);
    renderAuditTimeline(item.events || []);

    document.getElementById('newCommentInput').value = '';
    document.getElementById('newCommentInput').focus();

  } catch (err) {
    console.error(err);
    showToast('Failed to load work item details', 'error');
    modal.style.display = 'none';
  }
}

function renderNextActions(item) {
  const container = document.getElementById('nextActionsContainer');
  container.innerHTML = '';
  const actions = item.next_required_actions || [];

  if (actions.length === 0) {
    container.innerHTML = '<span style="color:var(--text-muted);font-size:0.85rem;">No immediate actions for this state.</span>';
    return;
  }

  actions.forEach(action => {
    const btn = document.createElement('button');
    btn.dataset.actionType = action.action_type;

    if (!action.permitted_for_viewer) {
      btn.className = 'btn btn-secondary';
      btn.disabled = true;
      btn.title = `Restricted to: ${action.allowed_roles_or_teams.join(', ')}`;
      btn.innerHTML = `🔒 ${escapeHtml(action.label)} <span style="font-size:0.68rem;opacity:0.6;">(Restricted)</span>`;
    } else {
      const actionMap = {
        'APPROVE':         { cls: 'btn-success',   fn: () => promptApproval(item.id, item.version, true)  },
        'REJECT':          { cls: 'btn-danger',    fn: () => promptApproval(item.id, item.version, false) },
        'CLAIM':           { cls: 'btn-primary',   fn: () => executeClaim(item.id, item.version)          },
        'RESOLVE':         { cls: 'btn-success',   fn: () => promptResolution(item.id, item.version)      },
        'INVESTIGATE':     { cls: 'btn-secondary', fn: () => executeTransition(item.id, item.version, 'IN_INVESTIGATION', 'Investigating root cause') },
        'REQUEST_APPROVAL':{ cls: 'btn-secondary', fn: () => executeTransition(item.id, item.version, 'PENDING_APPROVAL', 'Escalated for approval') },
        'BLOCK':           { cls: 'btn-danger',    fn: () => executeTransition(item.id, item.version, 'BLOCKED', 'External blocker encountered') },
        'UNBLOCK':         { cls: 'btn-primary',   fn: () => executeTransition(item.id, item.version, 'IN_PROGRESS', 'External blocker cleared') },
      };
      const mapped = actionMap[action.action_type] || { cls: 'btn-secondary', fn: null };
      btn.className = `btn ${mapped.cls}`;
      if (mapped.fn) btn.onclick = mapped.fn;
      btn.textContent = action.label;
      btn.title = action.description;
    }

    container.appendChild(btn);
  });
}

function renderAuditTimeline(events) {
  const container = document.getElementById('auditTimelineList');
  container.innerHTML = '';

  if (events.length === 0) {
    container.innerHTML = '<span style="color:var(--text-muted);font-size:0.8rem;">No events recorded yet.</span>';
    return;
  }

  events.forEach(ev => {
    const item = document.createElement('div');
    item.className = 'timeline-item';
    item.setAttribute('role', 'listitem');

    const typeConfig = {
      'CREATED':           { icon: '✨', cls: 'dot-created'  },
      'CLAIMED':           { icon: '✋', cls: 'dot-claimed'  },
      'APPROVED':          { icon: '✅', cls: 'dot-approved' },
      'REJECTED':          { icon: '❌', cls: 'dot-rejected' },
      'STATUS_CHANGED':    { icon: '🔄', cls: 'dot-changed'  },
      'ENRICHED':          { icon: '⚡', cls: 'dot-changed'  },
      'COMMENT_ADDED':     { icon: '💬', cls: 'dot-comment'  },
      'NOTIFICATION_SENT': { icon: '📨', cls: 'dot-comment'  },
    };
    const cfg = typeConfig[ev.event_type] || { icon: '📝', cls: '' };

    let detailHtml = '';
    if (ev.from_state && ev.to_state) {
      detailHtml = `<span style="color:var(--text-muted);">${ev.from_state}</span> → <span class="text-cyan">${ev.to_state}</span>`;
    }
    if (ev.details) {
      if (ev.details.comment)          detailHtml += `<em>"${escapeHtml(ev.details.comment)}"</em>`;
      if (ev.details.reason)           detailHtml += ` <span style="color:var(--text-muted);">(${escapeHtml(ev.details.reason)})</span>`;
      if (ev.details.decision_notes)   detailHtml += ` Decision: ${escapeHtml(ev.details.decision_notes)}`;
      if (ev.details.resolution_notes) detailHtml += ` Resolution: ${escapeHtml(ev.details.resolution_notes)}`;
      if (ev.details.sla_risk_level)   detailHtml += ` SLA Risk: <strong>${ev.details.sla_risk_level}</strong> (${ev.details.elapsed_minutes}min elapsed)`;
    }

    item.innerHTML = `
      <div class="timeline-dot ${cfg.cls}" aria-hidden="true">${cfg.icon}</div>
      <div class="timeline-content">
        <div class="timeline-top">
          <span class="timeline-actor">${escapeHtml(ev.actor_name)}</span>
          <div style="display:flex;align-items:center;gap:0.5rem;">
            <span class="timeline-event-type">${ev.event_type}</span>
            <span class="timeline-time">${formatDateRelative(ev.created_at)}</span>
          </div>
        </div>
        <div class="timeline-details">${detailHtml}</div>
      </div>`;
    container.appendChild(item);
  });
}

// =====================================================================
// ACTIONS: CLAIM, TRANSITION, APPROVAL, COMMENT
// =====================================================================
async function executeClaim(itemId, expectedVersion) {
  try {
    const res = await apiFetch(`/api/work-items/${itemId}/claim`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expected_version: expectedVersion })
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail?.message || JSON.stringify(err.detail) || 'Claim failed');
    }
    showToast('Work item claimed successfully!', 'success');
    openItemDetail(itemId);
    if (currentTab === 'dashboard') loadDashboard();
    if (currentTab === 'items') loadWorkItems();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function executeTransition(itemId, expectedVersion, targetStatus, reason, resolutionNotes = null) {
  try {
    const res = await apiFetch(`/api/work-items/${itemId}/transition`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expected_version: expectedVersion, target_status: targetStatus, reason, resolution_notes: resolutionNotes })
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail?.message || JSON.stringify(err.detail) || 'Transition failed');
    }
    showToast(`Status updated → ${targetStatus}`, 'success');
    openItemDetail(itemId);
    if (currentTab === 'dashboard') loadDashboard();
    if (currentTab === 'items') loadWorkItems();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

function promptResolution(itemId, expectedVersion) {
  const notes = prompt('Mandatory resolution notes (min 5 characters):');
  if (notes === null) return;
  if (notes.trim().length < 5) {
    alert('Resolution notes must be at least 5 characters.');
    return;
  }
  executeTransition(itemId, expectedVersion, 'RESOLVED', 'Issue resolved and verified', notes.trim());
}

function promptApproval(itemId, expectedVersion, approved) {
  const action = approved ? 'approve' : 'reject';
  const notes = prompt(`Enter formal decision notes to ${action} this request:`);
  if (notes === null) return;
  if (notes.trim().length < 2) { alert('Decision notes are required.'); return; }
  executeApproval(itemId, expectedVersion, approved, notes.trim());
}

async function executeApproval(itemId, expectedVersion, approved, notes) {
  try {
    const res = await apiFetch(`/api/work-items/${itemId}/approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expected_version: expectedVersion, approved, notes })
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail?.message || JSON.stringify(err.detail) || 'Approval failed');
    }
    showToast(`Request ${approved ? 'approved ✅' : 'rejected ❌'} successfully`, approved ? 'success' : 'warn');
    openItemDetail(itemId);
    if (currentTab === 'dashboard') loadDashboard();
    if (currentTab === 'items') loadWorkItems();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function addCommentToCurrentItem() {
  const input = document.getElementById('newCommentInput');
  const comment = input.value.trim();
  if (!comment || !currentItemDetail) return;

  try {
    const res = await apiFetch(`/api/work-items/${currentItemDetail.id}/comments`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ comment })
    });
    if (!res.ok) throw new Error('Failed to post comment');
    input.value = '';
    showToast('Comment added to audit trail', 'success');
    openItemDetail(currentItemDetail.id);
  } catch (err) {
    showToast(err.message, 'error');
  }
}

// =====================================================================
// SIMULATOR — Critical Behaviors Test Bench
// =====================================================================
function simLog(msg, style = '') {
  const box = document.getElementById('simResultBox');
  box.innerHTML += `<span style="${style}">${msg}\n</span>`;
  box.scrollTop = box.scrollHeight;
}

function simClear(heading) {
  const box = document.getElementById('simResultBox');
  box.innerHTML = `<span class="sim-info">// ${heading}\n\n</span>`;
}

async function simulateRaceConditionClaim() {
  simClear('TEST 1 — Concurrent Race Condition Claim Prevention');

  try {
    const initRes = await fetch('/api/work-items/wi_p0_unassigned_gateway');
    const init = await initRes.json();
    simLog(`Target Item : ${init.id}`, 'color:#94a3b8');
    simLog(`Assignee    : ${init.assignee_id || 'None (Unassigned)'}`, 'color:#94a3b8');
    simLog(`Version     : v${init.version}`, 'color:#94a3b8');
    simLog('');
    simLog('Dispatching 2 concurrent claim requests simultaneously…', 'color:#a78bfa');
    simLog('  Worker 1 → Bob Martinez  (incident_response)');
    simLog('  Worker 2 → Eve Adams     (incident_response + ops_admin)');
    simLog('');

    const [r1, r2] = await Promise.all([
      fetch('/api/work-items/wi_p0_unassigned_gateway/claim', {
        method: 'POST',
        headers: { 'X-User-Id': 'usr_bob', 'Content-Type': 'application/json' },
        body: JSON.stringify({ expected_version: init.version })
      }),
      fetch('/api/work-items/wi_p0_unassigned_gateway/claim', {
        method: 'POST',
        headers: { 'X-User-Id': 'usr_eve', 'Content-Type': 'application/json' },
        body: JSON.stringify({ expected_version: init.version })
      })
    ]);

    const d1 = await r1.json();
    const d2 = await r2.json();

    simLog(`Worker 1 → HTTP ${r1.status}`, r1.status === 200 ? 'color:#34d399' : 'color:#ff4757');
    if (r1.status === 200) simLog(`           Claimed by: ${d1.assignee_name}`, 'color:#34d399');
    if (r1.status === 409) simLog(`           ${d1.detail?.message || JSON.stringify(d1.detail)}`, 'color:#ff4757');

    simLog(`Worker 2 → HTTP ${r2.status}`, r2.status === 200 ? 'color:#34d399' : 'color:#ff4757');
    if (r2.status === 200) simLog(`           Claimed by: ${d2.assignee_name}`, 'color:#34d399');
    if (r2.status === 409) simLog(`           ${d2.detail?.message || JSON.stringify(d2.detail)}`, 'color:#ff4757');

    const statuses = [r1.status, r2.status].sort();
    simLog('');
    if (statuses[0] === 200 && statuses[1] === 409) {
      simLog('✅ PASS  Race condition prevented — exactly 1 claim succeeded, 1 received 409 Conflict.', 'color:#34d399;font-weight:700;');
    } else {
      simLog(`⚠️  Unexpected statuses: ${statuses.join(', ')}`, 'color:#f0c020');
    }
  } catch (err) {
    simLog(`❌ Error: ${err.message}`, 'color:#ff4757');
  }
}

async function simulateStaleOCCUpdate() {
  simClear('TEST 2 — Optimistic Concurrency Control (Stale Version Rejection)');

  try {
    const r = await fetch('/api/work-items/wi_p2_csv_export');
    const item = await r.json();

    simLog(`Current database version : v${item.version}`, 'color:#94a3b8');
    simLog(`Sending mutation with    : v${item.version - 1} (intentionally stale)`, 'color:#a78bfa');
    simLog('');

    const res = await fetch('/api/work-items/wi_p2_csv_export/transition', {
      method: 'POST',
      headers: { 'X-User-Id': 'usr_alice', 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expected_version: item.version - 1,
        target_status: 'IN_INVESTIGATION',
        reason: 'Simulated stale overwrite attempt'
      })
    });
    const body = await res.json();

    simLog(`Server Response : HTTP ${res.status}`, res.status === 409 ? 'color:#34d399' : 'color:#ff4757');
    simLog(JSON.stringify(body.detail || body, null, 2), 'color:#94a3b8');
    simLog('');
    if (res.status === 409) {
      simLog('✅ PASS  Server rejected stale mutation — silent data overwrite prevented.', 'color:#34d399;font-weight:700;');
    }
  } catch (err) {
    simLog(`❌ Error: ${err.message}`, 'color:#ff4757');
  }
}

async function simulateIdempotencyReplay() {
  simClear('TEST 3 — Idempotency-Key Network Retry Deduplication');

  const testKey = 'sim_idem_' + Math.random().toString(36).substring(2, 10);
  const payload = {
    title: 'Idempotency Test ' + Date.now(),
    description: 'Verifying idempotent execution and replay caching.',
    category: 'operational_task',
    priority: 'P2',
    assigned_team: 'tier1_support'
  };

  simLog(`Generated Idempotency-Key : ${testKey}`, 'color:#a78bfa');
  simLog('');

  simLog('[Request 1 — Initial submission]', 'color:#94a3b8');
  const r1 = await fetch('/api/work-items', {
    method: 'POST',
    headers: { 'X-User-Id': 'usr_alice', 'Idempotency-Key': testKey, 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  const b1 = await r1.json();
  simLog(`  Status          : HTTP ${r1.status}`, 'color:#34d399');
  simLog(`  X-Idempotency-Replay : ${r1.headers.get('X-Idempotency-Replay') || 'None (first call)'}`, 'color:#94a3b8');
  simLog(`  Created Item ID : ${b1.id}`, 'color:#38bdf8');
  simLog('');

  simLog('[Request 2 — Network retry with same Idempotency-Key]', 'color:#94a3b8');
  const r2 = await fetch('/api/work-items', {
    method: 'POST',
    headers: { 'X-User-Id': 'usr_alice', 'Idempotency-Key': testKey, 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  const b2 = await r2.json();
  simLog(`  Status          : HTTP ${r2.status}`, 'color:#34d399');
  simLog(`  X-Idempotency-Replay : ${r2.headers.get('X-Idempotency-Replay') || 'None'}`, 'color:#38bdf8');
  simLog(`  Returned Item ID : ${b2.id}`, 'color:#94a3b8');
  simLog(`  IDs identical    : ${b1.id === b2.id}`, b1.id === b2.id ? 'color:#34d399' : 'color:#ff4757');
  simLog('');

  if (r2.headers.get('X-Idempotency-Replay') === 'true' && b1.id === b2.id) {
    simLog('✅ PASS  Server recognised duplicate key and replayed cached receipt — no duplicate item created.', 'color:#34d399;font-weight:700;');
  }
}

async function simulateCrossTeamUnauthorized() {
  simClear('TEST 4 — Server-Enforced RBAC Cross-Team Claim Rejection');

  simLog('User   : Alice Chen  (teams: [tier1_support])', 'color:#94a3b8');
  simLog('Target : wi_p0_unassigned_gateway  (assigned_team: incident_response)', 'color:#94a3b8');
  simLog('Action : Attempting claim via direct API call (bypassing UI)…', 'color:#a78bfa');
  simLog('');

  const res = await fetch('/api/work-items/wi_p0_unassigned_gateway/claim', {
    method: 'POST',
    headers: { 'X-User-Id': 'usr_alice', 'Content-Type': 'application/json' },
    body: JSON.stringify({ expected_version: 1 })
  });
  const body = await res.json();

  simLog(`Server Response : HTTP ${res.status}`, res.status === 403 ? 'color:#34d399' : 'color:#ff4757');
  simLog(JSON.stringify(body, null, 2), 'color:#94a3b8');
  simLog('');
  if (res.status === 403) {
    simLog('✅ PASS  Server-side RBAC returned 403 Forbidden — authorization is NOT solely relying on UI controls.', 'color:#34d399;font-weight:700;');
  }
}

// =====================================================================
// ASYNC JOBS INSPECTOR
// =====================================================================
async function loadAsyncJobs() {
  const tbody = document.getElementById('asyncJobsTableBody');
  if (!tbody) return;

  tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;padding:1.5rem;color:var(--text-muted);">Loading jobs…</td></tr>`;

  try {
    const res = await apiFetch('/api/async-jobs');
    const jobs = await res.json();
    tbody.innerHTML = '';

    if (jobs.length === 0) {
      tbody.innerHTML = `
        <tr><td colspan="7">
          <div class="empty-state" style="padding:2rem;">
            <span class="empty-state-icon">⚙️</span>
            <div class="empty-state-title">No background jobs</div>
          </div>
        </td></tr>`;
      return;
    }

    jobs.forEach(j => {
      const tr = document.createElement('tr');
      const statusClass = {
        PENDING: 'job-pending', PROCESSING: 'job-processing',
        COMPLETED: 'job-completed', DEAD_LETTER: 'job-dead', RETRYING: 'job-retrying'
      }[j.status] || '';

      tr.innerHTML = `
        <td class="font-mono" style="font-size:0.72rem;color:var(--text-muted);">${j.id}</td>
        <td><strong>${j.job_type}</strong></td>
        <td>
          <a href="#" onclick="openItemDetail('${j.work_item_id}'); return false;"
             style="color:var(--cyan);text-decoration:none;font-family:var(--font-mono);font-size:0.78rem;"
             title="Open work item">${j.work_item_id}</a>
        </td>
        <td><span class="job-status-badge ${statusClass}">${j.status}</span></td>
        <td style="font-variant-numeric:tabular-nums;color:${j.attempts >= j.max_attempts ? 'var(--p0)' : 'var(--text-secondary)'};">
          ${j.attempts} / ${j.max_attempts}
        </td>
        <td style="font-size:0.75rem;color:var(--text-muted);font-variant-numeric:tabular-nums;">${formatDateRelative(j.run_at)}</td>
        <td style="font-size:0.72rem;color:var(--p0);max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${escapeHtml(j.last_error || '')}">
          ${j.last_error ? escapeHtml(j.last_error.substring(0, 80)) + (j.last_error.length > 80 ? '…' : '') : '—'}
        </td>`;
      tbody.appendChild(tr);
    });
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;padding:1.5rem;color:var(--p0);">Failed to load jobs</td></tr>`;
    showToast('Failed to load async jobs', 'error');
  }
}

async function triggerDueAsyncJobs() {
  const btn = document.getElementById('btnRunJobs');
  if (btn) { btn.disabled = true; btn.textContent = 'Running…'; }
  try {
    const res = await apiFetch('/api/async-jobs/run-pending', { method: 'POST' });
    const data = await res.json();
    showToast(data.message, 'success');
    loadAsyncJobs();
  } catch (err) {
    showToast('Failed to trigger background jobs', 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '<span>▶</span> Run Due Jobs Now'; }
  }
}

// =====================================================================
// RESET DEMO
// =====================================================================
async function resetDemoData() {
  if (!confirm('This will reset the database to the clean default seed state. Continue?')) return;
  const btn = document.getElementById('btnResetDemo');
  if (btn) { btn.disabled = true; btn.textContent = 'Resetting…'; }

  try {
    const res = await apiFetch('/api/reset-demo', { method: 'POST' });
    const data = await res.json();
    showToast(data.message, 'success');
    currentOffset = 0;
    if (currentTab === 'dashboard') loadDashboard();
    if (currentTab === 'items') loadWorkItems();
    if (currentTab === 'async') loadAsyncJobs();
  } catch (err) {
    showToast('Failed to reset demo database', 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '↺ Reset Demo'; }
  }
}

// =====================================================================
// EVENT LISTENERS
// =====================================================================
function setupEventListeners() {
  // Persona switcher
  document.getElementById('personaSelect').addEventListener('change', e => setCurrentUser(e.target.value));

  // Reset demo
  document.getElementById('btnResetDemo').addEventListener('click', resetDemoData);

  // Nav tabs
  document.querySelectorAll('.nav-tab-btn').forEach(btn =>
    btn.addEventListener('click', () => switchTab(btn.dataset.tab))
  );

  // ---- FILTERS ----
  let searchTimer = null;
  document.getElementById('filterSearch').addEventListener('input', e => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      currentFilters.search = e.target.value.trim();
      currentOffset = 0;
      loadWorkItems();
    }, 320);
  });

  ['filterStatus', 'filterPriority', 'filterTeam', 'filterSla'].forEach(id => {
    const key = id === 'filterStatus' ? 'status' :
                id === 'filterPriority' ? 'priority' :
                id === 'filterTeam' ? 'assigned_team' : 'sla_risk_level';
    document.getElementById(id).addEventListener('change', e => {
      currentFilters[key] = e.target.value;
      currentOffset = 0;
      loadWorkItems();
    });
  });

  // ---- PAGINATION ----
  document.getElementById('btnPrevPage').addEventListener('click', () => {
    if (currentOffset >= PAGE_SIZE) {
      currentOffset -= PAGE_SIZE;
      loadWorkItems();
    }
  });
  document.getElementById('btnNextPage').addEventListener('click', () => {
    currentOffset += PAGE_SIZE;
    loadWorkItems();
  });

  // ---- DETAIL MODAL ----
  document.getElementById('btnCloseDetailModal').addEventListener('click', () => {
    document.getElementById('itemDetailModal').style.display = 'none';
  });
  document.getElementById('itemDetailModal').addEventListener('click', e => {
    if (e.target.id === 'itemDetailModal') e.target.style.display = 'none';
  });

  // Enter key on comment input
  document.getElementById('newCommentInput').addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      addCommentToCurrentItem();
    }
  });

  // ---- CREATE MODAL ----
  document.getElementById('btnOpenCreateModal').addEventListener('click', () => {
    document.getElementById('createItemModal').style.display = 'flex';
    document.getElementById('createTitle').focus();
  });
  document.getElementById('btnCloseCreateModal').addEventListener('click', () =>
    document.getElementById('createItemModal').style.display = 'none'
  );
  document.getElementById('btnCancelCreate').addEventListener('click', () =>
    document.getElementById('createItemModal').style.display = 'none'
  );
  document.getElementById('createItemModal').addEventListener('click', e => {
    if (e.target.id === 'createItemModal') e.target.style.display = 'none';
  });

  // ---- CREATE FORM SUBMIT ----
  document.getElementById('createItemForm').addEventListener('submit', async e => {
    e.preventDefault();
    const btn = document.getElementById('btnSubmitCreate');
    btn.disabled = true;
    btn.textContent = 'Creating…';

    const title        = document.getElementById('createTitle').value.trim();
    const description  = document.getElementById('createDescription').value.trim();
    const category     = document.getElementById('createCategory').value;
    const priority     = document.getElementById('createPriority').value;
    const assigned_team= document.getElementById('createTeam').value;

    try {
      const res = await apiFetch('/api/work-items', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': `create_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`
        },
        body: JSON.stringify({ title, description, category, priority, assigned_team })
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Creation failed');
      }
      showToast('Work item created successfully!', 'success');
      document.getElementById('createItemModal').style.display = 'none';
      document.getElementById('createItemForm').reset();
      loadWorkItems();
      if (currentTab === 'dashboard') loadDashboard();
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      btn.disabled = false;
      btn.innerHTML = '<span>＋</span> Create Work Item';
    }
  });

  // Escape key closes modals
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      document.getElementById('itemDetailModal').style.display = 'none';
      document.getElementById('createItemModal').style.display = 'none';
    }
  });
}

// =====================================================================
// BADGE HELPERS
// =====================================================================
function prioBadge(priority) {
  return `<span class="badge-priority priority-${priority.toLowerCase()}">${priority}</span>`;
}

function statusBadge(status) {
  const label = status.replace(/_/g, ' ');
  return `<span class="badge-status status-${status.toLowerCase()}">${label}</span>`;
}

function slaBadge(level) {
  if (level === 'BREACHED') return `<span class="badge-sla sla-breached">🚨 BREACHED</span>`;
  if (level === 'WARN')     return `<span class="badge-sla sla-warn">⚠️ AT RISK</span>`;
  return `<span class="badge-sla sla-normal">✓ Normal</span>`;
}

// =====================================================================
// DATE FORMATTING
// =====================================================================
function formatDateRelative(isoString) {
  try {
    const d = new Date(isoString);
    const now = new Date();
    const diffMs = now - d;
    const diffMin = Math.round(diffMs / 60000);
    if (diffMin < 1)   return 'just now';
    if (diffMin < 60)  return `${diffMin}m ago`;
    if (diffMin < 1440) return `${Math.round(diffMin/60)}h ago`;
    return d.toLocaleDateString('en-GB', { day:'numeric', month:'short', hour:'2-digit', minute:'2-digit' });
  } catch {
    return isoString;
  }
}

// =====================================================================
// SECURITY UTILITY
// =====================================================================
function escapeHtml(str) {
  if (!str) return '';
  return String(str).replace(/[&<>'"]/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c])
  );
}
