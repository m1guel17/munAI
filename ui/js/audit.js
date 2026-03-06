/**
 * audit.js — AuditPanel: filterable audit log viewer with live tail.
 */

class AuditPanel {
  constructor(ws) {
    this._ws = ws;
    this._filterText = '';
    this._liveMode = false;
    this._liveUnsubscribe = null;
  }

  load() {
    this._initDatePicker();
    this._attachHandlers();
    this._fetch();
  }

  filter(text) {
    this._filterText = text.toLowerCase();
    this._applyFilter();
  }

  _initDatePicker() {
    const picker = qs('#audit-date-picker');
    if (picker && !picker.value) {
      picker.value = new Date().toISOString().slice(0, 10);
    }
  }

  _attachHandlers() {
    const refreshBtn = qs('#audit-refresh-btn');
    if (refreshBtn) refreshBtn.onclick = () => this._fetch();

    const picker = qs('#audit-date-picker');
    if (picker) picker.onchange = () => this._fetch();

    const typeFilter = qs('#audit-type-filter');
    if (typeFilter) typeFilter.onchange = () => this._fetch();

    const liveToggle = qs('#audit-live-toggle');
    if (liveToggle) {
      liveToggle.onclick = () => this._toggleLive(liveToggle);
    }

    const searchEl = qs('#audit-search');
    if (searchEl) {
      searchEl.oninput = () => this.filter(searchEl.value);
    }
  }

  _fetch() {
    const date = (qs('#audit-date-picker') || {}).value || '';
    const type = (qs('#audit-type-filter') || {}).value || '';

    const params = new URLSearchParams();
    if (date) params.set('date', date);
    if (type) params.set('type', type);
    params.set('limit', '500');
    fetch('/api/audit?' + params)
      .then(r => r.json())
      .then(data => this._renderRows(data.events || []))
      .catch(() => this._showError('Failed to load audit events.'));
  }

  _renderRows(events) {
    const tbody = qs('#audit-tbody');
    const empty = qs('#audit-empty');
    if (!tbody) return;

    tbody.innerHTML = '';

    if (!events.length) {
      if (empty) empty.hidden = false;
      return;
    }
    if (empty) empty.hidden = true;

    for (const event of events) {
      tbody.appendChild(this._renderRow(event));
    }
    this._applyFilter();
  }

  _renderRow(event) {
    const tr = document.createElement('tr');

    const ts = event.timestamp ? new Date(event.timestamp).toLocaleTimeString() : '—';
    const evType = event.event_type || '—';
    const sessionId = event.session_id ? event.session_id.slice(0, 8) : '—';
    const detail = event.detail ? JSON.stringify(event.detail) : '';

    // Color code by event type prefix
    let typeClass = '';
    if (evType.startsWith('gateway.auth') || evType.startsWith('tool.blocked') || evType.startsWith('tool.path')) {
      typeClass = 'audit-type--security';
    } else if (evType.startsWith('tool.')) {
      typeClass = 'audit-type--tool';
    } else if (evType.startsWith('agent.')) {
      typeClass = 'audit-type--agent';
    }

    tr.innerHTML = `
      <td class="audit-cell audit-cell--time">${ts}</td>
      <td class="audit-cell audit-cell--type ${typeClass}">${evType}</td>
      <td class="audit-cell audit-cell--session" title="${event.session_id || ''}">${sessionId}</td>
      <td class="audit-cell audit-cell--detail"></td>
    `;

    const detailCell = tr.querySelector('.audit-cell--detail');
    if (detail.length > 80) {
      const short = el('span', { class: 'audit-detail-short' });
      short.textContent = detail.slice(0, 80) + '…';
      const full = el('pre', { class: 'audit-detail-full', hidden: true });
      full.textContent = JSON.stringify(event.detail, null, 2);
      short.addEventListener('click', () => {
        short.hidden = true;
        full.hidden = false;
      });
      full.addEventListener('click', () => {
        full.hidden = true;
        short.hidden = false;
      });
      detailCell.appendChild(short);
      detailCell.appendChild(full);
    } else {
      detailCell.textContent = detail;
    }

    // Security row highlight
    if (typeClass === 'audit-type--security') {
      tr.classList.add('audit-row--security');
    }

    return tr;
  }

  _applyFilter() {
    const tbody = qs('#audit-tbody');
    if (!tbody) return;
    const rows = tbody.querySelectorAll('tr');
    for (const row of rows) {
      const text = row.textContent.toLowerCase();
      row.hidden = this._filterText ? !text.includes(this._filterText) : false;
    }
  }

  _toggleLive(btn) {
    this._liveMode = !this._liveMode;
    btn.classList.toggle('audit-live-btn--active', this._liveMode);
    btn.title = this._liveMode ? 'Live: ON (click to disable)' : 'Live: OFF (click to enable)';

    if (this._liveMode) {
      this._liveUnsubscribe = this._ws.on('audit.event', (payload) => {
        const tbody = qs('#audit-tbody');
        if (!tbody) return;
        const row = this._renderRow(payload);
        tbody.insertBefore(row, tbody.firstChild);
        const empty = qs('#audit-empty');
        if (empty) empty.hidden = true;
        this._applyFilter();
      });
    } else {
      if (this._liveUnsubscribe) {
        this._liveUnsubscribe();
        this._liveUnsubscribe = null;
      }
    }
  }

  _showError(msg) {
    const tbody = qs('#audit-tbody');
    if (tbody) tbody.innerHTML = '';
    const empty = qs('#audit-empty');
    if (empty) {
      empty.textContent = msg;
      empty.hidden = false;
    }
  }
}
