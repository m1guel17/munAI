/**
 * doctor.js — DoctorPanel: health check diagnostics.
 */

class DoctorPanel {
  constructor(ws) {
    this._ws = ws;
  }

  load() {
    const el = qs('#doctor-list');
    if (el) el.innerHTML = '<div class="panel-loading">Running checks\u2026</div>';
    this._ws.send('doctor.run', {})
      .then(data => this._render(data.checks || []))
      .catch(() => {
        if (el) el.innerHTML = '<div class="panel-error">Failed to run diagnostics.</div>';
      });
  }

  _render(checks) {
    const el = qs('#doctor-list');
    if (!el) return;

    if (!checks.length) {
      el.innerHTML = '<div class="panel-empty">No checks returned.</div>';
      return;
    }

    let html = '<table class="doctor-table"><thead><tr><th>Check</th><th>Status</th><th>Detail</th></tr></thead><tbody>';
    for (const c of checks) {
      const statusCls = c.ok ? 'doctor-status--ok' : 'doctor-status--fail';
      const statusText = c.ok ? '\u2713 pass' : '\u2717 fail';
      html +=
        '<tr>' +
          '<td>' + _docEsc(c.label) + '</td>' +
          '<td class="' + statusCls + '">' + statusText + '</td>' +
          '<td>' + _docEsc(c.detail || '') + '</td>' +
        '</tr>';
    }
    html += '</tbody></table>';
    html += '<div class="config-form__actions" style="margin-top:1rem">' +
      '<button class="btn btn--secondary" id="doctor-run-again-btn">Run Again</button>' +
      '</div>';

    el.innerHTML = html;
    qs('#doctor-run-again-btn')?.addEventListener('click', () => this.load());
  }
}

function _docEsc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
