/**
 * config.js — ConfigPanel: form + raw JSON config editor.
 */

class ConfigPanel {
  constructor(ws) {
    this._ws = ws;
    this._hash = null;
    this._config = null;
    this._tab = 'form';
  }

  load() {
    const el = qs('#config-body');
    if (el) el.innerHTML = '<div class="panel-loading">Loading\u2026</div>';
    this._ws.send('config.get', {})
      .then(data => {
        this._hash = data.hash;
        this._config = data.config;
        this._render();
      })
      .catch(() => {
        if (el) el.innerHTML = '<div class="panel-error">Failed to load config.</div>';
      });
  }

  _render() {
    const el = qs('#config-body');
    if (!el) return;

    const formActive = this._tab === 'form';
    const cfg = this._config || {};

    el.innerHTML =
      '<div class="panel-tabs">' +
        '<button class="panel-tab' + (formActive ? ' panel-tab--active' : '') + '" id="config-tab-form">Form</button>' +
        '<button class="panel-tab' + (!formActive ? ' panel-tab--active' : '') + '" id="config-tab-raw">Raw JSON</button>' +
      '</div>' +
      '<div id="config-form-pane"' + (formActive ? '' : ' hidden') + '>' +
        this._renderForm(cfg) +
        '<div class="config-form__actions">' +
          '<button class="btn btn--primary" id="config-save-btn">Save</button>' +
        '</div>' +
      '</div>' +
      '<div id="config-raw-pane"' + (!formActive ? '' : ' hidden') + '>' +
        '<textarea class="config-raw-editor" id="config-raw-textarea" spellcheck="false">' +
          _cfgEsc(JSON.stringify(cfg, null, 2)) +
        '</textarea>' +
        '<div class="config-raw-error" id="config-raw-error" hidden></div>' +
        '<div class="config-form__actions">' +
          '<button class="btn btn--primary" id="config-raw-save-btn">Save</button>' +
        '</div>' +
      '</div>' +
      '<div class="config-save-banner" id="config-save-banner" hidden>' +
        'Config saved. ' +
        '<button class="btn btn--danger btn--sm" id="config-restart-btn">Apply &amp; Restart</button>' +
      '</div>';

    qs('#config-tab-form')?.addEventListener('click', () => { this._tab = 'form'; this._render(); });
    qs('#config-tab-raw')?.addEventListener('click', () => { this._tab = 'raw'; this._render(); });
    qs('#config-save-btn')?.addEventListener('click', () => this._saveForm());
    qs('#config-raw-save-btn')?.addEventListener('click', () => this._saveRaw());
    qs('#config-restart-btn')?.addEventListener('click', () => this._restart());
  }

  _renderForm(cfg) {
    const gw = cfg.gateway || {};
    const ag = cfg.agent || {};
    const ch = cfg.channels || {};
    const tg = ch.telegram || {};
    const wc = ch.webchat || {};
    const hb = cfg.heartbeat || {};
    const tl = cfg.tools || {};
    const au = cfg.audit || {};

    const sel = (val, opt) => opt === val ? ' selected' : '';
    const chk = v => (v !== false && v) ? ' checked' : '';

    return (
      '<details class="config-section" open>' +
        '<summary class="config-section__title">Gateway</summary>' +
        '<div class="config-form__row"><label>Port</label>' +
          '<input type="number" id="cfg-gateway-port" min="1" max="65535" value="' + _cfgEsc(gw.port ?? 18700) + '" /></div>' +
        '<div class="config-form__row"><label>Bind address</label>' +
          '<input type="text" id="cfg-gateway-bind" value="' + _cfgEsc(gw.bind ?? '127.0.0.1') + '" /></div>' +
        '<div class="config-form__row"><label>Auth token env</label>' +
          '<input type="text" id="cfg-gateway-token-env" value="' + _cfgEsc(gw.token_env ?? '') + '" placeholder="MUNAI_GATEWAY_TOKEN" /></div>' +
      '</details>' +
      '<details class="config-section">' +
        '<summary class="config-section__title">Agent</summary>' +
        '<div class="config-form__row"><label>Max tool iterations</label>' +
          '<input type="number" id="cfg-agent-max-tool-iter" min="1" value="' + _cfgEsc(ag.max_tool_iterations ?? 25) + '" /></div>' +
        '<div class="config-form__row"><label>Max turn duration (s)</label>' +
          '<input type="number" id="cfg-agent-max-turn" min="1" value="' + _cfgEsc(ag.max_turn_duration_seconds ?? 300) + '" /></div>' +
        '<div class="config-form__row"><label>Workspace</label>' +
          '<input type="text" id="cfg-agent-workspace" value="' + _cfgEsc(ag.workspace ?? '~/.munai/workspace') + '" /></div>' +
      '</details>' +
      '<details class="config-section">' +
        '<summary class="config-section__title">Channels</summary>' +
        '<div class="config-form__row"><label><input type="checkbox" id="cfg-webchat-enabled"' + chk(wc.enabled !== false) + ' /> Webchat enabled</label></div>' +
        '<div class="config-form__row"><label><input type="checkbox" id="cfg-tg-enabled"' + chk(tg.enabled) + ' /> Telegram enabled</label></div>' +
        '<div class="config-form__row"><label>Telegram DM policy</label>' +
          '<select id="cfg-tg-dm-policy">' +
            '<option value="pairing"' + sel(tg.dm_policy || 'pairing', 'pairing') + '>pairing</option>' +
            '<option value="open"' + sel(tg.dm_policy, 'open') + '>open</option>' +
            '<option value="closed"' + sel(tg.dm_policy, 'closed') + '>closed</option>' +
          '</select></div>' +
        '<div class="config-form__row"><label>Allow from (user IDs, comma-separated)</label>' +
          '<input type="text" id="cfg-tg-allow-from" value="' + _cfgEsc((tg.allow_from || []).join(', ')) + '" /></div>' +
      '</details>' +
      '<details class="config-section">' +
        '<summary class="config-section__title">Heartbeat</summary>' +
        '<div class="config-form__row"><label><input type="checkbox" id="cfg-hb-enabled"' + chk(hb.enabled !== false) + ' /> Enabled</label></div>' +
        '<div class="config-form__row"><label>Interval (minutes)</label>' +
          '<input type="number" id="cfg-hb-interval" min="1" value="' + _cfgEsc(hb.interval_minutes ?? 30) + '" /></div>' +
        '<div class="config-form__row"><label>Ack keyword</label>' +
          '<input type="text" id="cfg-hb-ack" value="' + _cfgEsc(hb.ack_keyword ?? 'HEARTBEAT_OK') + '" /></div>' +
      '</details>' +
      '<details class="config-section">' +
        '<summary class="config-section__title">Tools</summary>' +
        '<div class="config-form__row"><label><input type="checkbox" id="cfg-tools-workspace-only"' + chk(tl.workspace_only !== false) + ' /> Workspace only</label></div>' +
        '<div class="config-form__row"><label>Shell approval mode</label>' +
          '<select id="cfg-tools-shell-approval">' +
            '<option value="always"' + sel(tl.shell_approval_mode || 'always', 'always') + '>always</option>' +
            '<option value="once"' + sel(tl.shell_approval_mode, 'once') + '>once</option>' +
            '<option value="never"' + sel(tl.shell_approval_mode, 'never') + '>never</option>' +
          '</select></div>' +
        '<div class="config-form__row"><label>Max output chars</label>' +
          '<input type="number" id="cfg-tools-max-output" min="1" value="' + _cfgEsc(tl.max_output_chars ?? 50000) + '" /></div>' +
      '</details>' +
      '<details class="config-section">' +
        '<summary class="config-section__title">Audit</summary>' +
        '<div class="config-form__row"><label><input type="checkbox" id="cfg-audit-enabled"' + chk(au.enabled !== false) + ' /> Enabled</label></div>' +
        '<div class="config-form__row"><label>Retention (days)</label>' +
          '<input type="number" id="cfg-audit-retention" min="1" value="' + _cfgEsc(au.retention_days ?? 90) + '" /></div>' +
        '<div class="config-form__row"><label><input type="checkbox" id="cfg-audit-log-prompts"' + chk(au.log_llm_prompts) + ' /> Log LLM prompts</label></div>' +
        '<div class="config-form__row"><label><input type="checkbox" id="cfg-audit-log-output"' + chk(au.log_tool_output !== false) + ' /> Log tool output</label></div>' +
        '<div class="config-form__row"><label><input type="checkbox" id="cfg-audit-redact"' + chk(au.redact_in_audit !== false) + ' /> Redact in audit</label></div>' +
      '</details>'
    );
  }

  _collectForm() {
    const cfg = JSON.parse(JSON.stringify(this._config || {}));

    cfg.gateway = cfg.gateway || {};
    const port = parseInt(qs('#cfg-gateway-port')?.value || '0', 10);
    if (port) cfg.gateway.port = port;
    cfg.gateway.bind = qs('#cfg-gateway-bind')?.value || cfg.gateway.bind;
    const tokenEnv = qs('#cfg-gateway-token-env')?.value;
    cfg.gateway.token_env = tokenEnv || null;

    cfg.agent = cfg.agent || {};
    const maxIter = parseInt(qs('#cfg-agent-max-tool-iter')?.value || '0', 10);
    if (maxIter) cfg.agent.max_tool_iterations = maxIter;
    const maxTurn = parseInt(qs('#cfg-agent-max-turn')?.value || '0', 10);
    if (maxTurn) cfg.agent.max_turn_duration_seconds = maxTurn;
    cfg.agent.workspace = qs('#cfg-agent-workspace')?.value || cfg.agent.workspace;

    cfg.channels = cfg.channels || {};
    cfg.channels.webchat = cfg.channels.webchat || {};
    cfg.channels.webchat.enabled = qs('#cfg-webchat-enabled')?.checked ?? true;
    cfg.channels.telegram = cfg.channels.telegram || {};
    cfg.channels.telegram.enabled = qs('#cfg-tg-enabled')?.checked ?? false;
    cfg.channels.telegram.dm_policy = qs('#cfg-tg-dm-policy')?.value || 'pairing';
    const allowFrom = (qs('#cfg-tg-allow-from')?.value || '').split(',').map(s => s.trim()).filter(Boolean);
    cfg.channels.telegram.allow_from = allowFrom;

    cfg.heartbeat = cfg.heartbeat || {};
    cfg.heartbeat.enabled = qs('#cfg-hb-enabled')?.checked ?? true;
    const hbInterval = parseInt(qs('#cfg-hb-interval')?.value || '0', 10);
    if (hbInterval) cfg.heartbeat.interval_minutes = hbInterval;
    cfg.heartbeat.ack_keyword = qs('#cfg-hb-ack')?.value || 'HEARTBEAT_OK';

    cfg.tools = cfg.tools || {};
    cfg.tools.workspace_only = qs('#cfg-tools-workspace-only')?.checked ?? true;
    cfg.tools.shell_approval_mode = qs('#cfg-tools-shell-approval')?.value || 'always';
    const maxOutput = parseInt(qs('#cfg-tools-max-output')?.value || '0', 10);
    if (maxOutput) cfg.tools.max_output_chars = maxOutput;

    cfg.audit = cfg.audit || {};
    cfg.audit.enabled = qs('#cfg-audit-enabled')?.checked ?? true;
    const retention = parseInt(qs('#cfg-audit-retention')?.value || '0', 10);
    if (retention) cfg.audit.retention_days = retention;
    cfg.audit.log_llm_prompts = qs('#cfg-audit-log-prompts')?.checked ?? false;
    cfg.audit.log_tool_output = qs('#cfg-audit-log-output')?.checked ?? true;
    cfg.audit.redact_in_audit = qs('#cfg-audit-redact')?.checked ?? true;

    return cfg;
  }

  _saveForm() {
    this._doSave(this._collectForm());
  }

  _saveRaw() {
    const ta = qs('#config-raw-textarea');
    const errEl = qs('#config-raw-error');
    let parsed;
    try {
      parsed = JSON.parse(ta?.value || '{}');
    } catch (e) {
      if (errEl) { errEl.textContent = 'JSON parse error: ' + e.message; errEl.hidden = false; }
      return;
    }
    if (errEl) errEl.hidden = true;
    this._doSave(parsed);
  }

  _doSave(cfg) {
    this._ws.send('config.set', { config: cfg, hash: this._hash })
      .then(() => {
        this._config = cfg;
        const banner = qs('#config-save-banner');
        if (banner) banner.hidden = false;
        this._ws.send('config.get', {}).then(d => { this._hash = d.hash; }).catch(() => {});
      })
      .catch(err => {
        const msg = (err && err.message) ? err.message : 'Failed to save config.';
        const el = qs('#config-body');
        const errDiv = document.createElement('div');
        errDiv.className = 'panel-error';
        errDiv.textContent = msg;
        el?.prepend(errDiv);
        setTimeout(() => errDiv.remove(), 5000);
      });
  }

  _restart() {
    const btn = qs('#config-restart-btn');
    if (btn) btn.textContent = 'Restarting\u2026';
    this._ws.send('gateway.restart', {}).catch(() => {});
  }
}

function _cfgEsc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
