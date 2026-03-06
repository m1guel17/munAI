/**
 * skills.js — SkillsPanel: browse installed workspace skills.
 */

class SkillsPanel {
  constructor(ws) {
    this._ws = ws;
  }

  load() {
    const el = qs('#skills-list');
    if (el) el.innerHTML = '<div class="panel-loading">Loading\u2026</div>';
    this._ws.send('skills.list', {})
      .then(data => this._render(data.skills || []))
      .catch(() => {
        if (el) el.innerHTML = '<div class="panel-error">Failed to load skills.</div>';
      });
  }

  _render(skills) {
    const el = qs('#skills-list');
    if (!el) return;
    if (!skills.length) {
      el.innerHTML = `
        <div class="panel-empty">
          No skills installed.<br>
          <span class="panel-empty__hint">Add skill files to <code>~/.munai/workspace/skills/</code></span>
        </div>`;
      return;
    }
    let html = '';
    for (const s of skills) {
      const tags = (s.tags || []).map(t => `<span class="skill-tag">${_sEsc(t)}</span>`).join('');
      const missingBadge = s.missing_env && s.missing_env.length
        ? `<span class="badge badge--warn" title="Missing: ${_sEsc(s.missing_env.join(', '))}">&#9888; missing env</span>`
        : '';
      const readyBadge = s.required_env && s.required_env.length && (!s.missing_env || !s.missing_env.length)
        ? '<span class="badge badge--on">ready</span>'
        : '';

      // Build set-key forms for missing env vars
      let setKeyForms = '';
      for (const key of (s.missing_env || [])) {
        setKeyForms += `
          <div class="skill-env-row" data-key="${_sEsc(key)}">
            <span class="skill-env-row__key">${_sEsc(key)}</span>
            <input type="password" class="skill-env-input" placeholder="Enter value\u2026" autocomplete="off" />
            <button class="btn btn--primary btn--sm skill-env-save-btn" data-key="${_sEsc(key)}" data-skill="${_sEsc(s.name)}">Set</button>
          </div>`;
      }

      html += `
        <div class="skill-item">
          <div class="skill-item__header" data-skill="${_sEsc(s.name)}">
            ${s.trigger ? `<span class="skill-item__trigger">${_sEsc(s.trigger)}</span>` : ''}
            <span class="skill-item__name">${_sEsc(s.name)}</span>
            ${tags}
            ${missingBadge}${readyBadge}
            <span class="skill-item__chevron">&#9656;</span>
          </div>
          <div class="skill-item__desc">${_sEsc(s.description || '')}</div>
          <div class="skill-item__body" hidden>
            ${setKeyForms ? `<div class="skill-env-section">
              <strong>Missing environment variables:</strong>
              ${setKeyForms}
            </div>` : ''}
            ${s.content ? `<div class="skill-item__content">${_renderSkillMd(s.content)}</div>` : ''}
          </div>
        </div>`;
    }
    el.innerHTML = html;

    el.querySelectorAll('.skill-item__header').forEach(header => {
      header.addEventListener('click', () => {
        const item = header.closest('.skill-item');
        const body = item?.querySelector('.skill-item__body');
        const chevron = item?.querySelector('.skill-item__chevron');
        if (!body) return;
        const open = !body.hidden;
        body.hidden = open;
        if (chevron) chevron.innerHTML = open ? '&#9656;' : '&#9662;';
      });
    });

    el.querySelectorAll('.skill-env-save-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const row = btn.closest('.skill-env-row');
        const input = row?.querySelector('.skill-env-input');
        const key = btn.dataset.key;
        const value = input?.value || '';
        if (!value) return;
        this._ws.send('skills.set_env', { key, value })
          .then(() => {
            if (row) row.innerHTML = `<span class="skill-env-row__key">${_sEsc(key)}</span> <span class="badge badge--on">saved</span>`;
          })
          .catch(() => {
            if (btn) btn.textContent = 'Failed';
          });
      });
    });
  }
}

function _renderSkillMd(content) {
  if (typeof marked !== 'undefined') {
    return marked.parse(content);
  }
  return '<pre>' + _sEsc(content) + '</pre>';
}

function _sEsc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
