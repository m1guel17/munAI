/**
 * health.js — HealthPanel: gateway status, uptime, provider info.
 */

class HealthPanel {
  constructor(ws) {
    this._ws = ws;
    this._timer = null;
  }

  load() {
    this._fetch();
    if (!this._timer) {
      this._timer = setInterval(() => this._fetch(), 30000);
    }
  }

  unload() {
    if (this._timer) {
      clearInterval(this._timer);
      this._timer = null;
    }
  }

  async _fetch() {
    try {
      const data = await this._ws.send('health', {});
      this._render(data);
    } catch {
      this._renderError();
    }
  }

  _render(data) {
    const gatewayCard = qs('#health-gateway-card');
    const providerCard = qs('#health-provider-card');
    if (!gatewayCard || !providerCard) return;

    gatewayCard.innerHTML = `
      <h3 class="health-card__title">Gateway</h3>
      <div class="health-row">
        <span class="health-row__label">Status</span>
        <span class="health-row__value">
          <span class="status-dot status-dot--green"></span> Running
        </span>
      </div>
      <div class="health-row">
        <span class="health-row__label">Uptime</span>
        <span class="health-row__value">${this._formatUptime(data.uptime_seconds || 0)}</span>
      </div>
      <div class="health-row">
        <span class="health-row__label">Connections</span>
        <span class="health-row__value">${data.sessions ?? '—'}</span>
      </div>
      <div class="health-row">
        <span class="health-row__label">Port</span>
        <span class="health-row__value">${data.port ?? '18700'}</span>
      </div>
      <div class="health-row">
        <span class="health-row__label">Bind</span>
        <span class="health-row__value">${data.bind ?? '127.0.0.1'}</span>
      </div>
      <div class="health-row">
        <span class="health-row__label">Version</span>
        <span class="health-row__value">${data.version ?? '—'}</span>
      </div>
    `;

    const providers = data.providers || [];
    if (providers.length) {
      let rows = '<h3 class="health-card__title">Model Providers</h3>';
      for (const p of providers) {
        const badges = [];
        if (p.is_primary)   badges.push('<span class="badge badge--on">primary</span>');
        if (p.is_fallback)  badges.push('<span class="badge">fallback</span>');
        if (p.is_heartbeat) badges.push('<span class="badge">heartbeat</span>');
        rows +=
          '<div class="health-row">' +
            '<span class="health-row__label">' + _hEsc(p.name) + '</span>' +
            '<span class="health-row__value">' +
              '<span class="status-dot status-dot--green"></span> ' +
              _hEsc(p.model) + ' ' + badges.join(' ') +
            '</span>' +
          '</div>';
      }
      providerCard.innerHTML = rows;
    } else {
      const provider = data.provider || {};
      providerCard.innerHTML =
        '<h3 class="health-card__title">Primary Model</h3>' +
        '<div class="health-row">' +
          '<span class="health-row__label">Provider</span>' +
          '<span class="health-row__value">' + _hEsc(provider.name ?? '—') + '</span>' +
        '</div>' +
        '<div class="health-row">' +
          '<span class="health-row__label">Model</span>' +
          '<span class="health-row__value">' + _hEsc(provider.model ?? '—') + '</span>' +
        '</div>';
    }
  }

  _renderError() {
    const gatewayCard = qs('#health-gateway-card');
    if (gatewayCard) {
      gatewayCard.innerHTML = `
        <h3 class="health-card__title">Gateway</h3>
        <div class="health-row">
          <span class="health-row__label">Status</span>
          <span class="health-row__value">
            <span class="status-dot status-dot--red"></span> Unreachable
          </span>
        </div>
      `;
    }
  }

  _formatUptime(seconds) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
  }
}

function _hEsc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
