/* MoodSync music player: plays inside the app (30-second previews via <audio>, full songs/playlists via the YouTube /
   Spotify embed), one queue per mood, keeps playing while you move between pages, logs plays for the Insights page. */
(() => {
  'use strict';
  const MS = window.MS; if (!MS) return;
  const { api, state, toast, escapeHtml: esc, $, $$ } = MS;
  const VIBE = {
    happy: ['A little sunshine for your day', 'Warm melodies and songs that feel like a window-down afternoon.'],
    energetic: ['Big energy, big feelings', 'Turn the volume up and give that energy somewhere to go.'],
    calm: ['Slow down, breathe it out', 'Gentle sounds for an uncluttered mind and an easier pace.'],
    low: ['A soft place to land', 'No pressure to feel better instantly. Just a little company.']
  };
  const SILENT = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=';
  const P = { mood: null, queue: [], cur: null, curMood: null, shuffle: false, repeat: false, loading: false, status: '',
              t0: 0, logged: true, pending: false, offline: false, mine: [], atMoods: new Set(), audio: new Audio(), unlocked: false };
  P.audio.preload = 'auto';
  try { const v = parseFloat(localStorage.getItem('moodsync:vol')); P.audio.volume = isNaN(v) ? 0.8 : Math.min(1, Math.max(0, v)); P.shuffle = localStorage.getItem('moodsync:shuffle') === '1'; } catch (e) {}

  const playable = t => !!(t && (t.embed || t.preview_url));
  const curMood = () => state.musicMood || 'happy';
  const fmt = s => { s = Math.max(0, Math.floor(s || 0)); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); };
  const silent = () => P.audio.getAttribute('src') === SILENT;   // the tiny unlock clip, never a real track
  const art = (t, cls = '') => t && t.artwork ? `<img class="${cls}" src="${esc(t.artwork)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : `<span class="${cls} art-emoji">${esc((t && t.emoji) || '♫')}</span>`;
  const isPlaying = () => !!P.cur && (P.cur.embed ? true : !P.audio.paused);

  // ------------------------------------------------------------------ loading + resolving previews
  async function loadMood(mood, autoplay = false) {
    P.mood = mood; state.musicMood = mood; P.loading = true; P.status = 'Tuning in…'; P.pending = autoplay; renderPage();
    try { P.queue = (await api(`/suggest/music?mood=${mood}&limit=30`)).tracks || []; }
    catch (e) { P.loading = false; P.pending = false; P.status = 'Could not load tracks: ' + e.message; renderPage(); return; }
    P.loading = false; P.status = ''; renderPage();
    await resolveAll();
  }
  async function resolveAll() {
    const need = P.queue.filter(t => !t.embed && !t.preview_url && !t.tried).map(t => t.key);
    P.status = need.length ? 'Finding playable previews…' : ''; renderPage();
    for (let i = 0; i < need.length; i += 8) {
      const chunk = need.slice(i, i + 8);
      try {
        const r = await api('/music/resolve', { method: 'POST', json: { keys: chunk } });
        chunk.forEach(k => { const t = P.queue.find(x => x.key === k); if (!t) return; t.tried = true; if (r.resolved[k]) Object.assign(t, r.resolved[k]); });
      } catch (e) {
        P.offline = true; P.status = "Couldn't fetch previews (is the server online?). Songs will open in a new tab instead.";
        chunk.forEach(k => { const t = P.queue.find(x => x.key === k); if (t) t.tried = true; }); break;
      }
      if (P.pending) { const f = P.queue.find(playable); if (f) { P.pending = false; play(f.key); } }
      renderPage();
    }
    P.queue.forEach(t => { if (!t.embed && !t.preview_url) t.tried = true; });
    if (P.pending) { P.pending = false; toast('No in-app previews found for this mood yet.'); }
    const n = P.queue.filter(playable).length;
    if (!P.offline) P.status = n ? '' : 'No in-app previews found. Songs will open in a new tab.';
    renderPage();
  }
  async function loadMine() {
    try { P.mine = ((await api('/suggest/music?limit=60')).tracks || []).filter(t => t.custom); } catch (e) { P.mine = []; }
    renderMine();
  }

  // ------------------------------------------------------------------ playback
  function unlock() {   // Safari/iOS only allow audio that starts inside a tap; this "primes" the element before we await the API
    if (P.unlocked || P.cur) return; P.unlocked = true;
    try { P.audio.src = SILENT; const p = P.audio.play(); if (p && p.then) p.then(() => { if (silent()) P.audio.pause(); }).catch(() => {}); } catch (e) {}
  }
  function logPlay(completed) {
    const t = P.cur; if (!t || P.logged) return; P.logged = true;
    const secs = t.embed ? (Date.now() - P.t0) / 1000 : (P.audio.currentTime || 0);
    if (secs < 3) return;
    api('/plays', { method: 'POST', json: { track_key: t.key, mood: P.curMood || null, seconds: Math.round(secs * 10) / 10, completed: !!completed, source: t.embed ? 'embed' : 'preview' } }).catch(() => {});
  }
  function play(key) {
    const t = P.queue.find(x => x.key === key) || (P.cur && P.cur.key === key ? P.cur : null); if (!t) return;
    if (!playable(t)) {
      if (!t.tried && !t.embed) { toast('Still finding that preview…'); return; }
      if (t.url) window.open(t.url, '_blank', 'noopener'); toast('No in-app preview for this one, so it opened in a new tab.'); return;
    }
    logPlay(false);
    P.cur = t; P.curMood = P.mood; P.t0 = Date.now(); P.logged = false;
    if (t.embed) { P.audio.pause(); showEmbed(t); }
    else { hideEmbed(); P.audio.src = t.preview_url; const p = P.audio.play(); if (p && p.catch) p.catch(err => { console.warn('[MoodSync audio] play() rejected:', err); toast(err && err.name === 'NotAllowedError' ? 'Browser blocked autoplay. Press play ▶' : 'Audio error: ' + (err && err.name || 'unknown') + ' (see console)'); }); }
    mediaSession(t); renderAll();
  }
  function step(dir) {
    const list = P.queue.filter(playable); if (!list.length) { toast('Nothing playable in this queue yet.'); return; }
    const i = list.findIndex(t => P.cur && t.key === P.cur.key);
    if (P.shuffle && list.length > 1) { let j; do { j = Math.floor(Math.random() * list.length); } while (j === i); play(list[j].key); return; }
    play(list[i < 0 ? (dir > 0 ? 0 : list.length - 1) : (i + dir + list.length) % list.length].key);
  }
  function toggle() {
    if (!P.cur) { playMood(curMood()); return; }
    if (P.cur.embed) { toast('This one plays in the little player. Use its own controls ↗'); return; }
    if (P.audio.paused) P.audio.play().catch(() => {}); else P.audio.pause();
  }
  async function playMood(mood) {
    mood = mood || curMood(); unlock();
    if (P.mood !== mood || !P.queue.length) { await loadMood(mood, true); return; }
    const f = P.queue.find(playable);
    if (f) play(f.key); else { P.pending = true; await resolveAll(); }
  }
  async function feedback(key, value) {
    const now = state.feedback[key] === value ? 'none' : value;
    state.feedback[key] = now === 'none' ? '' : now;
    try { await api('/song_feedback', { method: 'POST', json: { track_key: key, feedback: now, mood: P.mood || curMood() } }); } catch (e) { toast('Feedback could not save: ' + e.message); }
    renderAll();
    if (value === 'skip' && now === 'skip' && P.cur && P.cur.key === key) step(1);
    toast(now === 'like' ? 'Noted: more of this vibe ♡' : now === 'skip' ? 'Got it, we will keep exploring ✨' : 'Feedback cleared');
  }
  function mediaSession(t) {
    if (!('mediaSession' in navigator)) return;
    try {
      navigator.mediaSession.metadata = new MediaMetadata({ title: t.title, artist: t.artist || '', artwork: t.artwork ? [{ src: t.artwork, sizes: '400x400' }] : [] });
      navigator.mediaSession.setActionHandler('previoustrack', () => step(-1)); navigator.mediaSession.setActionHandler('nexttrack', () => step(1));
      navigator.mediaSession.setActionHandler('play', () => P.audio.play()); navigator.mediaSession.setActionHandler('pause', () => P.audio.pause());
    } catch (e) {}
  }

  // ------------------------------------------------------------------ embed panel (full songs / playlists)
  function showEmbed(t) {
    const h = t.provider === 'spotify' ? 152 : 180;
    $('#embed-holder').innerHTML = `<iframe src="${esc(t.embed)}" width="320" height="${h}" frameborder="0" allow="autoplay; encrypted-media; clipboard-write; fullscreen; picture-in-picture" title="${esc(t.title)}"></iframe>`;
    $('#embed-title').textContent = t.title; $('#embed-panel').classList.remove('hidden');
  }
  function hideEmbed() { const h = $('#embed-holder'); if (h) h.innerHTML = ''; const p = $('#embed-panel'); if (p) p.classList.add('hidden'); }

  // ------------------------------------------------------------------ rendering
  function renderAll() { renderDock(); renderPage(); }
  function renderDock() {
    const dock = $('#player-dock'); if (!dock) return;
    if (window.MSTasks && MSTasks.renderRadio) MSTasks.renderRadio();
    const t = P.cur; dock.classList.toggle('hidden', !t); document.body.classList.toggle('has-dock', !!t);
    if (!t) return;
    dock.classList.toggle('embed-mode', !!t.embed);
    $('#dock-art').innerHTML = art(t); $('#dock-title').textContent = t.title; $('#dock-artist').textContent = t.embed ? `${t.artist} · playing in the little player` : t.artist;
    $('#dock-play').textContent = isPlaying() ? '⏸' : '▶';
    const l = $('#dock-like'); const on = state.feedback[t.key] === 'like'; l.textContent = on ? '♥' : '♡'; l.classList.toggle('on', on);
  }
  function onTime() {
    if (silent() || !P.cur || P.cur.embed) return;
    const d = P.audio.duration || 30, c = P.audio.currentTime || 0, pct = d ? c / d * 100 : 0;
    const seek = $('#dock-seek'); if (seek && !seek._drag) seek.value = pct;
    $('#dock-cur').textContent = fmt(c); $('#dock-dur').textContent = fmt(d);
    $$('.pl-prog-fill').forEach(el => el.style.width = pct + '%');
  }
  function renderPage() {
    const page = $('#page-music'); if (!page) return;
    const mood = P.mood || curMood();
    if (state.page === 'music' && MS.token && P._mineFor !== MS.token) { P._mineFor = MS.token; loadMine(); }
    if (state.page === 'music' && !P.loading && P.mood !== curMood()) { loadMood(curMood()); return; }
    $('#music-vibe-title').textContent = VIBE[mood][0]; $('#music-vibe-desc').textContent = VIBE[mood][1];
    $$('[data-pl-mood]').forEach(b => b.classList.toggle('active', b.dataset.plMood === mood));
    $('#pl-status').textContent = P.status;
    const n = P.queue.filter(playable).length; $('#pl-count').textContent = P.queue.length ? `${n} of ${P.queue.length} play in-app` : '—';
    const t = P.cur, fb = t ? state.feedback[t.key] : '';
    $('#now-card').innerHTML = t ? `<div class="now-art">${art(t)}</div><div class="now-info"><p class="eyebrow">${t.embed ? 'FULL SONG · PLAYING IN THE LITTLE PLAYER' : '30-SECOND PREVIEW · AUTO-NEXT'}</p><h2>${esc(t.title)}</h2><p class="muted">${esc(t.artist)}${t.description ? ' · ' + esc(t.description) : ''}</p>
        ${t.embed ? '' : `<div class="pl-prog" data-pl="seekbar"><i class="pl-prog-fill"></i></div>`}
        <div class="now-controls"><button data-pl="shuffle" class="${P.shuffle ? 'on' : ''}" aria-label="Shuffle" title="Shuffle">🔀</button><button data-pl="prev" aria-label="Previous">⏮</button><button data-pl="toggle" class="big" aria-label="Play or pause">${isPlaying() ? '⏸' : '▶'}</button><button data-pl="next" aria-label="Next">⏭</button><button data-pl="repeat" class="${P.repeat ? 'on' : ''}" aria-label="Repeat" title="Repeat this song">🔁</button></div>
        <div class="now-actions"><button data-pl-fb="like" data-key="${esc(t.key)}" class="${fb === 'like' ? 'liked' : ''}">♡ fits my mood</button><button data-pl-fb="skip" data-key="${esc(t.key)}" class="${fb === 'skip' ? 'liked' : ''}">↷ not for me</button>${t.external || t.apple_url ? `<a href="${esc(t.external || t.apple_url)}" target="_blank" rel="noopener noreferrer">open original ↗</a>` : ''}</div></div>`
      : `<div class="now-empty"><span>🎧</span><h2>Nothing playing yet</h2><p class="muted">Press “Play this mood” and your queue starts right here.</p></div>`;
    $('#pl-queue').innerHTML = P.loading ? '<div class="empty-state">Tuning in…</div>' : P.queue.map(q => {
      const f = state.feedback[q.key], on = P.cur && P.cur.key === q.key;
      const badge = q.embed ? `<span class="pl-badge full">${q.provider === 'spotify' ? 'Spotify' : 'YouTube'} · full</span>` : q.preview_url ? '<span class="pl-badge">30s preview</span>' : q.tried ? '<span class="pl-badge off">opens ↗</span>' : '<span class="pl-badge wait">finding…</span>';
      return `<div class="pl-row ${on ? 'now' : ''}" data-pl-play="${esc(q.key)}" role="button" tabindex="0"><div class="pl-art">${art(q)}<b>${on && isPlaying() ? '❚❚' : '▶'}</b></div><div class="pl-info"><strong>${esc(q.title)}</strong><span>${esc(q.artist)}${q.custom ? ' · yours' : ''}</span></div>${badge}
        <button data-pl-fb="like" data-key="${esc(q.key)}" class="${f === 'like' ? 'liked' : ''}" title="Fits my mood">♡</button><button data-pl-fb="skip" data-key="${esc(q.key)}" class="${f === 'skip' ? 'liked' : ''}" title="Not for me">↷</button></div>`;
    }).join('') || '<div class="empty-state">No tracks for this mood yet. Add your own below ✿</div>';
    onTime();
  }
  function renderMine() {
    const el = $('#my-tracks'); if (!el) return;
    el.innerHTML = P.mine.length ? '<span class="tiny-note">Your tracks:</span>' + P.mine.map(t => `<span class="chip static">${t.provider === 'spotify' ? '🟢' : '▶️'} ${esc(t.title)} <button data-pl-del="${esc(t.key)}" aria-label="Remove ${esc(t.title)}">×</button></span>`).join('') : '';
  }

  // ------------------------------------------------------------------ wiring
  function wire() {
    P.audio.addEventListener('timeupdate', onTime); P.audio.addEventListener('loadedmetadata', onTime);
    P.audio.addEventListener('play', () => { if (!silent()) renderAll(); }); P.audio.addEventListener('pause', () => { if (!silent()) renderAll(); });
    P.audio.addEventListener('ended', () => {
      if (silent()) return; logPlay(true);
      if (P.repeat) { P.logged = false; P.t0 = Date.now(); P.audio.currentTime = 0; P.audio.play().catch(() => {}); } else step(1);
    });
    P.audio.addEventListener('error', () => {
      if (silent() || !P.cur || P.cur.embed) return;
      const ec = P.audio.error ? P.audio.error.code : '?'; console.warn('[MoodSync audio] error code', ec, 'src', P.audio.currentSrc); toast(`Couldn't play “${P.cur.title}” (audio error ${ec}), skipping.`); P.cur.preview_url = ''; P.cur.tried = true; const bad = P.cur; P.cur = null; renderAll(); if (bad) step(1);
    });
    const seek = $('#dock-seek');
    seek.addEventListener('input', () => { seek._drag = true; const d = P.audio.duration || 30; $('#dock-cur').textContent = fmt(seek.value / 100 * d); });
    seek.addEventListener('change', () => { const d = P.audio.duration || 30; P.audio.currentTime = seek.value / 100 * d; seek._drag = false; });
    $('#embed-close').addEventListener('click', () => { logPlay(false); hideEmbed(); if (P.cur && P.cur.embed) P.cur = null; renderAll(); });

    document.addEventListener('click', async e => {
      const fb = e.target.closest('[data-pl-fb]'); if (fb) { e.stopPropagation(); await feedback(fb.dataset.key, fb.dataset.plFb); return; }
      const del = e.target.closest('[data-pl-del]');
      if (del) { try { await api('/tracks/' + del.dataset.plDel, { method: 'DELETE' }); if (P.cur && P.cur.key === del.dataset.plDel) { P.audio.pause(); hideEmbed(); P.cur = null; } await loadMine(); await loadMood(P.mood || curMood()); renderAll(); toast('Removed from your music'); } catch (err) { toast(err.message); } return; }
      const am = e.target.closest('[data-at-mood]');
      if (am) { const m = am.dataset.atMood; P.atMoods.has(m) ? P.atMoods.delete(m) : P.atMoods.add(m); am.classList.toggle('on', P.atMoods.has(m)); return; }
      const pm = e.target.closest('[data-pl-mood]'); if (pm) { await loadMood(pm.dataset.plMood); return; }
      const ctl = e.target.closest('[data-pl]');
      if (ctl) {
        const a = ctl.dataset.pl;
        if (a === 'prev') step(-1); else if (a === 'next') step(1); else if (a === 'toggle') toggle();
        else if (a === 'playmood') await playMood(P.mood || curMood());
        else if (a === 'shuffle') { P.shuffle = !P.shuffle; try { localStorage.setItem('moodsync:shuffle', P.shuffle ? '1' : '0'); } catch (x) {} renderPage(); }
        else if (a === 'repeat') { P.repeat = !P.repeat; renderPage(); }
        else if (a === 'like' && P.cur) await feedback(P.cur.key, 'like');
        else if (a === 'seekbar' && P.cur && !P.cur.embed) { const r = ctl.getBoundingClientRect(); P.audio.currentTime = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)) * (P.audio.duration || 30); }
        return;
      }
      const row = e.target.closest('[data-pl-play]'); if (row) play(row.dataset.plPlay);
    });
    document.addEventListener('keydown', e => {
      const row = e.target.closest && e.target.closest('[data-pl-play]');
      if (row && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); play(row.dataset.plPlay); return; }
      if (e.key === ' ' && P.cur && !P.cur.embed && !/^(INPUT|TEXTAREA|SELECT|BUTTON|A)$/.test(e.target.tagName) && !e.target.isContentEditable) { e.preventDefault(); toggle(); }
    });
    $('#add-track-form').addEventListener('submit', async e => {
      e.preventDefault(); const msg = $('#at-msg'); msg.textContent = 'Adding…';
      try {
        const r = await api('/tracks', { method: 'POST', json: { url: $('#at-url').value.trim(), title: $('#at-title').value.trim(), artist: $('#at-artist').value.trim(), moods: [...P.atMoods] } });
        msg.textContent = `Added “${r.title}” ✿ It now shows up in your mood radio.`; e.target.reset(); P.atMoods.clear(); $$('[data-at-mood]').forEach(b => b.classList.remove('on'));
        await loadMine(); await loadMood(P.mood || curMood());
      } catch (err) { msg.textContent = err.message || 'Could not add that link.'; }
    });
    P.audio.addEventListener('volumechange', () => { try { localStorage.setItem('moodsync:vol', String(P.audio.volume)); } catch (e) {} });
    const vol = $('#dock-vol'); vol.value = P.audio.volume; vol.addEventListener('input', () => { P.audio.volume = parseFloat(vol.value); });
    $('#logout-btn').addEventListener('click', () => { P.audio.pause(); hideEmbed(); P.cur = null; P.queue = []; P.mood = null; P.mine = []; P._mineFor = null; renderAll(); });
    window.addEventListener('beforeunload', () => logPlay(false));
  }
  wire();
  window.MSPlayer = { renderPage, playMood, isPlaying, current: () => P.cur, audio: P.audio };
})();
