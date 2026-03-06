/**
 * ws.js — WebSocket client with reconnection and request/response matching.
 */

class WsClient {
  constructor() {
    this._ws = null;
    this._clientId = this._getOrCreateClientId();
    this._pending = new Map();   // requestId → { resolve, reject }
    this._handlers = new Map();  // event name → [handler, ...]
    this._seq = 0;
    this._reconnectDelay = 1000;
    this._maxReconnectDelay = 30000;
    this._connected = false;
    this._connecting = false;
    this._stopped = false;
  }

  get clientId() { return this._clientId; }
  get connected() { return this._connected; }

  _getOrCreateClientId() {
    let id = localStorage.getItem('munai_client_id');
    if (!id) {
      id = uuidv4();
      localStorage.setItem('munai_client_id', id);
    }
    return id;
  }

  connect() {
    if (this._connecting || this._stopped) return;
    this._connecting = true;

    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const url = `${proto}://${location.host}/ws`;

    this._ws = new WebSocket(url);

    this._ws.onopen = () => {
      // Send connect handshake
      const token = localStorage.getItem('munai_gateway_token') || undefined;
      this._ws.send(JSON.stringify({
        type: 'connect',
        client_id: this._clientId,
        client_type: 'webchat',
        auth: { token: token || null },
      }));
    };

    this._ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      this._onMessage(msg);
    };

    this._ws.onerror = () => {
      // onerror is always followed by onclose; handle reconnect there
    };

    this._ws.onclose = () => {
      this._connected = false;
      this._connecting = false;
      this._emit('_status', { connected: false });

      // Reject all pending requests
      for (const [, { reject }] of this._pending) {
        reject(new Error('WebSocket disconnected'));
      }
      this._pending.clear();

      if (!this._stopped) {
        setTimeout(() => this.connect(), this._reconnectDelay);
        this._reconnectDelay = Math.min(this._reconnectDelay * 2, this._maxReconnectDelay);
      }
    };
  }

  _onMessage(msg) {
    if (msg.type === 'res') {
      const p = this._pending.get(msg.id);
      if (p) {
        this._pending.delete(msg.id);
        if (msg.ok) p.resolve(msg.payload);
        else p.reject(new Error(msg.error || 'Request failed'));
      }
      // First successful res after connect means we're authenticated
      if (!this._connected) {
        this._connected = true;
        this._reconnectDelay = 1000; // reset backoff on successful connection
        this._connecting = false;
        this._emit('_status', { connected: true });
      }
    } else if (msg.type === 'event') {
      this._emit(msg.event, msg.payload);
      // Also emit a wildcard for any event listener
      this._emit('*', { event: msg.event, payload: msg.payload });
      if (!this._connected) {
        this._connected = true;
        this._reconnectDelay = 1000;
        this._connecting = false;
        this._emit('_status', { connected: true });
      }
    }
  }

  /**
   * Send a request and return a Promise that resolves with the response payload.
   */
  send(method, params = {}) {
    return new Promise((resolve, reject) => {
      if (!this._ws || this._ws.readyState !== WebSocket.OPEN) {
        reject(new Error('Not connected'));
        return;
      }
      const id = uuidv4();
      const idempotencyKey = (method === 'agent' || method === 'send')
        ? uuidv4()
        : undefined;
      this._pending.set(id, { resolve, reject });
      this._ws.send(JSON.stringify({
        type: 'req',
        id,
        method,
        params,
        idempotency_key: idempotencyKey,
      }));
    });
  }

  /**
   * Subscribe to a server-pushed event or internal status event.
   * event: 'agent.delta' | 'agent.done' | '_status' | '*' | etc.
   */
  on(event, handler) {
    if (!this._handlers.has(event)) this._handlers.set(event, []);
    this._handlers.get(event).push(handler);
    return () => this.off(event, handler);
  }

  off(event, handler) {
    const list = this._handlers.get(event);
    if (list) {
      const idx = list.indexOf(handler);
      if (idx !== -1) list.splice(idx, 1);
    }
  }

  _emit(event, payload) {
    const list = this._handlers.get(event);
    if (list) list.forEach(h => h(payload));
  }

  disconnect() {
    this._stopped = true;
    if (this._ws) this._ws.close();
  }
}
