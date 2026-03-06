/**
 * channels.js — ChannelsPanel: live status of all channels.
 */

class ChannelsPanel {
  constructor(ws) {
    this._ws = ws;
    this._interval = null;
  }

  load() {
    this._ws.send('channels.status', {})
      .then(data => this._render(data.channels || []))
      .catch(() => {
        const el = qs('#channels-list');
        if (el) el.innerHTML = '<div class="panel-error">Failed to load channels.</div>';
      });
  }

  startAutoRefresh() {
    this.stopAutoRefresh();
    this._interval = setInterval(() => this.load(), 30000);
  }

  stopAutoRefresh() {
    if (this._interval) {
      clearInterval(this._interval);
      this._interval = null;
    }
  }

  _render(channels) {
    const el = qs('#channels-list');
    if (!el) return;
    if (!channels.length) {
      el.innerHTML = '<div class="panel-empty">No channels configured.</div>';
      return;
    }
    let html = '';
    for (const ch of channels) {
      const dotCls = ch.connected ? 'status-dot--on' : 'status-dot--off';
      const statusText = ch.connected ? 'Connected' : 'Disconnected';
      html += `
        <div class="channel-status-card">
          <div class="channel-status-card__header">
            <span class="status-dot ${dotCls}" title="${statusText}"></span>
            <span class="channel-status-card__name">${_cEsc(ch.name)}</span>
            <span class="badge badge--${_cEsc(ch.type)}">${_cEsc(ch.type)}</span>
          </div>
          <div class="channel-status-card__details">
            ${_channelDetails(ch)}
          </div>
        </div>`;
    }
    el.innerHTML = html;
  }
}

function _channelDetails(ch) {
  if (ch.type === 'webchat') {
    return `<span>${ch.client_count} client${ch.client_count !== 1 ? 's' : ''} connected</span>`;
  }
  if (ch.type === 'telegram') {
    if (!ch.enabled) return '<span class="channel-status-card__disabled">Not configured</span>';
    if (!ch.connected) {
      return `
        <span class="channel-status-card__disconnected">
          &#9888; Disconnected &mdash; restart the gateway to reconnect
        </span>`;
    }
    return `
      <span>Policy: <strong>${_cEsc(ch.dm_policy || '—')}</strong></span>
      <span>${ch.paired_users} paired user${ch.paired_users !== 1 ? 's' : ''}</span>`;
  }
  // Generic fallback for future channel types
  if (!ch.connected) {
    return '<span class="channel-status-card__disconnected">&#9888; Disconnected &mdash; restart gateway to reconnect</span>';
  }
  return '';
}

function _cEsc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
