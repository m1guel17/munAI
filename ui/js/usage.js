/**
 * usage.js — UsagePanel: cost & token tracking from audit events.
 */

class UsagePanel {
  constructor() {}

  load() {
    this._fetchAndRender();
  }

  async _fetchAndRender() {
    const today = new Date().toISOString().slice(0, 10);

    // Fetch last 30 days of agent.model_call events
    // We use the HTTP endpoint since we need to scan multiple dates
    const events = await this._fetchRecentCalls(30);
    this._render(events, today);
  }

  async _fetchRecentCalls(days) {
    const calls = [];
    const now = new Date();
    const fetches = [];
    for (let i = 0; i < days; i++) {
      const d = new Date(now);
      d.setDate(d.getDate() - i);
      const dateStr = d.toISOString().slice(0, 10);
      fetches.push(
        fetch(`/api/audit?date=${dateStr}&type=agent.model_call&limit=1000`)
          .then(r => r.json())
          .then(data => data.events || [])
          .catch(() => [])
      );
    }
    const results = await Promise.all(fetches);
    for (const batch of results) calls.push(...batch);
    return calls;
  }

  _render(events, today) {
    const thisMonth = today.slice(0, 7); // YYYY-MM

    const todayEvents = events.filter(e => (e.timestamp || '').startsWith(today));
    const monthEvents = events.filter(e => (e.timestamp || '').startsWith(thisMonth));

    const summarize = (evs) => {
      let calls = evs.length;
      let tokensIn = 0, tokensOut = 0, cost = 0;
      for (const e of evs) {
        const d = e.detail || {};
        tokensIn += d.tokens_in || d.prompt_tokens || 0;
        tokensOut += d.tokens_out || d.completion_tokens || 0;
        cost += d.cost_usd || 0;
      }
      return { calls, tokensIn, tokensOut, cost };
    };

    const todayStat = summarize(todayEvents);
    const monthStat = summarize(monthEvents);
    const allStat = summarize(events);

    const hasCostData = allStat.tokensIn > 0 || allStat.cost > 0;

    // Summary cards
    const summaryEl = qs('#usage-summary');
    if (summaryEl) {
      summaryEl.innerHTML = `
        ${this._summaryCard('Today', todayStat, hasCostData)}
        ${this._summaryCard('This Month', monthStat, hasCostData)}
        ${this._summaryCard('All Time (30d)', allStat, hasCostData)}
      `;
    }

    // Breakdown table by provider/model
    const breakdownEl = qs('#usage-breakdown');
    if (breakdownEl) {
      if (!events.length) {
        breakdownEl.innerHTML = '<div class="panel-empty">No usage data yet. Start chatting to see stats here.</div>';
        return;
      }

      const byKey = {};
      for (const e of events) {
        const d = e.detail || {};
        const key = `${d.provider || '?'}|||${d.model || '?'}`;
        if (!byKey[key]) byKey[key] = { provider: d.provider || '?', model: d.model || '?', calls: 0, tokensIn: 0, tokensOut: 0, cost: 0 };
        byKey[key].calls++;
        byKey[key].tokensIn += d.tokens_in || d.prompt_tokens || 0;
        byKey[key].tokensOut += d.tokens_out || d.completion_tokens || 0;
        byKey[key].cost += d.cost_usd || 0;
      }

      const rows = Object.values(byKey).sort((a, b) => b.calls - a.calls);
      const tbody = rows.map(r => `
        <tr>
          <td>${r.provider}</td>
          <td>${r.model}</td>
          <td>${formatNumber(r.calls)}</td>
          <td>${hasCostData ? formatNumber(r.tokensIn) + ' / ' + formatNumber(r.tokensOut) : '—'}</td>
          <td>${hasCostData && r.cost > 0 ? '$' + r.cost.toFixed(4) : '—'}</td>
        </tr>
      `).join('');

      breakdownEl.innerHTML = `
        <table class="usage-table">
          <thead>
            <tr>
              <th>Provider</th><th>Model</th><th>Calls</th>
              <th>Tokens (in/out)</th><th>Cost</th>
            </tr>
          </thead>
          <tbody>${tbody}</tbody>
        </table>
        ${!hasCostData ? '<p class="usage-note">Token and cost data not yet recorded. Will appear after next update.</p>' : ''}
      `;
    }
  }

  _summaryCard(label, stat, hasCostData) {
    return `
      <div class="usage-card">
        <div class="usage-card__label">${label}</div>
        <div class="usage-card__cost">${hasCostData && stat.cost > 0 ? '$' + stat.cost.toFixed(4) : '—'}</div>
        <div class="usage-card__stat">${formatNumber(stat.calls)} calls</div>
        ${hasCostData ? `<div class="usage-card__stat">${formatNumber(stat.tokensIn + stat.tokensOut)} tokens</div>` : ''}
      </div>
    `;
  }
}
