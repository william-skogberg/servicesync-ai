'use strict';

// ServiceSync AI dashboard: no framework, no browser-side API key.
// Data is always loaded from the local Inquiry API, not hard-coded.
const state = { inquiries: [], selectedId: null, query: '', filter: 'all' };
const $ = (id) => document.getElementById(id);
const SERVICE_LABELS = {
  home_cleaning: 'Home cleaning',
  deep_cleaning: 'Deep cleaning',
  window_cleaning: 'Window cleaning',
  move_out_cleaning: 'Move-out cleaning',
  other: 'Other / unknown',
};
const FLAG_LABELS = {
  service_mismatch: 'Selected service differs from AI classification',
  unclassified: 'AI could not determine a specific service',
  ai_review: 'AI recommends human review',
  ai_unavailable: 'AI analysis was unavailable',
};

function labelService(value) {
  return SERVICE_LABELS[value] || String(value || 'Unknown').replaceAll('_', ' ');
}

function formatTime(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }).format(date);
}

function reviewFlags(inquiry) {
  if (Array.isArray(inquiry.review_flags)) return inquiry.review_flags;
  // Compatibility with records from the earlier backend, if necessary.
  const flags = [];
  if (inquiry.analysis_status === 'unavailable') flags.push('ai_unavailable');
  const analysis = inquiry.ai_analysis;
  if (analysis) {
    if (analysis.category === 'other') flags.push('unclassified');
    else if (analysis.category && analysis.category !== inquiry.service_type) flags.push('service_mismatch');
    if (analysis.needs_review) flags.push('ai_review');
  }
  return flags;
}

function make(tag, className = '', value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value !== undefined && value !== null) node.textContent = String(value);
  return node;
}

function badge(label, style) {
  return make('span', `tag tag-${style}`, label);
}

function currentRecord() {
  return state.inquiries.find((item) => item.id === state.selectedId) || null;
}

function statusBadge(status) {
  return status === 'synced'
    ? badge('✓ Synced', 'green')
    : status === 'failed'
      ? badge('! Failed', 'red')
      : badge('• Pending', 'grey');
}

function analysisBadge(status) {
  if (status === 'completed') return badge('✦ AI completed', 'blue');
  if (status === 'demo') return badge('◇ Rules demo', 'grey');
  return badge('! AI unavailable', 'red');
}

function setConnection(ok) {
  const node = $('api-indicator');
  node.className = `connection-status ${ok ? 'online' : 'offline'}`;
  node.replaceChildren(make('span', 'status-dot'), document.createTextNode(ok ? 'API connected' : 'API unavailable'));
}

let toastTimeout;
function notify(message, isError = false) {
  const node = $('toast');
  node.textContent = message;
  node.className = `toast${isError ? ' error' : ''}`;
  node.hidden = false;
  clearTimeout(toastTimeout);
  toastTimeout = setTimeout(() => { node.hidden = true; }, 4500);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    let details = `${response.status} ${response.statusText}`;
    if (typeof body?.detail === 'string') details = body.detail;
    throw new Error(details);
  }
  return body;
}

async function refresh({ quiet = false, selectId = null } = {}) {
  $('refresh-button').disabled = true;
  try {
    const inquiries = await api('/inquiries');
    if (!Array.isArray(inquiries)) throw new Error('Unexpected API response');
    state.inquiries = inquiries;
    if (selectId) state.selectedId = selectId;
    if (!currentRecord()) state.selectedId = inquiries[0]?.id || null;
    render();
    setConnection(true);
    if (!quiet) notify('Dashboard updated');
  } catch (error) {
    setConnection(false);
    // Keep any previously loaded records visible on intermittent errors.
    if (!state.inquiries.length) {
      $('inquiries-body').replaceChildren();
      const tr = make('tr');
      const td = make('td', 'table-empty', 'Cannot load inquiries. Is Inquiry API running on port 8000?');
      td.colSpan = 4;
      tr.append(td);
      $('inquiries-body').append(tr);
    }
    notify(`Could not load data: ${error.message}`, true);
  } finally {
    $('refresh-button').disabled = false;
  }
}

function renderMetrics() {
  const inquiries = state.inquiries;
  $('stat-total').textContent = String(inquiries.length);
  $('stat-synced').textContent = String(inquiries.filter((item) => item.status === 'synced').length);
  $('stat-failed').textContent = String(inquiries.filter((item) => item.status === 'failed').length);
  $('stat-review').textContent = String(inquiries.filter((item) => reviewFlags(item).length > 0).length);
  $('retry-all-button').disabled = !inquiries.some((item) => item.status === 'failed');
}

function filteredInquiries() {
  return state.inquiries.filter((item) => {
    const matchesFilter = state.filter === 'all'
      || (state.filter === 'attention' && reviewFlags(item).length > 0)
      || item.status === state.filter;
    const text = [item.customer_name, item.message, item.postal_code, item.service_type, item.ai_analysis?.category]
      .filter(Boolean).join(' ').toLowerCase();
    return matchesFilter && text.includes(state.query);
  });
}

function renderList() {
  const rows = filteredInquiries();
  const body = $('inquiries-body');
  body.replaceChildren();
  $('results-count').textContent = `Showing ${rows.length} of ${state.inquiries.length} inquiries`;
  if (!rows.length) {
    const tr = make('tr');
    const td = make('td', 'table-empty', 'No inquiries match your filters.');
    td.colSpan = 4;
    tr.append(td);
    body.append(tr);
    return;
  }

  for (const item of rows) {
    const tr = make('tr', item.id === state.selectedId ? 'selected' : '');
    tr.setAttribute('role', 'button');
    tr.setAttribute('tabindex', '0');
    tr.setAttribute('aria-label', `View inquiry for ${item.customer_name}`);
    tr.setAttribute('aria-pressed', item.id === state.selectedId ? 'true' : 'false');
    tr.addEventListener('click', () => selectInquiry(item.id));
    tr.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        selectInquiry(item.id);
      }
    });

    const customer = make('td');
    customer.append(make('span', 'cell-name', item.customer_name), make('span', 'cell-meta', formatTime(item.created_at)));
    const service = make('td');
    service.append(make('span', 'service-name', labelService(item.service_type)));
    const delivery = make('td');
    delivery.append(statusBadge(item.status));
    const review = make('td');
    if (reviewFlags(item).length) {
      const icon = make('span', 'review-indicator', '!');
      icon.title = 'Needs review';
      icon.setAttribute('aria-label', 'Needs review');
      review.append(icon);
    }
    tr.append(customer, service, delivery, review);
    body.append(tr);
  }
}

function selectInquiry(id) {
  state.selectedId = id;
  renderList();
  renderDetails();
}

function fact(title, value) {
  const wrapper = make('div', 'detail-fact');
  wrapper.append(make('small', '', title), make('strong', '', value ?? '—'));
  return wrapper;
}

function addSection(container, heading) {
  container.append(make('h3', 'detail-section-title', heading));
}

function renderDetails() {
  const container = $('detail-content');
  const item = currentRecord();
  if (!item) {
    container.replaceChildren();
    const empty = make('div', 'empty-details');
    empty.append(make('div', 'empty-symbol', '◇'), make('strong', '', 'No inquiry selected'), make('p', '', 'Create a request or choose one from the list.'));
    container.append(empty);
    return;
  }

  container.replaceChildren();
  const analysis = item.ai_analysis;
  const flags = reviewFlags(item);
  container.append(make('h3', 'detail-name', item.customer_name));
  container.append(make('p', 'detail-id', `ID ${item.id} · ${formatTime(item.created_at)}`));
  const tags = make('div', 'detail-tags');
  tags.append(statusBadge(item.status), analysisBadge(item.analysis_status));
  if (flags.length) tags.append(badge('Needs review', 'amber'));
  container.append(tags);

  if (flags.length) {
    const alert = make('div', 'review-alert' + (item.analysis_status === 'unavailable' ? ' error' : ''));
    alert.append(make('strong', '', flags.includes('service_mismatch') ? 'Service mismatch detected' : 'Review recommended'));
    alert.append(make('p', '', flags.map((flag) => FLAG_LABELS[flag] || flag).join(' · ')));
    container.append(alert);
  }

  addSection(container, 'SERVICE COMPARISON');
  const comparison = make('div', 'detail-row');
  comparison.append(
    fact('Selected in form', labelService(item.service_type)),
    fact('AI classification', analysis ? labelService(analysis.category) : 'Unavailable'),
  );
  container.append(comparison);

  addSection(container, 'AI EXTRACTION');
  const extraction = make('div', 'detail-row');
  extraction.append(fact('Area', analysis?.area_m2 ? `${analysis.area_m2} m²` : 'Not specified'));
  extraction.append(fact('Requested time', analysis?.requested_date_text || 'Not specified'));
  container.append(extraction);

  if (analysis?.summary) {
    addSection(container, 'AI SUMMARY');
    container.append(make('p', 'ai-summary', analysis.summary));
  }

  addSection(container, 'ORIGINAL MESSAGE');
  container.append(make('p', 'message-card', item.message));
  addSection(container, 'DELIVERY');
  const details = make('div', 'detail-row');
  details.append(fact('Postal code', item.postal_code), fact('Delivery attempts', item.delivery_attempts ?? 0));
  container.append(details);
  if (item.last_error) container.append(make('p', 'detail-muted', `Last delivery error: ${item.last_error}`));
  if (item.ai_error) container.append(make('p', 'detail-muted', `AI error: ${item.ai_error}`));

  if (item.status !== 'synced') {
    const actions = make('div', 'detail-actions');
    const retry = make('button', 'button button-primary', '↻ Retry CRM delivery');
    retry.type = 'button';
    retry.addEventListener('click', () => retryOne(item.id, retry));
    actions.append(retry);
    container.append(actions);
  }
}

function render() {
  renderMetrics();
  renderList();
  renderDetails();
}

async function retryOne(id, button) {
  button.disabled = true;
  try {
    const result = await api(`/inquiries/${encodeURIComponent(id)}/retry`, { method: 'POST' });
    await refresh({ quiet: true, selectId: id });
    notify(result.status === 'synced' ? 'CRM delivery succeeded' : 'CRM is still unavailable', result.status !== 'synced');
  } catch (error) {
    button.disabled = false;
    notify(`Retry failed: ${error.message}`, true);
  }
}

async function retryAll() {
  const button = $('retry-all-button');
  button.disabled = true;
  try {
    const result = await api('/retry-failed', { method: 'POST' });
    await refresh({ quiet: true });
    notify(`Retried ${result.attempted} request(s): ${result.synced} synced, ${result.still_failed} failed`, result.still_failed > 0);
  } catch (error) {
    notify(`Retry failed: ${error.message}`, true);
  } finally {
    renderMetrics();
  }
}

function closeDialog() { $('new-inquiry-dialog').close(); }

async function submitNewInquiry(event) {
  event.preventDefault();
  const form = $('new-inquiry-form');
  if (!form.reportValidity()) return;
  const submitButton = $('submit-inquiry-button');
  const data = Object.fromEntries(new FormData(form).entries());
  submitButton.disabled = true;
  submitButton.textContent = 'Analyzing and syncing…';
  try {
    const result = await api('/inquiries', { method: 'POST', body: JSON.stringify(data) });
    closeDialog();
    form.reset();
    state.query = '';
    state.filter = 'all';
    $('search-input').value = '';
    $('status-filter').value = 'all';
    await refresh({ quiet: true, selectId: result.id });
    const aiStatus = result.analysis_status === 'completed' ? 'AI completed' : result.analysis_status === 'demo' ? 'demo analysis' : 'AI unavailable';
    notify(`Request saved · ${result.status === 'synced' ? 'CRM synced' : 'CRM delivery failed'} · ${aiStatus}`, result.status !== 'synced');
  } catch (error) {
    notify(`Could not create inquiry: ${error.message}`, true);
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = 'Analyze & sync →';
  }
}

$('refresh-button').addEventListener('click', () => refresh());
$('search-input').addEventListener('input', (event) => { state.query = event.target.value.trim().toLowerCase(); renderList(); });
$('status-filter').addEventListener('change', (event) => { state.filter = event.target.value; renderList(); });
$('retry-all-button').addEventListener('click', retryAll);
$('new-inquiry-button').addEventListener('click', () => $('new-inquiry-dialog').showModal());
$('close-dialog-button').addEventListener('click', closeDialog);
$('cancel-dialog-button').addEventListener('click', closeDialog);
$('new-inquiry-form').addEventListener('submit', submitNewInquiry);
refresh({ quiet: true });
