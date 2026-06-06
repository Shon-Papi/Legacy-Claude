/* ============================================================
   LifeOS — a portable, installable daily life-score dashboard.
   Vanilla JS PWA. State persists in localStorage.
   ============================================================ */
'use strict';

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const uid = () => Math.random().toString(36).slice(2, 9);
const todayKey = () => new Date().toISOString().slice(0, 10);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const DOW = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/* ---------------- state ---------------- */
const LS = 'lifeos-v1';
const KEY_LS = 'lifeos-overseer-key';
let S;

function freshState() {
  return {
    version: 1, day: todayKey(),
    name: '',
    metrics: {},          // { pillarId: { metricKey: value } }
    goals: [
      { id: uid(), text: 'Make 2 reels', done: false },
      { id: uid(), text: 'Polish the app', done: false },
      { id: uid(), text: 'Outline next video', done: false },
    ],
    history: [],          // [{date, score, breakdown}]
    streak: 0,
    config: { weights: {}, targets: {} },
  };
}

function load() {
  let raw;
  try { raw = JSON.parse(localStorage.getItem(LS)); } catch { raw = null; }
  if (!raw) { S = freshState(); save(); return; }
  S = Object.assign(freshState(), raw);
  S.config = Object.assign({ weights: {}, targets: {} }, S.config);
  if (S.day !== todayKey()) rollOver();
}

function rollOver() {
  // snapshot yesterday into history, then reset the day
  const ctx = goalCtx();
  const ls = lifeScore(S, ctx);
  S.history.push({ date: S.day, score: ls.score, breakdown: ls.breakdown });
  S.history = S.history.slice(-60);
  S.streak = ls.score >= 70 ? (S.streak || 0) + 1 : 0;
  S.day = todayKey();
  S.metrics = {};
  S.goals = S.goals.filter(g => !g.done).map(g => ({ id: uid(), text: g.text, done: false }));
  save();
}

function save() { localStorage.setItem(LS, JSON.stringify(S)); }

/* ---------------- metric helpers ---------------- */
function mval(pid, key) { return S.metrics[pid]?.[key]; }
function setMetric(pid, key, v) {
  (S.metrics[pid] ||= {})[key] = v;
  save(); renderToday();
}
function goalCtx() {
  return { goalTotal: S.goals.length, goalDone: S.goals.filter(g => g.done).length };
}

/* ---------------- score grade ---------------- */
function gradeFor(score) {
  if (score >= 90) return ['Elite', '#34d399'];
  if (score >= 75) return ['Dialed in', '#6ee7b7'];
  if (score >= 60) return ['On track', '#fbbf24'];
  if (score >= 40) return ['Building', '#f0a868'];
  if (score >= 1) return ['Slow start', '#fb7185'];
  return ['Log your day', '#8b8f9c'];
}
function scoreColor(score) {
  if (score >= 75) return '#34d399';
  if (score >= 60) return '#fbbf24';
  if (score >= 40) return '#f0a868';
  return '#fb7185';
}

/* ---------------- TODAY render ---------------- */
let openPillar = null;
let goalsExpanded = false;
const COLLAPSED = 4;

function renderToday() {
  const now = new Date();
  const hr = now.getHours();
  const hi = hr < 5 ? 'Still up?' : hr < 12 ? 'Good morning' : hr < 17 ? 'Afternoon' : hr < 21 ? 'Evening' : 'Wind down';
  $('#greeting').textContent = S.name ? `${hi}, ${S.name}` : hi;
  $('#todayDate').textContent = `${DOW[now.getDay()]}, ${MON[now.getMonth()]} ${now.getDate()}`;

  const ctx = goalCtx();
  const ls = lifeScore(S, ctx);

  // ring
  const C = 2 * Math.PI * 86;
  $('#ringFg').style.strokeDasharray = C;
  $('#ringFg').style.strokeDashoffset = C * (1 - ls.score / 100);
  $('#ringFg').style.stroke = scoreColor(ls.score);
  $('#lifeScore').textContent = ls.score;
  const [grade, gcol] = gradeFor(ls.score);
  const ge = $('#scoreGrade'); ge.textContent = grade; ge.style.color = gcol;

  // meta
  $('#streakNum').textContent = S.streak;
  const last7 = S.history.slice(-7);
  $('#avg7').textContent = last7.length ? Math.round(last7.reduce((s, h) => s + h.score, 0) / last7.length) : '—';
  $('#awakePct').textContent = awakePct() + '%';

  // pillars
  renderPillars(ctx);

  // goals
  renderGoals(ctx);

  // overseer quick chips (once)
  if (!$('#overseerQuick').dataset.init) initOverseerQuick();
}

function awakePct() {
  const now = new Date();
  const h = now.getHours() + now.getMinutes() / 60;
  return clamp(Math.round(((h - 6) / (24 - 6)) * 100), 0, 100);
}

function renderPillars(ctx) {
  const grid = $('#pillarGrid');
  grid.innerHTML = '';
  for (const p of PILLARS) {
    const ps = pillarScore(S, p, ctx);
    const el = document.createElement('div');
    el.className = 'pillar' + (openPillar === p.id ? ' open' : '');
    el.innerHTML = `
      <div class="pillar-top">
        <span class="pillar-emoji">${p.emoji}</span>
        <span class="pillar-name">${p.name}</span>
        <span class="pillar-score" style="color:${scoreColor(ps.score)}">${ps.score}</span>
      </div>
      <div class="pillar-bar"><div style="width:${ps.score}%;background:${p.color}"></div></div>
      <div class="pillar-weight">weight ${getWeight(S, p)}%</div>
      ${p.syncable ? '<span class="pillar-sync">sync soon</span>' : ''}`;
    el.onclick = (e) => {
      if (e.target.closest('.metric-box')) return; // don't toggle when interacting
      openPillar = openPillar === p.id ? null : p.id;
      renderPillars(ctx);
    };
    if (openPillar === p.id) el.appendChild(metricEditor(p));
    grid.appendChild(el);
  }
}

function metricEditor(p) {
  const box = document.createElement('div');
  box.className = 'metric-box';
  box.onclick = e => e.stopPropagation();
  if (p.blurb) {
    const b = document.createElement('div');
    b.className = 'metric-blurb'; b.textContent = p.blurb;
    box.appendChild(b);
  }
  for (const m of p.metrics) {
    if (m.type === 'derived') {
      const ctx = goalCtx();
      const row = document.createElement('div');
      row.className = 'metric';
      row.innerHTML = `<div class="metric-label">${m.label}<small>${ctx.goalDone}/${ctx.goalTotal} goals done — manage in Goals below</small></div>`;
      box.appendChild(row);
      continue;
    }
    box.appendChild(metricRow(p, m));
  }
  return box;
}

function metricRow(p, m) {
  const row = document.createElement('div');
  row.className = 'metric';
  const target = getTarget(S, p.id, m);
  const val = mval(p.id, m.key);
  const label = `<div class="metric-label">${m.label}${m.type !== 'toggle' ? `<small>target ${target}${m.unit ? ' ' + m.unit : ''}</small>` : ''}</div>`;

  if (m.type === 'toggle') {
    row.innerHTML = label + `<button class="toggle ${val ? 'on' : ''}" aria-label="toggle"></button>`;
    row.querySelector('.toggle').onclick = () => setMetric(p.id, m.key, !val);
  } else if (m.type === 'counter') {
    row.innerHTML = label + `<div class="stepper">
      <button class="step-btn minus">−</button>
      <span class="step-val">${val || 0}<small>/${target}</small></span>
      <button class="step-btn plus">+</button></div>`;
    row.querySelector('.plus').onclick = () => setMetric(p.id, m.key, (Number(val) || 0) + 1);
    row.querySelector('.minus').onclick = () => setMetric(p.id, m.key, Math.max(0, (Number(val) || 0) - 1));
  } else if (m.type === 'slider') {
    row.innerHTML = label + `<input class="slider" type="range" min="0" max="${m.max}" step="1" value="${val || 0}">
      <span class="slider-val">${val || 0}</span>`;
    const sl = row.querySelector('.slider');
    sl.oninput = () => { row.querySelector('.slider-val').textContent = sl.value; };
    sl.onchange = () => setMetric(p.id, m.key, Number(sl.value));
  } else { // number
    row.innerHTML = label + `<div class="stepper">
      <button class="step-btn minus">−</button>
      <input class="num-input" type="number" inputmode="decimal" value="${val ?? ''}" step="${m.step || 1}" min="0" max="${m.max || ''}">
      <button class="step-btn plus">+</button></div>`;
    const inp = row.querySelector('.num-input');
    const step = m.step || 1;
    inp.onchange = () => setMetric(p.id, m.key, clamp(Number(inp.value) || 0, 0, m.max || 1e9));
    row.querySelector('.plus').onclick = () => { inp.value = clamp((Number(inp.value) || 0) + step, 0, m.max || 1e9); setMetric(p.id, m.key, Number(inp.value)); };
    row.querySelector('.minus').onclick = () => { inp.value = clamp((Number(inp.value) || 0) - step, 0, m.max || 1e9); setMetric(p.id, m.key, Number(inp.value)); };
  }
  return row;
}

/* ---------------- goals ---------------- */
function renderGoals(ctx = goalCtx()) {
  $('#goalDone').textContent = ctx.goalDone;
  $('#goalTotal').textContent = ctx.goalTotal;
  const list = $('#goalList');
  const shown = goalsExpanded ? S.goals : S.goals.slice(0, COLLAPSED);
  list.innerHTML = '';
  shown.forEach(g => {
    const li = document.createElement('li');
    li.className = 'goal-item' + (g.done ? ' done' : '');
    li.innerHTML = `<span class="check ${g.done ? 'done' : ''}"></span><span class="goal-text">${esc(g.text)}</span><span class="del">✕</span>`;
    li.querySelector('.check').onclick = li.querySelector('.goal-text').onclick = () => { g.done = !g.done; save(); renderToday(); };
    li.querySelector('.del').onclick = () => { S.goals = S.goals.filter(x => x.id !== g.id); save(); renderToday(); };
    list.appendChild(li);
  });
  const hidden = S.goals.length - COLLAPSED;
  const b = $('#showMoreBtn');
  b.hidden = hidden <= 0;
  if (hidden > 0) b.textContent = goalsExpanded ? 'Show less ▴' : `Show ${hidden} more ▾`;
}

/* ---------------- TRENDS ---------------- */
function renderTrends() {
  const ctx = goalCtx();
  const ls = lifeScore(S, ctx);
  const series = [...S.history.slice(-13), { date: S.day, score: ls.score, breakdown: ls.breakdown, today: true }];
  $('#tsToday').textContent = ls.score;
  const past = S.history.slice(-7);
  $('#ts7').textContent = past.length ? Math.round(past.reduce((s, h) => s + h.score, 0) / past.length) : ls.score;
  const allScores = [...S.history.map(h => h.score), ls.score];
  $('#tsBest').textContent = Math.max(...allScores);
  $('#tsStreak').textContent = S.streak;

  // bars
  const bars = $('#trendBars');
  bars.innerHTML = '';
  series.forEach(h => {
    const d = new Date(h.date + 'T00:00');
    const col = document.createElement('div');
    col.className = 'bar-col';
    col.innerHTML = `<div class="bar ${h.today ? 'today' : ''} ${h.score ? '' : 'bar-empty'}"
        style="height:${Math.max(3, h.score)}%;${h.score ? `background:linear-gradient(180deg,${scoreColor(h.score)},#16624a)` : ''}"
        title="${h.score}"></div>
      <div class="bar-lbl">${'SMTWTFS'[d.getDay()]}</div>`;
    bars.appendChild(col);
  });

  // pillar 7d averages (include today live)
  const avgEl = $('#pillarAverages');
  avgEl.innerHTML = '';
  for (const p of PILLARS) {
    const vals = [...S.history.slice(-6).map(h => h.breakdown?.[p.id] ?? 0), pillarScore(S, p, ctx).score];
    const avg = Math.round(vals.reduce((s, v) => s + v, 0) / vals.length);
    const row = document.createElement('div');
    row.className = 'pavg-row';
    row.innerHTML = `<span class="pavg-emoji">${p.emoji}</span>
      <span class="pavg-name">${p.name}</span>
      <span class="pavg-bar"><div style="width:${avg}%;background:${p.color}"></div></span>
      <span class="pavg-num">${avg}</span>`;
    avgEl.appendChild(row);
  }
}

/* ---------------- SETTINGS ---------------- */
function renderSettings() {
  $('#nameInput').value = S.name || '';

  // weights
  const wl = $('#weightList');
  wl.innerHTML = '';
  PILLARS.forEach(p => {
    const w = getWeight(S, p);
    const row = document.createElement('div');
    row.className = 'wrow';
    row.innerHTML = `<span class="we">${p.emoji}</span><span class="wn">${p.name}</span>
      <input type="range" min="0" max="30" value="${w}"><span class="wv">${w}%</span>`;
    const sl = row.querySelector('input');
    sl.oninput = () => { row.querySelector('.wv').textContent = sl.value + '%'; updateWeightTotal(); };
    sl.onchange = () => { (S.config.weights)[p.id] = Number(sl.value); save(); renderToday(); };
    wl.appendChild(row);
  });
  updateWeightTotal();

  // targets
  const tl = $('#targetList');
  tl.innerHTML = '';
  PILLARS.forEach(p => p.metrics.forEach(m => {
    if (m.type === 'toggle' || m.type === 'derived') return;
    const t = getTarget(S, p.id, m);
    const row = document.createElement('div');
    row.className = 'trow';
    row.innerHTML = `<span class="we">${p.emoji}</span>
      <span class="tn">${m.label}<small> ${p.name}</small></span>
      <input class="num-input" type="number" inputmode="decimal" value="${t}" step="${m.step || 1}" min="0">`;
    const inp = row.querySelector('input');
    inp.onchange = () => { (S.config.targets[p.id] ||= {})[m.key] = Number(inp.value) || m.target; save(); renderToday(); };
    tl.appendChild(row);
  }));

  // key state
  $('#keyInput').value = '';
  $('#overseerMode').textContent = localStorage.getItem(KEY_LS) ? 'Claude' : 'local';
}

function updateWeightTotal() {
  const total = PILLARS.reduce((s, p) => {
    const sl = [...$$('#weightList .wrow')].find(r => r.querySelector('.wn').textContent === p.name)?.querySelector('input');
    return s + (sl ? Number(sl.value) : getWeight(S, p));
  }, 0);
  const el = $('#weightTotal');
  el.textContent = total + '%';
  el.style.color = total === 100 ? 'var(--green)' : 'var(--amber)';
}

/* ---------------- OVERSEER ---------------- */
function ctxForOverseer() {
  const ctx = goalCtx();
  const ls = lifeScore(S, ctx);
  const pillars = PILLARS.map(p => ({ name: p.name, score: pillarScore(S, p, ctx).score, weight: getWeight(S, p) }));
  const weakest = [...pillars].sort((a, b) => a.score - b.score)[0];
  return {
    name: S.name || 'you', date: $('#todayDate').textContent,
    lifeScore: ls.score, streak: S.streak,
    goals: `${ctx.goalDone}/${ctx.goalTotal}`,
    remainingGoals: S.goals.filter(g => !g.done).map(g => g.text),
    pillars, weakest: weakest?.name,
  };
}
function localAnswer(q) {
  const c = ctxForOverseer(); const t = q.toLowerCase();
  if (/score|how.*doing|recap|summary|status/.test(t))
    return `Life Score ${c.lifeScore}/100 today · ${c.streak}-day streak · goals ${c.goals}.\nWeakest pillar: ${c.weakest}. ${c.lifeScore < 70 ? 'Push there to break 70.' : 'Strong day — keep it.'}`;
  if (/weak|worst|lowest|improve|focus|where/.test(t))
    return `Your lowest pillar is ${c.weakest}. Open it on Today and log a quick win — it moves your score the most.`;
  if (/goal|todo|left|remain|next/.test(t))
    return c.remainingGoals.length ? `${c.remainingGoals.length} goals left:\n• ${c.remainingGoals.slice(0, 6).join('\n• ')}` : 'All goals done. 🔥';
  if (/streak/.test(t)) return `You're on a ${c.streak}-day streak. Stay above 70 to keep it alive.`;
  if (/strong|best|good|highest/.test(t)) {
    const best = [...c.pillars].sort((a, b) => b.score - a.score)[0];
    return `Your strongest pillar is ${best.name} at ${best.score}. Nice.`;
  }
  if (/\b(hi|hey|hello|yo|sup)\b/.test(t)) return `Hey${S.name ? ' ' + S.name : ''}. You're at ${c.lifeScore}/100. Want a recap or your weak spot?`;
  if (/help|what can/.test(t)) return 'Ask me: your score, a recap, your weakest pillar, what goals are left, or your streak.';
  return `You're at ${c.lifeScore}/100 with a ${c.streak}-day streak. Lowest pillar: ${c.weakest}. Ask for a recap or what to focus on.`;
}
async function askOverseer(q) {
  const key = localStorage.getItem(KEY_LS);
  if (!key) return localAnswer(q);
  try {
    const res = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-api-key': key, 'anthropic-version': '2023-06-01', 'anthropic-dangerous-direct-browser-access': 'true' },
      body: JSON.stringify({
        model: 'claude-haiku-4-5-20251001', max_tokens: 400,
        system: "You are Overseer, the assistant inside a personal life-score dashboard. You see the user's live scores. Be concise, sharp, and motivating — like a chief of staff. Reference the real numbers.",
        messages: [{ role: 'user', content: `Live state:\n${JSON.stringify(ctxForOverseer(), null, 2)}\n\nQuestion: ${q}` }],
      }),
    });
    const d = await res.json();
    return d?.content?.[0]?.text || localAnswer(q);
  } catch { return localAnswer(q); }
}
function pushMsg(text, who) {
  const m = document.createElement('div'); m.className = `msg ${who}`; m.textContent = text;
  $('#overseerThread').appendChild(m); m.scrollIntoView({ block: 'nearest' }); return m;
}
async function sendOverseer(text) {
  const inp = $('#overseerInput');
  const q = (text ?? inp.value).trim(); if (!q) return;
  inp.value = '';
  pushMsg(q, 'user');
  const thinking = pushMsg('…', 'bot thinking');
  const a = await askOverseer(q);
  thinking.remove(); pushMsg(a, 'bot');
}
function initOverseerQuick() {
  const wrap = $('#overseerQuick');
  wrap.dataset.init = '1';
  [['Recap', "Give me a recap"], ['Weak spot', "What's my weakest pillar?"], ['Goals left', 'What goals are left?'], ['Streak', "How's my streak?"]]
    .forEach(([label, q]) => {
      const c = document.createElement('button');
      c.className = 'qchip'; c.textContent = label;
      c.onclick = () => sendOverseer(q);
      wrap.appendChild(c);
    });
}

/* ---------------- SEARCH ---------------- */
function runSearch(q) {
  const out = $('#searchResults'); out.innerHTML = ''; q = q.trim().toLowerCase();
  if (!q) { out.innerHTML = '<div class="sr-empty">Search goals and pillars…</div>'; return; }
  const hits = [];
  S.goals.forEach(g => g.text.toLowerCase().includes(q) && hits.push(['Goal', g.text, () => switchTab('today')]));
  PILLARS.forEach(p => {
    if (p.name.toLowerCase().includes(q) || p.metrics.some(m => m.label.toLowerCase().includes(q)))
      hits.push(['Pillar', `${p.emoji} ${p.name}`, () => { switchTab('today'); openPillar = p.id; renderToday(); }]);
  });
  if (!hits.length) { out.innerHTML = '<div class="sr-empty">No matches.</div>'; return; }
  hits.forEach(([cat, text, go]) => {
    const d = document.createElement('div'); d.className = 'sr-item';
    d.innerHTML = `<div class="sr-cat">${cat}</div><div>${esc(text)}</div>`;
    d.onclick = () => { $('#searchModal').hidden = true; go(); };
    out.appendChild(d);
  });
}

/* ---------------- nav / toast ---------------- */
function switchTab(name) {
  $$('.page').forEach(p => p.hidden = p.dataset.page !== name);
  $$('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === name));
  if (name === 'trends') renderTrends();
  if (name === 'settings') renderSettings();
  if (name === 'today') renderToday();
  const sc = document.querySelector(`.page[data-page="${name}"] .scroll`);
  if (sc) sc.scrollTop = 0;
}
let toastT;
function toast(msg) { const e = $('#toast'); e.textContent = msg; e.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => e.hidden = true, 2200); }

/* ---------------- wire up ---------------- */
let deferredPrompt = null;
function init() {
  load();
  renderToday();

  $$('.tab').forEach(t => t.onclick = () => switchTab(t.dataset.tab));

  // goals
  $('#addGoalForm').onsubmit = e => { e.preventDefault(); const v = $('#addGoalInput').value.trim(); if (!v) return; S.goals.push({ id: uid(), text: v, done: false }); $('#addGoalInput').value = ''; save(); renderToday(); };
  $('#showMoreBtn').onclick = () => { goalsExpanded = !goalsExpanded; renderGoals(); };

  // end day
  $('#endDayBtn').onclick = () => {
    const ls = lifeScore(S, goalCtx());
    if (confirm(`End the day with a Life Score of ${ls.score}?\nThis saves today to your history and starts fresh.`)) {
      rollOver(); openPillar = null; goalsExpanded = false; renderToday(); switchTab('trends');
      toast(`Day saved · ${ls.score}/100`);
    }
  };

  // overseer
  $('#overseerSend').onclick = () => sendOverseer();
  $('#overseerInput').addEventListener('keydown', e => { if (e.key === 'Enter') sendOverseer(); });

  // search
  $('#searchBtn').onclick = () => { $('#searchModal').hidden = false; $('#searchInput').focus(); runSearch(''); };
  $('#closeSearch').onclick = () => $('#searchModal').hidden = true;
  $('#searchInput').addEventListener('input', e => runSearch(e.target.value));

  // settings: name
  $('#nameForm').onsubmit = e => { e.preventDefault(); S.name = $('#nameInput').value.trim(); save(); renderToday(); toast('Saved'); };
  // settings: key
  $('#keyForm').onsubmit = e => { e.preventDefault(); const k = $('#keyInput').value.trim(); if (!k) return; localStorage.setItem(KEY_LS, k); $('#keyInput').value = ''; $('#overseerMode').textContent = 'Claude'; renderSettings(); toast('Overseer → Claude ✦'); };
  $('#clearKey').onclick = () => { localStorage.removeItem(KEY_LS); $('#overseerMode').textContent = 'local'; renderSettings(); toast('Overseer → local'); };

  // data
  $('#exportBtn').onclick = () => {
    const blob = new Blob([JSON.stringify(S, null, 2)], { type: 'application/json' });
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = `lifeos-${todayKey()}.json`; a.click();
    URL.revokeObjectURL(a.href);
  };
  $('#importBtn').onclick = () => $('#importFile').click();
  $('#importFile').onchange = e => {
    const f = e.target.files[0]; if (!f) return;
    const r = new FileReader();
    r.onload = () => { try { S = Object.assign(freshState(), JSON.parse(r.result)); save(); renderToday(); switchTab('today'); toast('Data imported'); } catch { toast('Invalid file'); } };
    r.readAsText(f);
  };
  $('#resetBtn').onclick = () => { if (confirm('Erase all LifeOS data on this device?')) { S = freshState(); save(); openPillar = null; renderToday(); switchTab('today'); toast('Reset'); } };

  // PWA install
  window.addEventListener('beforeinstallprompt', e => { e.preventDefault(); deferredPrompt = e; $('#installCard').hidden = false; });
  $('#installBtn').onclick = async () => { if (!deferredPrompt) return; deferredPrompt.prompt(); await deferredPrompt.userChoice; deferredPrompt = null; $('#installCard').hidden = true; };

  // service worker
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});

  // refresh time-based bits + detect day change
  setInterval(() => { if (S.day !== todayKey()) { rollOver(); openPillar = null; } renderToday(); }, 60000);
}

document.addEventListener('DOMContentLoaded', init);
