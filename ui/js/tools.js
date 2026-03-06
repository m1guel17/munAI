/**
 * tools.js — ToolsPanel: tool catalog + approval queue + approval history tabs.
 */

class ToolsPanel {
  constructor(ws) {
    this._ws = ws;
    this._policy = {};
    this._tab = 'catalog';
  }

  load() {
    this._ws.send('tools.list', {})
      .then(data => {
        this._policy = data.policy || {};
        this._renderCatalog(data.tools || [], data.policy || {});
      })
      .catch(() => this._showError('catalog', 'Failed to load tools.'));
    this._loadApprovals();
  }

  _loadApprovals() {
    this._ws.send('approvals.list', {})
      .then(data => this._renderApprovals(data.approvals || []))
      .catch(() => this._showError('approvals', 'Failed to load approvals.'));
  }

  _loadHistory() {
    const el = qs('#tools-history');
    if (el) el.innerHTML = '<div class="panel-loading">Loading...</div>';
    const today = new Date().toISOString().slice(0, 10);
    Promise.all([
      fetch('/api/audit?type=tool.approval_granted&limit=200&date=' + today).then(r => r.json()),
      fetch('/api/audit?type=tool.approval_denied&limit=200&date=' + today).then(r => r.json()),
    ])
      .then(([granted, denied]) => {
        const events = [
          ...(granted.events || []),
          ...(denied.events || []),
        ].sort((a, b) => (b.ts || 0) - (a.ts || 0));
        this._renderHistory(events);
      })
      .catch(() => this._showError('history', 'Failed to load approval history.'));
  }

  _renderCatalog(tools, policy) {
    const el = qs('#tools-catalog');
    if (!el) return;

    let html = '<div class="tool-list">';
    for (const t of tools) {
      const dotCls = t.enabled ? 'status-dot--on' : 'status-dot--off';
      const paramRows = (t.params || []).map(p =>
        `<tr>
          <td class="tool-param__name">${_tEsc(p.name)}${p.required ? ' <span class="tool-param__req">*</span>' : ''}</td>
          <td class="tool-param__type">${_tEsc(p.type)}</td>
          <td class="tool-param__desc">${_tEsc(p.description)}</td>
        </tr>`
      ).join('');
      html += `
        <div class="tool-item">
          <div class="tool-row" data-tool="${_tEsc(t.name)}">
            <span class="tool-row__chevron">&#9656;</span>
            <span class="tool-row__name">${_tEsc(t.name)}</span>
            <span class="badge badge--${_tEsc(t.group)}">${_tEsc(t.group)}</span>
            <span class="status-dot ${dotCls}" title="${t.enabled ? 'Enabled' : 'Disabled'}"></span>
            <span class="tool-row__desc">${_tEsc(t.description)}</span>
            <label class="toggle ${t.enabled ? 'toggle--on' : ''}" title="${t.enabled ? 'Disable' : 'Enable'}">
              <input type="checkbox" class="toggle__input" data-tool="${_tEsc(t.name)}" ${t.enabled ? 'checked' : ''} />
              <span class="toggle__track"></span>
            </label>
          </div>
          <div class="tool-detail" hidden>
            <p class="tool-detail__desc">${_tEsc(t.description)}</p>
            ${paramRows ? `<table class="tool-params">
              <thead><tr><th>Parameter</th><th>Type</th><th>Description</th></tr></thead>
              <tbody>${paramRows}</tbody>
            </table>` : ''}
          </div>
        </div>`;
    }
    html += '</div>';

    // Policy section
    const am = policy.shell_approval_mode || 'always';
    const wo = policy.workspace_only ? 'checked' : '';
    html += `
      <div class="tools-policy">
        <h3 class="tools-policy__title">Shell Policy</h3>
        <div class="tools-policy__row">
          <label for="approval-mode-select">Approval mode</label>
          <select id="approval-mode-select">
            <option value="always" ${am === 'always' ? 'selected' : ''}>Always</option>
            <option value="auto" ${am === 'auto' ? 'selected' : ''}>Auto (safe commands)</option>
            <option value="never" ${am === 'never' ? 'selected' : ''}>Never</option>
          </select>
        </div>
        <div class="tools-policy__row">
          <label>
            <input type="checkbox" id="workspace-only-cb" ${wo} />
            Workspace-only file access
          </label>
        </div>
        <button id="tools-policy-save-btn" class="btn btn--primary btn--sm">Save Policy</button>
      </div>`;

    el.innerHTML = html;

    // Row expand
    el.querySelectorAll('.tool-row').forEach(row => {
      row.addEventListener('click', e => {
        if (e.target.closest('.toggle')) return;
        const item = row.closest('.tool-item');
        const detail = item?.querySelector('.tool-detail');
        const chevron = row.querySelector('.tool-row__chevron');
        if (!detail) return;
        const open = !detail.hidden;
        detail.hidden = open;
        if (chevron) chevron.innerHTML = open ? '&#9656;' : '&#9662;';
      });
    });

    // Toggle listeners
    el.querySelectorAll('.toggle__input').forEach(cb => {
      cb.addEventListener('change', () => this._onToggle(cb.dataset.tool, cb.checked));
    });

    // Policy save
    qs('#tools-policy-save-btn')?.addEventListener('click', () => this._savePolicy());
  }

  _onToggle(toolName, enabled) {
    const deny = new Set(this._policy.deny || []);
    const allow = new Set(this._policy.allow || []);
    if (enabled) {
      deny.delete(toolName);
    } else {
      deny.add(toolName);
      allow.delete(toolName);
    }
    this._policy.deny = [...deny];
    this._policy.allow = [...allow];
    this._ws.send('tools.set_policy', { allow: this._policy.allow, deny: this._policy.deny })
      .catch(() => {});
  }

  _savePolicy() {
    const mode = qs('#approval-mode-select')?.value || 'always';
    const wo = qs('#workspace-only-cb')?.checked ?? true;
    this._ws.send('tools.set_policy', {
      shell_approval_mode: mode,
      workspace_only: wo,
      allow: this._policy.allow || [],
      deny: this._policy.deny || [],
    }).catch(() => {});
  }

  _renderApprovals(approvals) {
    const el = qs('#tools-approvals');
    if (!el) return;
    if (!approvals.length) {
      el.innerHTML = '<div class="panel-empty">No pending approvals.</div>';
      return;
    }
    let html = '';
    for (const a of approvals) {
      const cmd = Array.isArray(a.command) ? a.command.join(' ') : String(a.command || '');
      html += `
        <div class="approval-item" data-id="${_tEsc(a.approval_id)}">
          <div class="approval-item__meta">
            <span class="approval-item__id">${_tEsc(a.approval_id.slice(0, 8))}</span>
            <code class="approval-item__cmd">${_tEsc(cmd)}</code>
            <span class="approval-item__time">${_tEsc(a.requested_at || '')}</span>
          </div>
          <div class="approval-item__actions">
            <button class="btn btn--success btn--sm" data-action="approve" data-id="${_tEsc(a.approval_id)}">Approve</button>
            <button class="btn btn--danger btn--sm" data-action="deny" data-id="${_tEsc(a.approval_id)}">Deny</button>
          </div>
        </div>`;
    }
    el.innerHTML = html;

    el.querySelectorAll('[data-action]').forEach(btn => {
      btn.addEventListener('click', () => {
        const method = btn.dataset.action === 'approve' ? 'tool.approve' : 'tool.deny';
        this._ws.send(method, { approval_id: btn.dataset.id }).catch(() => {});
        btn.closest('.approval-item')?.remove();
      });
    });
  }

  _renderHistory(events) {
    const el = qs('#tools-history');
    if (!el) return;
    if (!events.length) {
      el.innerHTML = '<div class="panel-empty">No approval history today.</div>';
      return;
    }
    let html = '<table class="audit-table"><thead><tr><th>Time</th><th>Decision</th><th>Session</th><th>Detail</th></tr></thead><tbody>';
    for (const ev of events) {
      const time = ev.ts ? new Date(ev.ts * 1000).toLocaleTimeString() : '—';
      const granted = ev.event_type === 'tool.approval_granted';
      const badge = granted
        ? '<span class="badge badge--on">approved</span>'
        : '<span class="badge badge--off">denied</span>';
      const detail = ev.detail ? JSON.stringify(ev.detail).slice(0, 80) : '—';
      html += `<tr>
        <td>${_tEsc(time)}</td>
        <td>${badge}</td>
        <td>${_tEsc(ev.session_id || '—')}</td>
        <td><code>${_tEsc(detail)}</code></td>
      </tr>`;
    }
    html += '</tbody></table>';
    el.innerHTML = html;
  }

  _showError(section, msg) {
    const ids = { catalog: '#tools-catalog', approvals: '#tools-approvals', history: '#tools-history' };
    const el = qs(ids[section] || '#tools-catalog');
    if (el) el.innerHTML = `<div class="panel-error">${_tEsc(msg)}</div>`;
  }

  switchTab(tab) {
    this._tab = tab;
    qsa('.panel-tab').forEach(t => t.classList.toggle('panel-tab--active', t.dataset.tab === tab));
    qs('#tools-catalog-pane')?.classList.toggle('pane--hidden', tab !== 'catalog');
    qs('#tools-approvals-pane')?.classList.toggle('pane--hidden', tab !== 'approvals');
    qs('#tools-history-pane')?.classList.toggle('pane--hidden', tab !== 'history');
    if (tab === 'approvals') this._loadApprovals();
    if (tab === 'history') this._loadHistory();
  }
}

function _tEsc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
