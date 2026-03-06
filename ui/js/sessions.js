/**
 * sessions.js — SessionsPanel: list, load, reset, compact, export.
 */

class SessionsPanel {
  constructor(ws, chat) {
    this._ws = ws;
    this._chat = chat;
    this._activeId = null;
  }

  load() {
    const container = qs('#sessions-list');
    if (!container) return;
    container.innerHTML = '<div class="panel-loading">Loading…</div>';

    fetch('/api/sessions')
      .then(r => r.json())
      .then(data => this._render(data.sessions || []))
      .catch(() => {
        if (container) container.innerHTML = '<div class="panel-empty">Failed to load sessions.</div>';
      });
  }

  _render(sessions) {
    const container = qs('#sessions-list');
    if (!container) return;

    if (!sessions.length) {
      container.innerHTML = '<div class="panel-empty">No sessions yet.</div>';
      return;
    }

    container.innerHTML = '';
    for (const s of sessions) {
      const item = el('div', {
        class: 'session-item' + (s.session_id === this._activeId ? ' session-item--active' : ''),
        title: s.session_id,
      });

      const top = el('div', { class: 'session-item__top' });
      const idEl = el('span', { class: 'session-item__id' });
      idEl.textContent = s.session_id.slice(0, 20) + (s.session_id.length > 20 ? '…' : '');
      const timeEl = el('span', { class: 'session-item__time' });
      timeEl.textContent = timeAgo(s.last_active);
      top.appendChild(idEl);
      top.appendChild(timeEl);

      const preview = el('div', { class: 'session-item__preview' });
      preview.textContent = s.preview || '(no messages)';

      item.appendChild(top);
      item.appendChild(preview);
      item.addEventListener('click', () => this._select(s.session_id));
      container.appendChild(item);
    }
  }

  _select(sessionId) {
    this._activeId = sessionId;
    // Re-render to update active state
    this.load();
    this._loadHistory(sessionId);
    this._renderToolbar(sessionId);
  }

  _loadHistory(sessionId) {
    fetch(`/api/sessions/${encodeURIComponent(sessionId)}`)
      .then(r => r.json())
      .then(data => {
        this._chat.renderHistory(data.events || []);
        // Switch to chat view
        const chatBtn = qs('[data-view="chat"]');
        if (chatBtn) chatBtn.click();
      })
      .catch(() => {
        this._chat.addSystemMessage('Failed to load session history.');
      });
  }

  _renderToolbar(sessionId) {
    const toolbar = qs('#session-toolbar');
    if (!toolbar) return;
    toolbar.hidden = false;
    qs('#session-toolbar-id').textContent = sessionId.slice(0, 24) + (sessionId.length > 24 ? '…' : '');

    const resetBtn = qs('#session-reset-btn');
    const compactBtn = qs('#session-compact-btn');
    const exportBtn = qs('#session-export-btn');

    resetBtn.onclick = () => this._reset(sessionId);
    compactBtn.onclick = () => this._compact(sessionId);
    exportBtn.onclick = () => this._export(sessionId);
  }

  async _reset(sessionId) {
    if (!confirm(`Reset session "${sessionId.slice(0, 20)}"? This clears all history.`)) return;
    try {
      await this._ws.send('sessions.reset', { session_id: sessionId });
      this._chat.clear();
      this._chat.addSystemMessage('Session reset.');
      this._activeId = null;
      qs('#session-toolbar').hidden = true;
      this.load();
    } catch (e) {
      this._chat.addSystemMessage('Reset failed: ' + e.message);
    }
  }

  async _compact(sessionId) {
    this._chat.addSystemMessage('Compacting session…');
    try {
      const res = await this._ws.send('sessions.compact', { session_id: sessionId });
      if (res.compacted > 0) {
        this._chat.addSystemMessage(`Compacted ${res.compacted} turns. Summary: ${res.summary}`);
      } else {
        this._chat.addSystemMessage(res.message || 'Nothing to compact.');
      }
    } catch (e) {
      this._chat.addSystemMessage('Compact failed: ' + e.message);
    }
  }

  _export(sessionId) {
    fetch(`/api/sessions/${encodeURIComponent(sessionId)}`)
      .then(r => r.json())
      .then(data => {
        const lines = (data.events || []).map(e => JSON.stringify(e)).join('\n');
        const blob = new Blob([lines], { type: 'application/jsonl' });
        const url = URL.createObjectURL(blob);
        const a = el('a', { href: url, download: `${sessionId}.jsonl` });
        document.body.appendChild(a);
        a.click();
        setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 1000);
      })
      .catch(() => alert('Export failed.'));
  }
}
