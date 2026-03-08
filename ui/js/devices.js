/**
 * devices.js — DevicesPanel: paired Telegram users and active webchat connections.
 */

class DevicesPanel {
  constructor(ws) {
    this._ws = ws;
  }

  load() {
    const el = qs('#devices-list');
    if (el) el.innerHTML = '<div class="panel-loading">Loading\u2026</div>';
    this._ws.send('auth.devices.list', {})
      .then(data => this._render(data.devices || [], data.pending_code))
      .catch(() => {
        if (el) el.innerHTML = '<div class="panel-error">Failed to load devices.</div>';
      });
  }

  _generateCode() {
    const el = qs('#devices-list');
    if (el) el.innerHTML = '<div class="panel-loading">Generating code\u2026</div>';
    this._ws.send('auth.devices.list', { generate_code: true })
      .then(data => this._render(data.devices || [], data.pending_code))
      .catch(() => {
        if (el) el.innerHTML = '<div class="panel-error">Failed to generate code.</div>';
      });
  }

  _render(devices, pendingCode) {
    const el = qs('#devices-list');
    if (!el) return;

    let html = '';

    // Pending pairing code callout
    if (pendingCode) {
      html +=
        '<div class="devices-code-box">' +
          '<strong>Pending pairing code:</strong> ' +
          '<span class="devices-code">' + _devEsc(pendingCode.code) + '</span>' +
          (pendingCode.expires_at
            ? ' <span class="devices-code-expiry">(expires ' + _devEsc(new Date(pendingCode.expires_at).toLocaleString()) + ')</span>'
            : '') +
        '</div>';
    }

    html +=
      '<div class="config-form__actions" style="margin-bottom:1rem">' +
        '<button class="btn btn--secondary btn--sm" id="devices-gen-code-btn">Generate Pairing Code</button>' +
      '</div>';

    if (!devices.length) {
      html += '<div class="panel-empty">No paired devices.</div>';
    } else {
      html += '<table class="devices-table"><thead><tr><th>ID</th><th>Type</th><th></th></tr></thead><tbody>';
      for (const d of devices) {
        html +=
          '<tr>' +
            '<td>' + _devEsc(d.id) + '</td>' +
            '<td><span class="badge badge--' + _devEsc(d.type) + '">' + _devEsc(d.type) + '</span></td>' +
            '<td><button class="btn btn--secondary btn--sm devices-revoke-btn" ' +
              'data-id="' + _devEsc(d.id) + '" data-type="' + _devEsc(d.type) + '">Revoke</button></td>' +
          '</tr>';
      }
      html += '</tbody></table>';
    }

    el.innerHTML = html;

    qs('#devices-gen-code-btn')?.addEventListener('click', () => this._generateCode());

    el.querySelectorAll('.devices-revoke-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        this._ws.send('auth.devices.revoke', { id: btn.dataset.id, type: btn.dataset.type })
          .then(() => this.load())
          .catch(() => { btn.textContent = 'Failed'; });
      });
    });
  }
}

function _devEsc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
