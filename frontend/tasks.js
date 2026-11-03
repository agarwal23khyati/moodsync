/* MoodSync to-do: priorities, due dates, categories, effort, search/sort/filter, edit dialog, and the mood-aware
   "Focus now" list produced by the Task agent. Also draws the extra cards on the Home dashboard. */
(() => {
  'use strict';
  const MS = window.MS; if (!MS) return;
  const { api, state, toast, escapeHtml: esc, $, $$, todayKey } = MS;
  const T = { filter: 'all', sort: 'smart', cat: 'All', q: '', focus: [], streak: 0, mood: null, loaded: false, timer: null };
  const PRI = { high: 3, medium: 2, low: 1 };
  const EFF = { quick: '⚡ quick', medium: '◐ medium', deep: '🧠 deep' };
  const MOOD_COL = { happy: '#f6c453', energetic: '#ff8a5b', calm: '#6cc5a1', low: '#8d94e8' };
  const dkey = t => (t.due_date ? String(t.due_date).slice(0, 10) : null);
  const day = d => todayKey(d);
  const diffDays = k => Math.round((new Date(k + 'T00:00:00') - new Date(todayKey() + 'T00:00:00')) / 864e5);

  function dueInfo(t) {
    const k = dkey(t); if (!k) return null; const d = diffDays(k);
    if (d < 0) return { text: `Overdue ${-d}d`, cls: 'late' };
    if (d === 0) return { text: 'Today', cls: 'today' };
    if (d === 1) return { text: 'Tomorrow', cls: '' };
    return { text: new Date(k + 'T00:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric' }), cls: '' };
  }
  function currentMood() {
    const m = state.moods && state.moods[0]; if (!m) return null;
    return Date.now() - new Date(m.created_at || m.logged_at) < 864e5 ? m.mood : null;
  }
  const badges = t => {
    const due = t.completed ? null : dueInfo(t);
    return `<span class="pri pri-${esc(t.priority || 'medium')}">● ${esc((t.priority || 'medium'))}</span>${due ? `<span class="tag due ${due.cls}">${due.text}</span>` : ''}<span class="tag">${esc(t.category || 'General')}</span><span class="tag">${EFF[t.effort] || EFF.medium}</span>`;
  };

  // ------------------------------------------------------------------ data
  async function reload() { state.tasks = await MS.getRows('tasks'); }
  async function after() { await reload(); render(); MS.renderHomeStatsOnly(); MS.renderHome(); renderHomeExtras(); refreshFocus(); }
  function refreshFocus() {
    clearTimeout(T.timer);
    T.timer = setTimeout(async () => {
      T.mood = currentMood();
      try { const r = await api('/suggest/task' + (T.mood ? '?mood=' + T.mood : '')); T.focus = r.focus || []; T.streak = r.streak_days || 0; T.loaded = true; }
      catch (e) { T.focus = []; T.loaded = true; }
      renderFocus(); renderHomeExtras();
    }, 200);
  }

  // ------------------------------------------------------------------ list
  function visible() {
    const td = todayKey(); let l = state.tasks.slice();
    const f = T.filter;
    l = l.filter(t => f === 'all' || (f === 'active' && !t.completed) || (f === 'completed' && t.completed) ||
      (f === 'today' && !t.completed && dkey(t) === td) || (f === 'overdue' && !t.completed && dkey(t) && dkey(t) < td));
    if (T.cat !== 'All') l = l.filter(t => (t.category || 'General') === T.cat);
    if (T.q) l = l.filter(t => (t.title || '').toLowerCase().includes(T.q));
    const due = t => dkey(t) || '9999-12-31', pri = t => PRI[t.priority] || 2, created = t => String(t.created_at || '');
    const cmp = {
      smart: (a, b) => (a.completed - b.completed) || (a.completed ? String(b.completed_at || '').localeCompare(String(a.completed_at || '')) : (due(a).localeCompare(due(b)) || pri(b) - pri(a) || created(b).localeCompare(created(a)))),
      due: (a, b) => due(a).localeCompare(due(b)) || pri(b) - pri(a),
      priority: (a, b) => pri(b) - pri(a) || due(a).localeCompare(due(b)),
      newest: (a, b) => created(b).localeCompare(created(a))
    }[T.sort];
    return l.sort(cmp);
  }
  function render() {
    if (!$('#task-list')) return;
    const all = state.tasks, done = all.filter(t => t.completed).length, open = all.length - done, td = todayKey();
    const overdue = all.filter(t => !t.completed && dkey(t) && dkey(t) < td).length;
    $('#task-count-chip').textContent = `${all.length} ${all.length === 1 ? 'task' : 'tasks'}`;
    const cats = [...new Set(all.map(t => t.category || 'General'))].sort();
    $('#task-cat-row').innerHTML = cats.length > 1 ? ['All', ...cats].map(c => `<button class="chip ${T.cat === c ? 'on' : ''}" data-t-cat="${esc(c)}">${esc(c)}</button>`).join('') : '';
    if (T.cat !== 'All' && !cats.includes(T.cat)) T.cat = 'All';
    const dl = $('#task-cat-list'); if (dl) dl.innerHTML = [...new Set(['General', 'Study', 'Work', 'Personal', 'Health', 'Home', ...cats])].map(c => `<option>${esc(c)}</option>`).join('');
    const list = visible();
    $('#task-list').innerHTML = list.map(t => `<div class="task-row v2 ${t.completed ? 'completed' : ''}"><button class="check-dot ${t.completed ? 'checked' : ''}" data-t-toggle="${esc(t.id)}" aria-label="${t.completed ? 'Mark as not done' : 'Mark as done'}">${t.completed ? '✓' : ''}</button>
      <div class="task-body"><span class="task-title" data-t-edit="${esc(t.id)}" title="Click to edit">${esc(t.title)}</span><div class="task-meta">${badges(t)}</div></div>
      <button class="row-btn" data-t-edit="${esc(t.id)}" aria-label="Edit task" title="Edit">✎</button><button class="delete-task" data-t-del="${esc(t.id)}" aria-label="Delete task">×</button></div>`).join('')
      || `<div class="empty-state">${all.length ? 'Nothing matches these filters. Try “All” ✿' : 'Nothing here yet. A fresh little patch of possibility 🌱'}</div>`;
    $('#task-footnote').textContent = all.length ? `${open} open${overdue ? ` · ${overdue} overdue` : ''} · showing ${list.length}` : '';
    $('#clear-done-btn').style.display = done ? '' : 'none'; $('#clear-done-btn').textContent = `Clear completed (${done})`;
    const pct = all.length ? Math.round(done / all.length * 100) : 0;
    $('#task-percent').textContent = pct + '%'; $('#task-donut').style.background = `conic-gradient(#a98be4 ${pct * 3.6}deg,#f0e9f7 0deg)`;
    $('#completed-count').textContent = done; $('#remaining-count').textContent = open;
    $('#task-encouragement').textContent = pct === 100 && all.length ? 'You did the thing. Let yourself enjoy that.' : done ? "Look at the progress you've already made." : 'Start small. Your future self says thanks.';
    $('#task-week').innerHTML = weekBars();
    $$('[data-task-filter]').forEach(b => b.classList.toggle('active', b.dataset.taskFilter === T.filter));
    renderFocus();
  }

  // ------------------------------------------------------------------ focus card (Task agent) + week bars
  function focusRows(list, compact) {
    return list.map(f => `<div class="focus-row"><button class="check-dot" data-t-toggle="${esc(f.id)}" aria-label="Mark as done"></button><div><strong>${esc(f.title)}</strong><small>${esc(f.reason)}</small></div>${compact ? '' : `<div class="task-meta"><span class="pri pri-${esc(f.priority)}">● ${esc(f.priority)}</span><span class="tag">${EFF[f.effort] || ''}</span></div>`}</div>`).join('');
  }
  function renderFocus() {
    const el = $('#focus-card'); if (!el) return;
    const mood = T.mood, meta = mood && MS.moodMeta[mood];
    el.innerHTML = `<div class="focus-head"><div><p class="eyebrow">FOCUS NOW</p><h2>${meta ? `Best next steps for a ${esc(meta.label.toLowerCase())} mood ${meta.emoji}` : 'Best next steps'}</h2></div>${T.streak ? `<span class="soft-chip">🔥 ${T.streak}-day task streak</span>` : ''}</div>
      ${!T.loaded ? '<div class="empty-state">Thinking…</div>' : T.focus.length ? focusRows(T.focus, false) : '<div class="empty-state">Nothing open right now. Add a task or enjoy the breathing room ✿</div>'}
      ${mood ? '<p class="tiny-note">Ranked by due date, priority and how well the effort fits your mood: small wins first when you feel low, deeper work when you feel energetic.</p>' : '<p class="tiny-note">Do a mood check-in on <button class="text-btn" data-page="home">Home</button> and this list becomes mood-aware.</p>'}`;
  }
  function weekBars(compact) {
    const days = [], cnt = {};
    state.tasks.forEach(t => { if (t.completed && t.completed_at) { const k = day(new Date(t.completed_at)); cnt[k] = (cnt[k] || 0) + 1; } });
    for (let i = 6; i >= 0; i--) { const d = new Date(); d.setDate(d.getDate() - i); days.push({ k: day(d), n: cnt[day(d)] || 0, l: d.toLocaleDateString(undefined, { weekday: 'narrow' }), now: i === 0 }); }
    const max = Math.max(1, ...days.map(d => d.n));
    return `<div class="week-chart">${days.map(d => `<div class="wk ${d.now ? 'now' : ''}" title="${d.n} done on ${d.k}"><b>${d.n || ''}</b><i style="height:${Math.max(4, d.n / max * 64)}px"></i><span>${d.l}</span></div>`).join('')}</div>`;
  }

  // ------------------------------------------------------------------ Home dashboard extras
  function renderHomeExtras() {
    const el = $('#home-extra'); if (!el) return;
    const week = Object.values(state.tasks).filter(t => t.completed && t.completed_at && Date.now() - new Date(t.completed_at) < 7 * 864e5).length;
    const m7 = []; for (let i = 6; i >= 0; i--) { const d = new Date(); d.setDate(d.getDate() - i); const k = day(d);
      const log = (state.moods || []).find(m => day(new Date(m.created_at || m.logged_at)) === k); m7.push(log ? log.mood : null); }
    const mood = currentMood() || state.mood;
    el.innerHTML = `<article class="card"><p class="eyebrow">FOCUS NOW</p><h2>${T.focus.length ? 'Your best next steps' : 'Nothing urgent'}</h2>${T.loaded ? (T.focus.length ? focusRows(T.focus.slice(0, 3), true) : '<div class="empty-state">All clear ✿</div>') : '<div class="empty-state">…</div>'}<button class="text-btn" data-page="tasks">Open to-do garden ↗</button></article>
      <article class="card"><p class="eyebrow">THIS WEEK</p><h2>${week} ${week === 1 ? 'task' : 'tasks'} done</h2>${weekBars()}<div class="mood-dots" title="Last 7 days of check-ins">${m7.map(m => `<i style="background:${m ? MOOD_COL[m] : '#eee8f4'}" title="${m || 'no check-in'}"></i>`).join('')}</div><button class="text-btn" data-page="insights">See all insights ↗</button></article>
      <article class="card" id="home-radio"></article>`;
    renderRadio();
  }
  function renderRadio() {
    const el = $('#home-radio'); if (!el) return; const cur = window.MSPlayer && MSPlayer.current();
    const mood = currentMood() || state.mood || 'happy', meta = MS.moodMeta[mood];
    el.innerHTML = `<p class="eyebrow">SOUNDTRACK</p>${cur ? `<h2>${esc(cur.title)}</h2><p class="muted">${esc(cur.artist)}</p><button class="btn btn-secondary btn-full" data-home-radio-toggle>${MSPlayer.isPlaying() ? '⏸ Pause' : '▶ Play'}</button>`
      : `<h2>${meta.emoji} ${esc(meta.label)} radio</h2><p class="muted">Songs for this mood, playing right here. No tabs.</p><button class="btn btn-primary btn-full" data-home-radio="${mood}">▶ Play ${esc(meta.label.toLowerCase())} radio</button>`}`;
  }

  // ------------------------------------------------------------------ edit dialog
  function openEdit(id) {
    const t = state.tasks.find(x => String(x.id) === String(id)); if (!t) return;
    const sel = (opts, v) => opts.map(([val, lab]) => `<option value="${val}" ${val === v ? 'selected' : ''}>${lab}</option>`).join('');
    $('#modal-root').innerHTML = `<div class="modal-backdrop" data-t-backdrop><article class="modal-card" role="dialog" aria-modal="true" aria-label="Edit task"><p class="eyebrow">EDIT TASK</p>
      <label class="field">Task<input id="te-title" maxlength="160" value="${esc(t.title)}"/></label>
      <div class="two-fields"><label class="field">Priority<select id="te-pri">${sel([['high', 'High'], ['medium', 'Medium'], ['low', 'Low']], t.priority || 'medium')}</select></label>
      <label class="field">Effort<select id="te-eff">${sel([['quick', 'Quick'], ['medium', 'Medium'], ['deep', 'Deep work']], t.effort || 'medium')}</select></label></div>
      <div class="two-fields"><label class="field">Category<input id="te-cat" maxlength="30" value="${esc(t.category || 'General')}"/></label><label class="field">Due<input id="te-due" type="date" value="${esc(dkey(t) || '')}"/></label></div>
      <p class="form-message" id="te-msg"></p><div class="modal-actions"><button class="btn btn-primary" data-t-save="${esc(t.id)}">Save</button><button class="btn" data-t-cancel>Cancel</button></div></article></div>`;
    $('#te-title').focus();
  }
  const closeModal = () => { $('#modal-root').innerHTML = ''; };

  // ------------------------------------------------------------------ wiring
  function wire() {
    $('#task-form').addEventListener('submit', async e => {
      e.preventDefault(); const title = $('#task-input').value.trim(); if (!title) return;
      try {
        await api('/tasks', { method: 'POST', json: { title, priority: $('#task-priority').value, effort: $('#task-effort').value, category: $('#task-category').value.trim() || 'General', due_date: $('#task-due').value || null } });
        $('#task-input').value = ''; $('#task-due').value = ''; await after(); toast('A little task has been planted 🌱');
      } catch (err) { toast(err.message || 'Could not add the task'); }
    });
    $$('[data-task-filter]').forEach(b => b.addEventListener('click', () => { T.filter = b.dataset.taskFilter; render(); }));
    $('#task-search').addEventListener('input', e => { T.q = e.target.value.trim().toLowerCase(); render(); });
    $('#task-sort').addEventListener('change', e => { T.sort = e.target.value; render(); });
    $('#clear-done-btn').addEventListener('click', async () => {
      const n = state.tasks.filter(t => t.completed).length; if (!n || !confirm(`Remove ${n} completed ${n === 1 ? 'task' : 'tasks'}?`)) return;
      try { await api('/tasks?completed=true', { method: 'DELETE' }); await after(); toast('Cleared completed tasks'); } catch (err) { toast(err.message); }
    });
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && $('#modal-root .modal-card [id^="te-"]')) closeModal(); });
    document.addEventListener('click', async e => {
      const g = sel => e.target.closest(sel);
      try {
        let x;
        if ((x = g('[data-t-toggle]'))) { const t = state.tasks.find(v => String(v.id) === x.dataset.tToggle); if (!t) return; await api('/tasks/' + t.id, { method: 'PATCH', json: { completed: !t.completed } }); await after(); if (!t.completed) toast('Tiny win unlocked ✨'); return; }
        if ((x = g('[data-t-del]'))) { await api('/tasks/' + x.dataset.tDel, { method: 'DELETE' }); await after(); toast('Task removed'); return; }
        if ((x = g('[data-t-edit]'))) { openEdit(x.dataset.tEdit); return; }
        if ((x = g('[data-t-cat]'))) { T.cat = x.dataset.tCat; render(); return; }
        if (g('[data-t-cancel]')) { closeModal(); return; }
        if ((x = g('[data-t-backdrop]')) && e.target === x) { closeModal(); return; }
        if ((x = g('[data-t-save]'))) {
          const title = $('#te-title').value.trim(); if (!title) { $('#te-msg').textContent = 'A task needs a name.'; return; }
          await api('/tasks/' + x.dataset.tSave, { method: 'PATCH', json: { title, priority: $('#te-pri').value, effort: $('#te-eff').value, category: $('#te-cat').value.trim() || 'General', due_date: $('#te-due').value || null } });
          closeModal(); await after(); toast('Saved ✿'); return;
        }
        if ((x = g('[data-home-radio]'))) { if (window.MSPlayer) { MSPlayer.playMood(x.dataset.homeRadio); MS.navigate('music'); } return; }   // playMood first: it claims the mood, so the page does not load it twice
        if (g('[data-home-radio-toggle]')) { MS.navigate('music'); return; }
      } catch (err) { toast(err.message || 'Something went wrong'); }
    });
  }
  wire();
  window.MSTasks = { render, renderHomeExtras, renderRadio, refreshFocus };
  if (state.user) { render(); refreshFocus(); }
})();
