/* MoodSync Insights: charts drawn with plain HTML/CSS/SVG (no chart library, so it works offline too).
   All numbers come from GET /api/insights (computed in backend/insights.py). */
(() => {
  'use strict';
  const MS = window.MS; if (!MS) return;
  const { api, escapeHtml: esc, $ } = MS;
  const COL = { happy: '#f6c453', energetic: '#ff8a5b', calm: '#6cc5a1', low: '#8d94e8' };
  const EMO = { happy: '☀️', energetic: '⚡', calm: '🌿', low: '🌧️' };
  const MOODS = ['happy', 'energetic', 'calm', 'low'];
  let loaded = false;

  const kpi = (label, value, sub = '') => `<div class="kpi"><span>${label}</span><strong>${value}</strong>${sub ? `<small>${sub}</small>` : ''}</div>`;
  const hbar = (label, pct, right, dim = false) => `<div class="hb ${dim ? 'dim' : ''}"><span>${label}</span><div class="hb-track"><i style="width:${Math.max(0, Math.min(100, pct))}%"></i></div><b>${right}</b></div>`;
  const card = (eyebrow, title, body, cls = '') => `<article class="card ins-card ${cls}"><p class="eyebrow">${eyebrow}</p><h2>${title}</h2>${body}</article>`;
  const empty = t => `<div class="empty-state">${t}</div>`;

  function donut(counts) {
    const total = MOODS.reduce((a, m) => a + (counts[m] || 0), 0); if (!total) return empty('No check-ins yet. Your first one will show up here.');
    let acc = 0; const stops = MOODS.filter(m => counts[m]).map(m => { const a = acc / total * 360; acc += counts[m]; return `${COL[m]} ${a}deg ${acc / total * 360}deg`; });
    return `<div class="donut-row"><div class="mix-donut" style="background:conic-gradient(${stops.join(',')})"><div><strong>${total}</strong><small>check-ins</small></div></div>
      <div class="legend">${MOODS.map(m => `<div><i style="background:${COL[m]}"></i>${EMO[m]} ${m}<b>${counts[m] || 0}</b></div>`).join('')}</div></div>`;
  }
  function strip(days) {
    return `<div class="strip">${days.map(d => `<i style="background:${d.mood ? COL[d.mood] : '#eee8f4'}" title="${d.date}: ${d.mood || 'no check-in'}"></i>`).join('')}</div>
      <p class="tiny-note">Last 28 days, oldest to newest. Grey = no check-in.</p>`;
  }
  function heat(matrix, cols) {
    const max = Math.max(1, ...cols.flatMap(c => MOODS.map(m => matrix[c][m])));
    return `<div class="heat" style="grid-template-columns:34px repeat(${cols.length},1fr)"><span></span>${cols.map(c => `<b>${c}</b>`).join('')}
      ${MOODS.map(m => `<span>${EMO[m]}</span>${cols.map(c => { const n = matrix[c][m]; return `<i title="${c} · ${m}: ${n}" style="background:${n ? COL[m] : '#f3eff8'};opacity:${n ? 0.25 + 0.75 * n / max : 1}">${n || ''}</i>`; }).join('')}`).join('')}</div>`;
  }
  function dual(rows) {
    const W = 560, H = 150, pad = 20, bw = (W - pad * 2) / rows.length, max = Math.max(1, ...rows.flatMap(r => [r.created, r.completed])), h = v => (H - 44) * v / max;
    return `<div class="svg-wrap"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Tasks created and completed per day, last 14 days"><line x1="${pad}" x2="${W - pad}" y1="${H - 24}" y2="${H - 24}" stroke="#e8e1f1"/>
      ${rows.map((r, i) => { const x = pad + i * bw, b = bw * 0.36, d = new Date(r.date + 'T00:00:00');
        return `<rect x="${x + bw * 0.1}" y="${H - 24 - h(r.created)}" width="${b}" height="${h(r.created)}" rx="3" fill="#e4d9f7"><title>${r.date}: ${r.created} added</title></rect>
          <rect x="${x + bw * 0.1 + b + 2}" y="${H - 24 - h(r.completed)}" width="${b}" height="${h(r.completed)}" rx="3" fill="#8c6ad5"><title>${r.date}: ${r.completed} done</title></rect>
          ${i % 2 === 0 || i === rows.length - 1 ? `<text x="${x + bw / 2}" y="${H - 8}" font-size="9" text-anchor="middle" fill="#9a90a8">${d.getDate()}/${d.getMonth() + 1}</text>` : ''}`; }).join('')}</svg>
      <div class="legend inline"><div><i style="background:#e4d9f7"></i>added</div><div><i style="background:#8c6ad5"></i>completed</div></div></div>`;
  }
  const rateRows = (obj, labelFn) => { const ks = Object.keys(obj).filter(k => obj[k].total); return ks.length ? ks.map(k => hbar(labelFn(k), obj[k].rate, `${Math.round(obj[k].rate)}% · ${obj[k].total}`, !obj[k].enough_data)).join('') + '<p class="tiny-note">Faded rows have fewer than 4 tasks, so treat them as a hint, not a pattern.</p>' : empty('Add some tasks to see this.'); };

  function render(d) {
    const m = d.mood, t = d.tasks, mu = d.music, w = d.wardrobe;
    const heads = `<div class="insight-heads">${d.headlines.map(h => `<div class="insight-card">✦ ${esc(h)}</div>`).join('')}</div>`;
    const moodBlock = `<div class="ins-grid">${card('YOUR INNER WEATHER', 'Mood mix', donut(m.counts))}${card('THE LAST FOUR WEEKS', `${m.days_logged_28} of 28 days checked in`, strip(m.last28))}</div>
      <div class="ins-grid">${card('WHEN YOU FEEL WHAT', 'By day of the week', m.total ? heat(m.by_weekday, Object.keys(m.by_weekday)) : empty('Needs a few check-ins.'))}${card('TIME OF DAY', 'Morning to night', m.total ? heat(m.by_part_of_day, Object.keys(m.by_part_of_day)) : empty('Needs a few check-ins.'))}</div>`;
    const taskBlock = `<div class="kpi-row">${kpi('Completion', t.rate + '%', `${t.completed} of ${t.total} tasks`)}${kpi('Open', t.open, t.due_today ? `${t.due_today} due today` : '')}${kpi('Overdue', t.overdue, t.overdue ? 'worth a look' : 'all on time')}${kpi('Typical time to finish', t.median_hours_to_complete === null ? '—' : t.median_hours_to_complete + ' h', 'median, add → done')}</div>
      <div class="ins-grid wide-left">${card('LAST 14 DAYS', 'Tasks added vs completed', dual(t.last14))}${card('THIS WEEK', `${t.completed_this_week} done vs ${t.completed_last_week} last week`, t.total ? `<div class="legend"><div>Best day<b>${Object.entries(t.completed_by_weekday).sort((a, b) => b[1] - a[1])[0][1] ? Object.entries(t.completed_by_weekday).sort((a, b) => b[1] - a[1])[0][0] : '—'}</b></div><div>Best time of day<b>${Object.entries(t.completed_by_part).sort((a, b) => b[1] - a[1])[0][1] ? Object.entries(t.completed_by_part).sort((a, b) => b[1] - a[1])[0][0] : '—'}</b></div></div>` : empty('Nothing yet.'))}</div>
      <div class="ins-grid">${card('MOOD vs FOLLOW-THROUGH', 'Completion by the mood a task was made in', rateRows(t.by_mood, k => `${EMO[k]} ${k}`))}${card('PRIORITY', 'Completion by priority', rateRows(t.by_priority, k => k))}</div>
      <div class="ins-grid">${card('EFFORT', 'Completion by effort', rateRows(t.by_effort, k => k))}${card('CATEGORIES', 'Completion by category', rateRows(t.by_category, k => esc(k)))}</div>`;
    const maxMood = Math.max(1, ...MOODS.map(k => mu.by_mood[k].like + mu.by_mood[k].skip));
    const musicBlock = `<div class="kpi-row">${kpi('Tracks played', mu.plays)}${kpi('Minutes listened', mu.minutes_listened)}${kpi('Played to the end', mu.plays ? mu.finished_rate + '%' : '—')}${kpi('Liked / skipped', `${mu.likes} / ${mu.skips}`)}</div>
      <div class="ins-grid">${card('FEEDBACK BY MOOD', 'What fits, what doesn’t', MOODS.some(k => mu.by_mood[k].like + mu.by_mood[k].skip) ? MOODS.map(k => { const v = mu.by_mood[k]; return `<div class="hb"><span>${EMO[k]} ${k}</span><div class="hb-track split"><i class="lk" style="width:${v.like / maxMood * 100}%"></i><i class="sk" style="width:${v.skip / maxMood * 100}%"></i></div><b>♡${v.like} ↷${v.skip}</b></div>`; }).join('') : empty('Tap ♡ or ↷ on songs to teach your mood radio.'))}
        ${card('MOST PLAYED', 'Your top tracks', mu.top_played.length ? mu.top_played.map(x => hbar(`${esc(x.title)}`, x.plays / mu.top_played[0].plays * 100, x.plays + '×')).join('') : empty('Play a few songs and they will rank here.'))}</div>`;
    const maxWorn = Math.max(1, ...w.most_worn.map(x => x.worn));
    const wardBlock = `<div class="kpi-row">${kpi('Wardrobe pieces', w.items)}${kpi('Not worn yet', w.never_worn)}${kpi('Outfits suggested', w.outfits_shown)}${kpi('Accepted', w.outfits_shown ? w.accept_rate + '%' : '—')}</div>
      ${card('MOST WORN', 'Your favourites', w.most_worn.length ? w.most_worn.map(x => hbar(esc(x.name), x.worn / maxWorn * 100, x.worn + '×')).join('') : empty('Accept an outfit suggestion and your favourites will show up.'))}`;
    $('#insights-root').innerHTML = `${heads}<h3 class="ins-title">Mood</h3>${moodBlock}<h3 class="ins-title">To-do</h3>${taskBlock}<h3 class="ins-title">Music</h3>${musicBlock}<h3 class="ins-title">Wardrobe</h3>${wardBlock}
      <p class="tiny-note">These are descriptive patterns from your own data. With small samples they can look stronger than they are, and they show association, not cause.</p>`;
  }
  async function load() {
    const root = $('#insights-root'); if (!root) return;
    if (!loaded) root.innerHTML = empty('Loading your patterns…');
    try { render(await api('/insights')); loaded = true; }
    catch (e) { root.innerHTML = empty(`Couldn't load insights: ${esc(e.message)}`); }
  }
  $('#logout-btn').addEventListener('click', () => { loaded = false; });
  window.MSInsights = { load };
})();
