/* ============================================================
   Rowan's Dashboard — a personal "life OS"
   Vanilla JS, no build step, localStorage persistence.
   Inspired by @rowanthislebrooke's reel.
   ============================================================ */
'use strict';

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const uid = () => Math.random().toString(36).slice(2, 9);
const todayKey = () => new Date().toISOString().slice(0, 10);

/* ---------- default seed (matches the reel) ---------- */
const SEED = {
  dayType: 'PULL DAY',
  wakeHour: 6,            // 6:00 AM
  sleepHour: 24,          // midnight
  waterGoal: 6,
  streak: 0,
  goals: [
    'Work with Aria and actually figure out the scripts and website + how it works',
    'Make 2 reels',
    'Call Apple about new phone and decide',
    'Polish app more',
    'Finish Discord and plan what you want on it',
    'Ship the schedule modal',
    'Reply to brand DMs',
    'Outline next YouTube video',
    'Read 20 pages',
    'Stretch + mobility 10 min',
  ].map(t => ({ id: uid(), text: t, done: false })),
  tomorrow: [],
  struggles: ['Too many open loops', 'Phone in the morning', 'Sleep schedule drifting'],
  wins: ['Hit gym 12 days straight', 'Crossed 195 subs', 'Stayed off doomscroll till noon'],
  water: 2,
  schedule: {
    lesroches: {
      Morning: {
        'Pre-shower': ['Water bottle → brush teeth', 'Electric shaver → nose shaver', 'Contacts → shower'],
        'Post-shower': ['Towel dry → sea salt spray (top + roots) → scrunch', 'Lotion → underwear', 'Sunscreen tint (eye-bags, forehead)', 'Dry hair → comb → eyelash curl → men pen → chapstick', 'Outfit'],
        'Leave + morning': ['Light breakfast (protein / debloat / carbs)', 'Caffeine — monster or double espresso', 'Grab: water, airpods, phone, etc.'],
      },
      Night: {
        'Teeth whitening': ['Teeth whitening strips'],
        '30 min before bed': ['Shower', 'Lotion', 'Minoxidil', 'Read / no phone'],
      },
    },
    bern: {
      Morning: {
        'Pre-shower': ['Water → brush teeth', 'Shave'],
        'Post-shower': ['Hair routine', 'Skincare', 'Outfit'],
        'Leave + morning': ['Breakfast', 'Coffee', 'Pack bag'],
      },
      Night: {
        'Wind down': ['Shower', 'Skincare', 'Journal', 'No phone 30 min'],
      },
    },
  },
  scheduleDone: {},   // { "lesroches::Morning::Pre-shower::0": true }
};

/* ---------- persistence ---------- */
const LS_KEY = 'rowan-dashboard-v1';
let S;
function load() {
  try {
    const raw = JSON.parse(localStorage.getItem(LS_KEY));
    S = raw && raw.day === todayKey() ? raw
      : raw ? rollOver(raw) : { day: todayKey(), ...structuredClone(SEED) };
  } catch { S = { day: todayKey(), ...structuredClone(SEED) }; }
  // ensure shape
  S = Object.assign({ day: todayKey() }, structuredClone(SEED), S);
}
function rollOver(prev) {
  // New day: bump streak if yesterday finished, carry tomorrow → today.
  const finished = prev.goals.length && prev.goals.every(g => g.done);
  const next = { ...prev, day: todayKey() };
  next.streak = finished ? (prev.streak || 0) + 1 : 0;
  next.goals = (prev.tomorrow && prev.tomorrow.length ? prev.tomorrow : prev.goals.filter(g => !g.done))
    .map(g => ({ id: uid(), text: g.text, done: false }));
  next.tomorrow = [];
  next.water = 0;
  next.scheduleDone = {};
  return next;
}
function save() { localStorage.setItem(LS_KEY, JSON.stringify(S)); }

/* ---------- date helpers ---------- */
const DOW = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'];
const MON = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
const fmtDay = d => `${DOW[d.getDay()]}, ${MON[d.getMonth()]} ${d.getDate()}`;

/* ---------- time of day ---------- */
function renderTimeOfDay() {
  const now = new Date();
  const h = now.getHours() + now.getMinutes() / 60;
  const wake = S.wakeHour, sleep = S.sleepHour;
  let pct = Math.round(((h - wake) / (sleep - wake)) * 100);
  pct = Math.max(0, Math.min(100, pct));
  const minsLeft = Math.max(0, Math.round((sleep - h) * 60));
  const hh = Math.floor(minsLeft / 60), mm = minsLeft % 60;

  let label = '⚡ Midday — keep moving';
  if (h < 9) label = '🌅 Morning — own the start';
  else if (h < 12) label = '☀️ Late morning — deep work';
  else if (h < 17) label = '⚡ Midday — keep moving';
  else if (h < 21) label = '🌇 Evening — finish strong';
  else label = '🌙 Night — wind down';

  $('#todLabel').textContent = label;
  $('#todTime').textContent = now.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  $('#todPct').textContent = pct + '%';
  $('#todFill').style.width = pct + '%';
  $('#todSub').textContent = h >= sleep ? 'Past bedtime — rest up' : `${hh}h ${mm}m of awake time left`;
}

/* ---------- header ---------- */
function renderHeader() {
  const d = new Date();
  $('#dayPillText').textContent = `${fmtDay(d)} · ${S.dayType}`;
  $('#waterCount').textContent = S.water;
  $('#moodChip').querySelector('span').textContent = S.struggles.length;
  $('#goalTodayLabel').textContent = `TODAY — ${fmtDay(d)}`;
  const t = new Date(d); t.setDate(t.getDate() + 1);
  $('#tmrwLabel').textContent = fmtDay(t);
  $('#schedDate').textContent = fmtDay(d);
}

/* ---------- goals ---------- */
let goalsExpanded = false;
const COLLAPSED = 5;
function renderGoals() {
  const list = $('#goalList');
  const done = S.goals.filter(g => g.done).length;
  $('#goalDone').textContent = done;
  $('#goalTotal').textContent = S.goals.length;
  $('#streakCount').textContent = S.streak;
  $('#goalProgressFill').style.width = (S.goals.length ? (done / S.goals.length) * 100 : 0) + '%';

  const shown = goalsExpanded ? S.goals : S.goals.slice(0, COLLAPSED);
  list.innerHTML = '';
  shown.forEach(g => list.appendChild(goalRow(g)));

  const hidden = S.goals.length - COLLAPSED;
  const btn = $('#showMoreBtn');
  btn.hidden = hidden <= 0;
  if (hidden > 0) {
    btn.innerHTML = goalsExpanded ? 'Show less ▴' : `Show ${hidden} more ▾`;
  }
}
function goalRow(g) {
  const li = document.createElement('li');
  li.className = 'goal-item' + (g.done ? ' done' : '');
  li.innerHTML = `<span class="check ${g.done ? 'done' : ''}"></span>
    <span class="goal-text">${esc(g.text)}</span>
    <span class="del" title="Delete">✕</span>`;
  li.querySelector('.check').onclick = li.querySelector('.goal-text').onclick = () => {
    g.done = !g.done; save(); renderGoals(); maybeCelebrate();
  };
  li.querySelector('.del').onclick = () => {
    S.goals = S.goals.filter(x => x.id !== g.id); save(); renderGoals();
  };
  return li;
}
function maybeCelebrate() {
  if (S.goals.length && S.goals.every(g => g.done)) toast('🔥 All goals done — streak locks at end of day');
}

/* ---------- tomorrow ---------- */
function renderTomorrow() {
  const list = $('#tmrwList');
  list.innerHTML = '';
  S.tomorrow.forEach(g => {
    const li = document.createElement('li');
    li.className = 'goal-item';
    li.innerHTML = `<span class="check"></span><span class="goal-text">${esc(g.text)}</span><span class="del">✕</span>`;
    li.querySelector('.del').onclick = () => { S.tomorrow = S.tomorrow.filter(x => x.id !== g.id); save(); renderTomorrow(); };
    list.appendChild(li);
  });
  $('#tmrwEmpty').hidden = S.tomorrow.length > 0;
}

/* ---------- struggles & wins ---------- */
function renderTags(arr, ul, cls, key) {
  ul.innerHTML = '';
  arr.forEach((text, i) => {
    const li = document.createElement('li');
    li.className = 'tag';
    li.innerHTML = `<span class="dot"></span><span class="t">${esc(text)}</span><span class="del">✕</span>`;
    li.querySelector('.del').onclick = () => { arr.splice(i, 1); save(); renderLists(); };
    ul.appendChild(li);
  });
}
function renderLists() {
  renderTags(S.struggles, $('#struggleList'), 'amber');
  renderTags(S.wins, $('#winList'), 'green');
  $('#struggleCount').textContent = S.struggles.length;
  $('#winCount').textContent = S.wins.length;
  $('#moodChip').querySelector('span').textContent = S.struggles.length;
}

/* ---------- water ---------- */
function renderWater() {
  $('#waterBig').textContent = S.water;
  $('#waterCount').textContent = S.water;
  $('#waterGoal').textContent = S.waterGoal;
  const dots = $('#waterDots');
  dots.innerHTML = '';
  const n = Math.max(S.waterGoal, S.water);
  for (let i = 0; i < n; i++) {
    const d = document.createElement('div');
    d.className = 'wdot' + (i < S.water ? ' full' : '');
    dots.appendChild(d);
  }
}

/* ---------- schedule modal ---------- */
let curLoc = 'lesroches';
function renderSchedule() {
  const body = $('#scheduleBody');
  body.innerHTML = '';
  const loc = S.schedule[curLoc];
  for (const [period, groups] of Object.entries(loc)) {
    const sec = document.createElement('div');
    sec.className = 'routine';
    const icon = period === 'Morning' ? '🌅' : '🌙';
    sec.innerHTML = `<div class="routine-title">${icon} ${period}</div>`;
    for (const [grp, items] of Object.entries(groups)) {
      const sub = document.createElement('div');
      sub.className = 'routine-sub';
      sub.textContent = grp;
      sec.appendChild(sub);
      items.forEach((it, idx) => {
        const k = `${curLoc}::${period}::${grp}::${idx}`;
        const done = !!S.scheduleDone[k];
        const row = document.createElement('div');
        row.className = 'routine-item' + (done ? ' done' : '');
        row.innerHTML = `<span class="check ${done ? 'done' : ''}"></span><span class="rt">${esc(it)}</span>`;
        row.querySelector('.check').onclick = row.querySelector('.rt').onclick = () => {
          S.scheduleDone[k] = !S.scheduleDone[k]; save(); renderSchedule();
        };
        sec.appendChild(row);
      });
    }
    body.appendChild(sec);
  }
}

/* ---------- other tabs (static-ish demo data) ---------- */
function renderOtherTabs() {
  // brand sparkline
  const pts = [120, 134, 141, 150, 162, 171, 180, 195];
  const max = Math.max(...pts), min = Math.min(...pts);
  const poly = pts.map((v, i) => `${(i / (pts.length - 1)) * 200},${44 - ((v - min) / (max - min)) * 40}`).join(' ');
  if ($('#ytSpark')) $('#ytSpark').setAttribute('points', poly);

  fillRows('#brandPipe', [
    ['🎬', 'How I built my dashboard with Claude', 'reel · scripting', 'WIP', 'wip'],
    ['📹', 'Day in the life — Les Roches', 'long-form', 'idea', 'idea'],
    ['📸', 'Brand photoshoot batch', '12 posts queued', 'done', 'done'],
    ['💬', 'Plan Discord launch', 'community', 'idea', 'idea'],
  ]);
  fillRows('#txList', [
    ['☕', 'Coffee · Bern', 'today', '−$5.20', ''],
    ['🛒', 'Groceries', 'yesterday', '−$62.10', ''],
    ['💸', 'Brand deal payout', '2 days ago', '+$1,200', 'up'],
    ['📱', 'Phone bill', '3 days ago', '−$40.00', ''],
  ]);
  fillRows('#suppList', [
    ['💊', 'Creatine 5g', 'daily', '✓', ''],
    ['🐟', 'Omega-3', 'with breakfast', '✓', ''],
    ['🌿', 'Vitamin D', 'morning', '—', ''],
    ['💤', 'Magnesium', 'before bed', '—', ''],
  ]);
  fillRows('#gymList', [
    ['🏋️', 'Lat pulldown', '4 × 10', '', ''],
    ['💪', 'Barbell row', '4 × 8', '', ''],
    ['🎯', 'Face pulls', '3 × 15', '', ''],
    ['🦾', 'Hammer curls — 20s', '4 × 12', '', ''],
    ['🧗', 'Pull-ups', '3 × failure', '', ''],
  ]);
}
function fillRows(sel, rows) {
  const el = $(sel); if (!el) return;
  el.innerHTML = '';
  rows.forEach(([ic, main, sub, right, cls]) => {
    const r = document.createElement('div');
    r.className = 'list-row';
    const badge = ['done', 'wip', 'idea'].includes(cls)
      ? `<span class="badge ${cls}">${right}</span>`
      : `<span class="lr-right ${cls}">${right}</span>`;
    r.innerHTML = `<span class="lr-ic">${ic}</span><div class="lr-main">${esc(main)}<div class="lr-sub">${esc(sub)}</div></div>${badge}`;
    el.appendChild(r);
  });
}

/* ============================================================
   OVERSEER — context-aware assistant.
   Answers locally from live dashboard state. If a Claude API
   key is saved (Settings), it proxies the question to Claude
   with the dashboard as context.
   ============================================================ */
const OverseerKey = 'rowan-overseer-key';
function dashboardContext() {
  const remaining = S.goals.filter(g => !g.done);
  return {
    date: fmtDay(new Date()), dayType: S.dayType, streak: S.streak,
    goalsTotal: S.goals.length, goalsDone: S.goals.length - remaining.length,
    remaining: remaining.map(g => g.text),
    tomorrow: S.tomorrow.map(g => g.text),
    struggles: S.struggles, wins: S.wins,
    water: `${S.water}/${S.waterGoal} bottles`,
  };
}
function localAnswer(q) {
  const c = dashboardContext(); const t = q.toLowerCase();
  if (/streak/.test(t)) return `You're on a ${c.streak}-day streak. Finish all ${c.goalsTotal} goals today to extend it.`;
  if (/water|hydrat|drink/.test(t)) return `You've had ${c.water}. ${S.water < S.waterGoal ? `${S.waterGoal - S.water} to go — tap + on the Water card.` : 'Goal hit. 💧'}`;
  if (/(left|remain|still|to ?do|next|focus)/.test(t)) {
    if (!c.remaining.length) return 'Nothing left — all goals are done. 🔥 Lock the streak by ending the day.';
    return `${c.remaining.length} goals left:\n• ${c.remaining.slice(0, 6).join('\n• ')}\nStart with the one you've been avoiding.`;
  }
  if (/struggl|stress|stuck|mind|worr/.test(t)) return c.struggles.length ? `On your mind right now:\n• ${c.struggles.join('\n• ')}\nPick one and turn it into a single next action.` : 'Nothing logged under struggles. Clear head. 🧘';
  if (/win|good|positive|going right/.test(t)) return c.wins.length ? `Wins worth remembering:\n• ${c.wins.join('\n• ')}` : 'Add a win — even a small one counts.';
  if (/tomorrow|plan/.test(t)) return c.tomorrow.length ? `Tomorrow's plan:\n• ${c.tomorrow.join('\n• ')}` : 'Tomorrow is empty. Write it tonight — locked until 6 AM.';
  if (/schedule|routine|morning|night/.test(t)) return 'Open the Schedule (🗓 top right) for your morning + night routines. Toggle between Les Roches and Bern.';
  if (/progress|how.*doing|summary|status|recap/.test(t))
    return `${c.date} · ${c.dayType}\n${c.goalsDone}/${c.goalsTotal} goals · ${c.streak}-day streak · ${c.water}\n${c.remaining.length ? `Next up: ${c.remaining[0]}` : 'All goals done. 🔥'}`;
  if (/(^|\b)(hi|hey|hello|yo|sup)\b/.test(t)) return `Hey. ${c.goalsDone}/${c.goalsTotal} goals done so far. What do you want to tackle?`;
  if (/help|what can you|who are you/.test(t)) return 'I read your whole dashboard. Ask me what\'s left, your streak, water, struggles, wins, tomorrow\'s plan, or for a recap.';
  return `Here's where you stand:\n${c.goalsDone}/${c.goalsTotal} goals done · ${c.streak}-day streak · ${c.water}.\n${c.remaining.length ? `Top priority: ${c.remaining[0]}` : 'Everything\'s done. 🔥'}`;
}
async function askOverseer(q) {
  const key = localStorage.getItem(OverseerKey);
  if (!key) return localAnswer(q);
  try {
    const res = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-api-key': key,
        'anthropic-version': '2023-06-01',
        'anthropic-dangerous-direct-browser-access': 'true',
      },
      body: JSON.stringify({
        model: 'claude-haiku-4-5-20251001',
        max_tokens: 400,
        system: 'You are Overseer, the assistant inside Rowan\'s personal life-OS dashboard. You can see the live dashboard JSON. Be concise, direct, and motivating — like a sharp chief of staff. Reference the actual data.',
        messages: [{ role: 'user', content: `Dashboard state:\n${JSON.stringify(dashboardContext(), null, 2)}\n\nQuestion: ${q}` }],
      }),
    });
    const data = await res.json();
    return data?.content?.[0]?.text || localAnswer(q);
  } catch { return localAnswer(q); }
}
function pushMsg(text, who) {
  const m = document.createElement('div');
  m.className = `msg ${who}`;
  m.textContent = text;
  $('#overseerThread').appendChild(m);
  m.scrollIntoView({ block: 'nearest' });
  return m;
}
async function sendOverseer() {
  const inp = $('#overseerInput');
  const q = inp.value.trim();
  if (!q) return;
  inp.value = '';
  pushMsg(q, 'user');
  const thinking = pushMsg('Thinking…', 'bot thinking');
  const a = await askOverseer(q);
  thinking.remove();
  pushMsg(a, 'bot');
}

/* ---------- search ---------- */
function runSearch(q) {
  const out = $('#searchResults');
  out.innerHTML = '';
  q = q.trim().toLowerCase();
  if (!q) { out.innerHTML = '<div class="sr-empty">Type to search goals, schedule, struggles, wins…</div>'; return; }
  const hits = [];
  S.goals.forEach(g => g.text.toLowerCase().includes(q) && hits.push(['Goal', g.text, 'main']));
  S.tomorrow.forEach(g => g.text.toLowerCase().includes(q) && hits.push(['Tomorrow', g.text, 'main']));
  S.struggles.forEach(t => t.toLowerCase().includes(q) && hits.push(['Struggle', t, 'main']));
  S.wins.forEach(t => t.toLowerCase().includes(q) && hits.push(['Win', t, 'main']));
  Object.entries(S.schedule).forEach(([loc, periods]) =>
    Object.entries(periods).forEach(([p, groups]) =>
      Object.values(groups).flat().forEach(it =>
        it.toLowerCase().includes(q) && hits.push([`${loc} · ${p}`, it, 'schedule']))));
  if (!hits.length) { out.innerHTML = '<div class="sr-empty">No matches.</div>'; return; }
  hits.slice(0, 30).forEach(([cat, text, target]) => {
    const d = document.createElement('div');
    d.className = 'sr-item';
    d.innerHTML = `<div class="sr-cat">${esc(cat)}</div><div class="sr-text">${esc(text)}</div>`;
    d.onclick = () => {
      closeModal('#searchModal');
      if (target === 'schedule') openSchedule();
      else switchTab('main');
    };
    out.appendChild(d);
  });
}

/* ---------- tabs & modals ---------- */
function switchTab(name) {
  $$('.page').forEach(p => p.hidden = p.dataset.page !== name);
  $$('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === name));
}
function openSchedule() { $('#scheduleModal').hidden = false; renderSchedule(); }
function closeModal(sel) { $(sel).hidden = true; }

/* ---------- toast ---------- */
let toastT;
function toast(msg) {
  const el = $('#toast');
  el.textContent = msg; el.hidden = false;
  clearTimeout(toastT);
  toastT = setTimeout(() => el.hidden = true, 2200);
}

/* ---------- util ---------- */
function esc(s) { return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }

/* ---------- wire up ---------- */
function renderAll() {
  renderHeader(); renderTimeOfDay(); renderGoals(); renderTomorrow();
  renderLists(); renderWater(); renderOtherTabs();
}

function init() {
  load();
  renderAll();

  // tabs
  $$('.tab').forEach(t => t.onclick = () => switchTab(t.dataset.tab));

  // goals
  $('#addGoalForm').onsubmit = e => {
    e.preventDefault();
    const v = $('#addGoalInput').value.trim(); if (!v) return;
    S.goals.push({ id: uid(), text: v, done: false });
    $('#addGoalInput').value = ''; save(); renderGoals();
  };
  $('#showMoreBtn').onclick = () => { goalsExpanded = !goalsExpanded; renderGoals(); };
  $('#pushTomorrow').onclick = () => {
    const rem = S.goals.filter(g => !g.done);
    if (!rem.length) return toast('Nothing to push — all done 🔥');
    rem.forEach(g => S.tomorrow.push({ id: uid(), text: g.text }));
    S.goals = S.goals.filter(g => g.done);
    save(); renderGoals(); renderTomorrow();
    toast(`Pushed ${rem.length} to tomorrow`);
  };

  // tomorrow
  $('#addTmrwForm').onsubmit = e => {
    e.preventDefault();
    const v = $('#addTmrwInput').value.trim(); if (!v) return;
    S.tomorrow.push({ id: uid(), text: v });
    $('#addTmrwInput').value = ''; save(); renderTomorrow();
  };
  $('#polishTmrw').onclick = () => {
    if (!S.tomorrow.length) return toast('Add a few items first');
    // light "polish": title-case + dedupe
    const seen = new Set();
    S.tomorrow = S.tomorrow.filter(g => {
      const k = g.text.toLowerCase().trim();
      if (seen.has(k)) return false; seen.add(k);
      g.text = g.text.charAt(0).toUpperCase() + g.text.slice(1);
      return true;
    });
    save(); renderTomorrow(); toast('✦ Polished');
  };

  // struggles / wins
  $('#addStruggleForm').onsubmit = e => {
    e.preventDefault();
    const v = $('#addStruggleInput').value.trim(); if (!v) return;
    S.struggles.push(v); $('#addStruggleInput').value = ''; save(); renderLists();
  };
  $('#addWinForm').onsubmit = e => {
    e.preventDefault();
    const v = $('#addWinInput').value.trim(); if (!v) return;
    S.wins.push(v); $('#addWinInput').value = ''; save(); renderLists();
  };

  // water
  $('#waterPlus').onclick = $('#waterChip').onclick = () => { S.water++; save(); renderWater(); };
  $('#waterMinus').onclick = () => { S.water = Math.max(0, S.water - 1); save(); renderWater(); };

  // day type pill
  $('#dayPill').onclick = () => {
    const types = ['PULL DAY', 'PUSH DAY', 'LEG DAY', 'REST DAY', 'CARDIO DAY'];
    S.dayType = types[(types.indexOf(S.dayType) + 1) % types.length];
    save(); renderHeader(); toast(S.dayType);
  };

  // end day
  $('#endDayBtn').onclick = () => {
    const done = S.goals.filter(g => g.done).length;
    const all = S.goals.length && done === S.goals.length;
    if (all) { S.streak++; toast(`🔥 Day complete — ${S.streak}-day streak!`); }
    else toast(`Day ended — ${done}/${S.goals.length} goals done`);
    save(); renderGoals();
  };

  // schedule modal
  $('#scheduleBtn').onclick = openSchedule;
  $('#closeSchedule').onclick = () => closeModal('#scheduleModal');
  $('#scheduleModal').onclick = e => { if (e.target.id === 'scheduleModal') closeModal('#scheduleModal'); };
  $$('.loc-tab').forEach(b => b.onclick = () => {
    curLoc = b.dataset.loc;
    $$('.loc-tab').forEach(x => x.classList.toggle('active', x === b));
    renderSchedule();
  });

  // overseer
  $('#overseerSend').onclick = sendOverseer;
  $('#overseerInput').addEventListener('keydown', e => { if (e.key === 'Enter') sendOverseer(); });

  // search
  $('#searchBtn').onclick = () => { $('#searchModal').hidden = false; $('#searchOverlayInput').focus(); runSearch(''); };
  $('#globalSearch').onfocus = () => { $('#searchModal').hidden = false; $('#searchOverlayInput').value = $('#globalSearch').value; $('#searchOverlayInput').focus(); runSearch($('#globalSearch').value); };
  $('#closeSearch').onclick = () => closeModal('#searchModal');
  $('#searchOverlayInput').addEventListener('input', e => runSearch(e.target.value));

  // settings → optional Claude key for Overseer
  $('#settingsBtn').onclick = () => {
    const cur = localStorage.getItem(OverseerKey) || '';
    const k = prompt('Optional: paste an Anthropic API key to power Overseer with Claude.\nLeave blank & OK to keep local mode. Type "clear" to remove.', cur);
    if (k === null) return;
    if (k.trim() === 'clear' || k.trim() === '') { localStorage.removeItem(OverseerKey); toast('Overseer: local mode'); }
    else { localStorage.setItem(OverseerKey, k.trim()); toast('Overseer: Claude connected ✦'); }
  };

  // keep time fresh
  setInterval(renderTimeOfDay, 30000);
}

document.addEventListener('DOMContentLoaded', init);
