/**
 * chat.js — ChatPanel: message rendering and streaming display.
 */

class ChatPanel {
  constructor(messagesEl) {
    this._container = messagesEl;
    this._currentAssistantBubble = null;
    this._currentAssistantText = '';
    this._toolCards = new Map(); // tool_call_id → card element
  }

  /**
   * Append a user message to the chat.
   */
  addUserMessage(text) {
    const msg = this._createMessage('user');
    // textContent is safe — no XSS risk from user's own input
    msg.bubble.textContent = text;
    this._container.appendChild(msg.wrapper);
    this._scrollToBottom();
  }

  /**
   * Called on 'agent.delta' — start or extend the current assistant message.
   * Uses textContent (not innerHTML) during streaming for XSS safety.
   */
  onDelta(text) {
    if (!this._currentAssistantBubble) {
      const msg = this._createMessage('assistant');
      msg.bubble.classList.add('message__bubble--streaming');
      this._container.appendChild(msg.wrapper);
      this._currentAssistantBubble = msg.bubble;
      this._currentAssistantText = '';
    }
    this._currentAssistantText += text;
    // textContent: safe during high-frequency streaming (no XSS, no layout thrash)
    this._currentAssistantBubble.textContent = this._currentAssistantText;
    this._scrollToBottom();
  }

  /**
   * Called on 'agent.done' — finalize the assistant message with markdown rendering.
   * Switches from textContent to innerHTML only after streaming is complete.
   */
  onDone(text, isError = false) {
    if (!this._currentAssistantBubble) {
      // Response arrived without deltas (e.g. very short reply)
      const msg = this._createMessage('assistant');
      this._currentAssistantBubble = msg.bubble;
      this._container.appendChild(msg.wrapper);
    }

    this._currentAssistantBubble.classList.remove('message__bubble--streaming');

    if (isError) {
      this._currentAssistantBubble.textContent = text || 'An error occurred.';
      this._currentAssistantBubble.closest('.message')?.classList.add('message--error');
    } else {
      const finalText = text || this._currentAssistantText;
      if (typeof marked !== 'undefined' && finalText) {
        // marked.parse returns safe HTML when input is trusted (our own LLM output)
        this._currentAssistantBubble.innerHTML = marked.parse(finalText);
      } else {
        this._currentAssistantBubble.textContent = finalText;
      }
    }

    this._currentAssistantBubble = null;
    this._currentAssistantText = '';
    this._scrollToBottom();
  }

  /**
   * Show a system/status message (e.g. "Reconnecting...")
   */
  addSystemMessage(text) {
    const wrapper = el('div', { class: 'message message--system' });
    const bubble = el('div', { class: 'message__bubble' });
    bubble.textContent = text;
    wrapper.appendChild(bubble);
    this._container.appendChild(wrapper);
    this._scrollToBottom();
  }

  /**
   * Insert a collapsible tool call card (running state).
   * @param {string} id  — unique card id (tool_call_id or random)
   * @param {string} tool — tool name
   * @param {object} params — tool params for display
   */
  addToolCard(id, tool, params) {
    this.clearToolIndicator();

    const card = el('div', { class: 'tool-card tool-card--running', id: 'tool-card-' + id });
    const header = el('div', { class: 'tool-card__header' });
    const icon = el('span', { class: 'tool-card__icon' });
    icon.textContent = '⚙';
    const name = el('span', { class: 'tool-card__name' });
    name.textContent = tool;
    const status = el('span', { class: 'tool-card__status' });
    status.textContent = '● running…';
    header.appendChild(icon);
    header.appendChild(name);
    header.appendChild(status);

    const body = el('div', { class: 'tool-card__body' });
    if (params && Object.keys(params).length) {
      const paramsEl = el('pre', { class: 'tool-card__output' });
      paramsEl.textContent = JSON.stringify(params, null, 2);
      body.appendChild(paramsEl);
    }
    body.hidden = true;

    header.addEventListener('click', () => { body.hidden = !body.hidden; });

    card.appendChild(header);
    card.appendChild(body);
    this._container.appendChild(card);
    this._toolCards.set(id, { card, header, status, body, startTime: Date.now() });
    this._scrollToBottom();
  }

  /**
   * Update a tool card to done or error state.
   * @param {string} id   — same id passed to addToolCard
   * @param {string} result — tool output text
   * @param {boolean} isError
   */
  updateToolCard(id, result, isError) {
    const entry = this._toolCards.get(id);
    if (!entry) return;

    const { card, header, status, body } = entry;
    const duration = Date.now() - entry.startTime;

    card.classList.remove('tool-card--running');
    card.classList.add(isError ? 'tool-card--error' : 'tool-card--done');

    const timing = el('span', { class: 'tool-card__timing' });
    timing.textContent = duration + 'ms';
    header.appendChild(timing);
    status.textContent = isError ? '✗' : '✓';

    if (result) {
      const output = el('pre', { class: 'tool-card__output' });
      output.textContent = result;
      body.appendChild(output);
      if (isError) body.hidden = false;
    }
  }

  /** @deprecated Use addToolCard/updateToolCard instead. Legacy indicator fallback. */
  addToolIndicator(label) {
    this.clearToolIndicator();
    const wrapper = el('div', { class: 'message message--tool', id: 'tool-indicator' });
    const bubble = el('div', { class: 'message__bubble' });
    bubble.textContent = '⚙ ' + label;
    wrapper.appendChild(bubble);
    this._container.appendChild(wrapper);
    this._scrollToBottom();
  }

  clearToolIndicator() {
    const existing = document.getElementById('tool-indicator');
    if (existing) existing.remove();
  }

  /**
   * Toggle streaming state — swaps send button ↔ stop button and disables input.
   */
  setStreaming(isStreaming) {
    const sendBtn = qs('#send-btn');
    const stopBtn = qs('#stop-btn');
    const input = qs('#user-input');
    if (sendBtn) sendBtn.hidden = isStreaming;
    if (stopBtn) stopBtn.hidden = !isStreaming;
    if (input) input.disabled = isStreaming;
  }

  /**
   * Update the footer bar with current model / session / token info.
   */
  updateFooter(model, sessionName, tokensIn, tokensOut) {
    const modelEl = qs('#footer-model');
    const sessionEl = qs('#footer-session');
    const tokensEl = qs('#footer-tokens');
    const tokensSep = qs('#footer-tokens-sep');
    if (modelEl && model) modelEl.textContent = model;
    if (sessionEl && sessionName) sessionEl.textContent = sessionName;
    if (tokensEl && tokensIn != null && tokensOut != null) {
      tokensEl.textContent = '\u2248' + _fmtN(tokensIn) + ' in / ' + _fmtN(tokensOut) + ' out';
      if (tokensSep) tokensSep.hidden = false;
    }
  }

  _createMessage(role) {
    const wrapper = el('div', { class: `message message--${role}` });
    const roleLabel = el('span', { class: 'message__role' }, role === 'user' ? 'You' : 'Munai');
    const bubble = el('div', { class: 'message__bubble' });
    wrapper.appendChild(roleLabel);
    wrapper.appendChild(bubble);
    return { wrapper, bubble };
  }

  _scrollToBottom() {
    this._container.scrollTop = this._container.scrollHeight;
  }

  /**
   * Render a past session's events into the chat panel.
   */
  renderHistory(events) {
    this.clear();
    this.addSystemMessage('— Session history —');
    for (const event of events) {
      if (event.type === 'user') {
        this.addUserMessage(event.text || '');
      } else if (event.type === 'assistant') {
        this.onDone(event.text || '', false);
      }
    }
  }

  clear() {
    this._container.innerHTML = '';
    this._currentAssistantBubble = null;
    this._currentAssistantText = '';
    this._toolCards.clear();
  }
}

function _fmtN(n) {
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
  return String(n);
}
