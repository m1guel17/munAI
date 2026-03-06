/**
 * cron.js — CronPanel: heartbeat scheduler management.
 */

class CronPanel {
  constructor(ws) {
    this._ws = ws;
  }

  load() {
    const el = qs('#cron-list');
    if (el) el.innerHTML = '<div class="panel-loading">Loading…</div>';
    this._ws.send('cron.list', {})
      .then(data => this._render(data.jobs || [], data.scheduler_running))
      .catch(() => {
        if (el) el.innerHTML = '<div class="panel-error">Failed to load cron jobs.</div>';
      });
  }

  _render(jobs, schedulerRunning) {
    const el = qs('#cron-list');
    if (!el) return;

    const badge = schedulerRunning
      ? '<span class="badge badge--on">Running</span>'
      : '<span class="badge badge--off">Stopped</span>';

    const header = qs('#cron-scheduler-status');
    if (header) header.innerHTML = 'Scheduler: ' + badge;

    if (!jobs.length) {
      el.innerHTML = '<div class="panel-empty">No scheduled jobs.</div>';
      return;
    }

    let html = '';
    for (const job of jobs) {
      const dotCls = job.is_running ? 'status-dot--running' : (job.enabled ? 'status-dot--on' : 'status-dot--off');
      const lastRun = job.last_run_at ? _timeAgo(job.last_run_at) : 'Never';
      const nextRun = job.next_run_at ? _timeAgo(job.next_run_at, true) : '—';
      html += `
        <div class="cron-job" data-id="${_cronEsc(job.id)}">
          <div class="cron-job__header">
            <span class="status-dot ${dotCls}"></span>
            <span class="cron-job__name">${_cronEsc(job.name)}</span>
            <span class="cron-job__interval">every ${_cronEsc(job.interval_minutes)} min</span>
            <div class="cron-job__actions">
              <button class="btn btn--secondary btn--sm cron-run-now-btn" data-id="${_cronEsc(job.id)}">Run Now</button>
              <button class="btn btn--secondary btn--sm cron-edit-btn" data-id="${_cronEsc(job.id)}">Edit</button>
            </div>
          </div>
          <div class="cron-job__timing">
            <span>Last run: <strong>${lastRun}</strong></span>
            <span>Next run: <strong>${nextRun}</strong></span>
            ${(job.run_history || []).length ? `<button class="btn btn--secondary btn--sm cron-history-btn" data-id="${_cronEsc(job.id)}">History</button>` : ''}
          </div>
          <div class="cron-history-table" data-id="${_cronEsc(job.id)}" hidden>
            ${_renderRunHistory(job.run_history || [])}
          </div>
          <div class="cron-edit-form" data-id="${_cronEsc(job.id)}" hidden>
            <div class="cron-edit-form__row">
              <label>Interval (minutes)</label>
              <input type="number" class="cron-interval-input" min="1" value="${_cronEsc(job.interval_minutes)}" />
            </div>
            <div class="cron-edit-form__row">
              <label>Ack keyword</label>
              <input type="text" class="cron-ack-input" value="${_cronEsc(job.ack_keyword || '')}" placeholder="HEARTBEAT_OK" />
            </div>
            <div class="cron-edit-form__row">
              <label>
                <input type="checkbox" class="cron-enabled-cb" ${job.enabled ? 'checked' : ''} />
                Enabled
              </label>
            </div>
            <button class="btn btn--primary btn--sm cron-save-btn" data-id="${_cronEsc(job.id)}">Save</button>
            <button class="btn btn--secondary btn--sm cron-cancel-btn" data-id="${_cronEsc(job.id)}">Cancel</button>
          </div>
        </div>`;
    }
    el.innerHTML = html;

    // History toggle
    el.querySelectorAll('.cron-history-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const table = el.querySelector(`.cron-history-table[data-id="${btn.dataset.id}"]`);
        if (table) table.hidden = !table.hidden;
      });
    });

    // Run Now
    el.querySelectorAll('.cron-run-now-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        this._ws.send('cron.run_now', { id: btn.dataset.id })
          .then(() => _showToast('Heartbeat triggered'))
          .catch(() => _showToast('Failed to trigger', true));
      });
    });

    // Edit toggle
    el.querySelectorAll('.cron-edit-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const form = el.querySelector(`.cron-edit-form[data-id="${btn.dataset.id}"]`);
        if (form) form.hidden = !form.hidden;
      });
    });

    // Save
    el.querySelectorAll('.cron-save-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const form = el.querySelector(`.cron-edit-form[data-id="${btn.dataset.id}"]`);
        if (!form) return;
        const interval = parseInt(form.querySelector('.cron-interval-input')?.value || '0', 10);
        const ack = form.querySelector('.cron-ack-input')?.value || '';
        const enabled = form.querySelector('.cron-enabled-cb')?.checked ?? true;
        this._ws.send('cron.update', {
          id: btn.dataset.id,
          interval_minutes: interval || undefined,
          ack_keyword: ack,
          enabled,
        })
          .then(() => { form.hidden = true; this.load(); })
          .catch(() => _showToast('Failed to save', true));
      });
    });

    // Cancel
    el.querySelectorAll('.cron-cancel-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const form = el.querySelector(`.cron-edit-form[data-id="${btn.dataset.id}"]`);
        if (form) form.hidden = true;
      });
    });
  }
}

function _renderRunHistory(history) {
  if (!history.length) return '<div class="panel-empty">No runs yet.</div>';
  let html = '<table class="cron-history"><thead><tr><th>Started</th><th>Duration</th><th>Outcome</th></tr></thead><tbody>';
  for (const run of history.slice().reverse()) {
    const time = run.started_at ? new Date(run.started_at).toLocaleTimeString() : '—';
    const dur = run.duration_ms != null ? run.duration_ms + 'ms' : '—';
    const outcome = run.ok
      ? '<span class="badge badge--on">ok</span>'
      : `<span class="badge badge--off" title="${_cronEsc(run.error || '')}">error</span>`;
    html += `<tr><td>${_cronEsc(time)}</td><td>${_cronEsc(dur)}</td><td>${outcome}</td></tr>`;
  }
  html += '</tbody></table>';
  return html;
}

function _timeAgo(isoString, future = false) {
  const date = new Date(isoString);
  const diff = Math.round((Date.now() - date.getTime()) / 1000);
  if (future) {
    const absDiff = Math.abs(diff);
    if (absDiff < 60) return `in ${absDiff}s`;
    if (absDiff < 3600) return `in ${Math.round(absDiff / 60)}m`;
    return `in ${Math.round(absDiff / 3600)}h`;
  }
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  return `${Math.round(diff / 3600)}h ago`;
}

function _showToast(msg, error = false) {
  const toast = document.createElement('div');
  toast.className = 'toast' + (error ? ' toast--error' : '');
  toast.textContent = msg;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 2500);
}

function _cronEsc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
