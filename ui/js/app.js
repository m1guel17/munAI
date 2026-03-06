/**
 * app.js — Entry point: initialize all UI components, wire up events.
 */

(function () {
  'use strict';

  const ws        = new WsClient();
  const messagesEl = qs('#messages');
  const inputEl   = qs('#user-input');
  const sendBtn   = qs('#send-btn');
  const stopBtn   = qs('#stop-btn');
  const statusDot = qs('#status-dot');
  const mobileDot = qs('#mobile-status-dot');

  const chat          = new ChatPanel(messagesEl);
  const sessionsPanel = new SessionsPanel(ws, chat);
  const healthPanel   = new HealthPanel(ws);
  const auditPanel    = new AuditPanel(ws);
  const usagePanel    = new UsagePanel();
  const toolsPanel    = new ToolsPanel(ws);
  const skillsPanel   = new SkillsPanel(ws);
  const channelsPanel = new ChannelsPanel(ws);
  const cronPanel     = new CronPanel(ws);
  const configPanel   = new ConfigPanel(ws);
  const doctorPanel   = new DoctorPanel(ws);
  const devicesPanel  = new DevicesPanel(ws);

  // ── Nav routing ──────────────────────────────────────────────────────────

  const navBtns = qsa('.nav-btn');
  navBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const viewId = btn.dataset.view;
      navBtns.forEach(b => b.classList.remove('nav-btn--active'));
      btn.classList.add('nav-btn--active');
      qsa('.view').forEach(v => v.classList.remove('view--active'));
      const target = qs('#view-' + viewId);
      if (target) target.classList.add('view--active');

      if (viewId === 'sessions')  sessionsPanel.load();
      if (viewId === 'health')    healthPanel.load();
      if (viewId === 'audit')     auditPanel.load();
      if (viewId === 'usage')     usagePanel.load();
      if (viewId === 'tools')     toolsPanel.load();
      if (viewId === 'skills')    skillsPanel.load();
      if (viewId === 'channels')  { channelsPanel.load(); channelsPanel.startAutoRefresh(); }
      if (viewId === 'cron')      cronPanel.load();
      if (viewId === 'config')    configPanel.load();
      if (viewId === 'doctor')    doctorPanel.load();
      if (viewId === 'devices')   devicesPanel.load();
      if (viewId !== 'channels')  channelsPanel.stopAutoRefresh();

      qs('#sidebar')?.classList.remove('sidebar--open');
    });
  });

  qs('#sessions-refresh-btn')?.addEventListener('click', () => sessionsPanel.load());
  qs('#health-refresh-btn')?.addEventListener('click', () => healthPanel.load());
  qs('#usage-refresh-btn')?.addEventListener('click', () => usagePanel.load());
  qs('#tools-refresh-btn')?.addEventListener('click', () => toolsPanel.load());
  qs('#skills-refresh-btn')?.addEventListener('click', () => skillsPanel.load());
  qs('#channels-refresh-btn')?.addEventListener('click', () => channelsPanel.load());
  qs('#cron-refresh-btn')?.addEventListener('click', () => cronPanel.load());
  qs('#config-refresh-btn')?.addEventListener('click', () => configPanel.load());
  qs('#doctor-refresh-btn')?.addEventListener('click', () => doctorPanel.load());
  qs('#devices-refresh-btn')?.addEventListener('click', () => devicesPanel.load());

  // ── Tools panel tab wiring ────────────────────────────────────────────────

  qsa('.panel-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      toolsPanel.switchTab(tab.dataset.tab);
    });
  });

  // ── Kill switch ───────────────────────────────────────────────────────────

  let _emergencyStopped = false;

  qs('#kill-switch-btn')?.addEventListener('click', () => {
    if (_emergencyStopped) {
      ws.send('gateway.emergency_stop', {}).catch(() => {});
      return;
    }
    qs('#kill-switch-modal').hidden = false;
  });

  qs('#kill-confirm-btn')?.addEventListener('click', () => {
    qs('#kill-switch-modal').hidden = true;
    ws.send('gateway.emergency_stop', {}).catch(() => {});
  });

  qs('#kill-cancel-btn')?.addEventListener('click', () => {
    qs('#kill-switch-modal').hidden = true;
  });

  ws.on('gateway.emergency_stopped', ({ stopped }) => {
    _emergencyStopped = stopped;
    const btn = qs('#kill-switch-btn');
    if (btn) {
      btn.classList.toggle('kill-switch-btn--active', stopped);
      btn.textContent = stopped ? '\u25BA Resume' : '\u25A0 Kill Switch';
    }
  });

  // ── Theme toggle ─────────────────────────────────────────────────────────

  const savedTheme = localStorage.getItem('munai_theme') || 'dark';
  document.documentElement.setAttribute('data-theme', savedTheme);

  qs('#theme-toggle')?.addEventListener('click', () => {
    const current = document.documentElement.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('munai_theme', next);
  });

  // ── Mobile hamburger ─────────────────────────────────────────────────────

  qs('#hamburger-btn')?.addEventListener('click', () => {
    qs('#sidebar')?.classList.toggle('sidebar--open');
  });

  // ── Connection status ────────────────────────────────────────────────────

  function setStatus(connected) {
    const cls = 'dot--' + (connected ? 'connected' : 'disconnected');
    if (statusDot) statusDot.className = 'dot ' + cls;
    if (mobileDot) mobileDot.className = 'dot ' + cls;
    if (sendBtn) sendBtn.disabled = !connected;
  }

  ws.on('_status', ({ connected }) => {
    setStatus(connected);
    if (connected) {
      inputEl?.focus();
      sessionsPanel.load();
    }
  });

  // ── Streaming ────────────────────────────────────────────────────────────

  ws.on('agent.delta', ({ text }) => {
    if (text) chat.onDelta(text);
  });

  ws.on('agent.done', ({ text, error, model, tokens_in, tokens_out }) => {
    chat.onDone(text, !!error);
    chat.setStreaming(false);
    if (sendBtn) sendBtn.disabled = !ws.connected;
    inputEl?.removeAttribute('disabled');
    inputEl?.focus();
    if (model || tokens_in != null) {
      chat.updateFooter(model, _currentSessionKey, tokens_in, tokens_out);
    }
  });

  // ── Tool events ──────────────────────────────────────────────────────────

  ws.on('agent.tool_start', ({ tool, tool_call_id, params }) => {
    const id = tool_call_id || tool;
    chat.addToolCard(id, tool, params);
  });

  ws.on('agent.tool_end', ({ tool_call_id, tool, result, error }) => {
    const id = tool_call_id || tool;
    chat.updateToolCard(id, result || error || '', !!error);
  });

  // ── Approval ─────────────────────────────────────────────────────────────

  let _currentApprovalId = null;

  ws.on('tool.approval_requested', ({ approval_id, command }) => {
    _currentApprovalId = approval_id;
    const banner = qs('#approval-banner');
    const commandEl = qs('#approval-command');
    if (!banner || !commandEl) return;
    commandEl.textContent = Array.isArray(command) ? command.join(' ') : String(command);
    banner.hidden = false;
    qs('#approval-approve-btn')?.focus();
  });

  function _respondApproval(approved) {
    if (!_currentApprovalId) return;
    const method = approved ? 'tool.approve' : 'tool.deny';
    ws.send(method, { approval_id: _currentApprovalId }).catch(e => {
      console.warn('Approval response failed:', e.message);
    });
    _currentApprovalId = null;
    const banner = qs('#approval-banner');
    if (banner) banner.hidden = true;
  }

  qs('#approval-approve-btn')?.addEventListener('click', () => _respondApproval(true));
  qs('#approval-deny-btn')?.addEventListener('click',   () => _respondApproval(false));

  // ── Send message ─────────────────────────────────────────────────────────

  let _currentSessionKey = null;

  function sendMessage() {
    const text = inputEl?.value.trim();
    if (!text || !ws.connected) return;

    chat.addUserMessage(text);
    if (inputEl) inputEl.value = '';
    autoResize();
    chat.setStreaming(true);
    if (sendBtn) sendBtn.disabled = true;

    ws.send('agent', { text }).catch(err => {
      chat.onDone('Failed to send: ' + err.message, true);
      chat.setStreaming(false);
      if (sendBtn) sendBtn.disabled = !ws.connected;
    });
  }

  sendBtn?.addEventListener('click', sendMessage);

  stopBtn?.addEventListener('click', () => {
    ws.send('agent.abort', { session_key: _currentSessionKey || '' }).catch(() => {});
  });

  inputEl?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // ── Auto-resize textarea ─────────────────────────────────────────────────

  function autoResize() {
    if (!inputEl) return;
    inputEl.style.height = 'auto';
    inputEl.style.height = Math.min(inputEl.scrollHeight, 160) + 'px';
  }
  inputEl?.addEventListener('input', autoResize);

  // ── Initialize ───────────────────────────────────────────────────────────

  setStatus(false);
  if (sendBtn) sendBtn.disabled = true;
  ws.connect();

})();
