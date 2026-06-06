/* ============================================================
   pillars.js — the Life Score allocation + scoring engine.

   Your life is split into weighted PILLARS. Each pillar holds
   one or more METRICS you log during the day. Every metric maps
   to 0..1 progress toward its target; a pillar's score is the
   average of its metrics (0..100). The daily Life Score is the
   weight-weighted average of all pillar scores.

   Weights + targets are editable in Settings (state.config), so
   you can re-allocate what matters. Pillars marked syncable:true
   are designed to later pull an external score (sleep tracker,
   meal logger, etc.) instead of manual inputs.
   ============================================================ */
'use strict';

/* metric.type:
   counter  → tap +/- (target = goal count)
   number   → numeric entry (target = goal)
   slider   → 1..max scale (target usually = max)
   toggle   → done / not done (target implied 1)
   derived  → computed elsewhere (e.g. from goals list)
*/
const PILLARS = [
  {
    id: 'sleep', name: 'Sleep', emoji: '😴', color: '#8b8cff', weight: 15, syncable: true,
    blurb: 'Sleep score will auto-sync from a tracker later.',
    metrics: [
      { key: 'hours', label: 'Hours slept', type: 'number', target: 8, unit: 'h', step: 0.5, max: 12 },
      { key: 'quality', label: 'Quality', type: 'slider', target: 5, max: 5 },
    ],
  },
  {
    id: 'nutrition', name: 'Nutrition', emoji: '🍽️', color: '#34d399', weight: 14, syncable: true,
    blurb: 'Meal score will auto-sync from a food log later.',
    metrics: [
      { key: 'meals', label: 'Meals logged', type: 'counter', target: 3, unit: 'meals' },
      { key: 'protein', label: 'Protein', type: 'number', target: 160, unit: 'g', step: 10, max: 400 },
    ],
  },
  {
    id: 'fitness', name: 'Fitness', emoji: '🏋️', color: '#f0a868', weight: 14,
    metrics: [
      { key: 'workout', label: 'Workout done', type: 'toggle' },
      { key: 'active', label: 'Active minutes', type: 'number', target: 45, unit: 'min', step: 5, max: 240 },
    ],
  },
  {
    id: 'hydration', name: 'Hydration', emoji: '💧', color: '#5b8cff', weight: 7,
    metrics: [
      { key: 'water', label: 'Water', type: 'counter', target: 6, unit: 'bottles' },
    ],
  },
  {
    id: 'productivity', name: 'Productivity', emoji: '✅', color: '#fbbf24', weight: 15,
    blurb: 'Scored from your goals completed today.',
    metrics: [
      { key: 'goals', label: 'Goals completed', type: 'derived' },
    ],
  },
  {
    id: 'mind', name: 'Mind', emoji: '🧘', color: '#c084fc', weight: 10,
    metrics: [
      { key: 'meditate', label: 'Meditate', type: 'toggle' },
      { key: 'journal', label: 'Journal', type: 'toggle' },
      { key: 'gratitude', label: 'Gratitude notes', type: 'counter', target: 3, unit: 'notes' },
    ],
  },
  {
    id: 'work', name: 'Work / Brand', emoji: '📈', color: '#fb7185', weight: 13,
    metrics: [
      { key: 'deepwork', label: 'Deep work', type: 'number', target: 4, unit: 'h', step: 0.5, max: 12 },
      { key: 'content', label: 'Content shipped', type: 'counter', target: 1, unit: 'pieces' },
    ],
  },
  {
    id: 'finance', name: 'Finance', emoji: '💰', color: '#2dd4bf', weight: 5,
    metrics: [
      { key: 'onbudget', label: 'Stayed on budget', type: 'toggle' },
      { key: 'saved', label: 'Moved money to savings', type: 'toggle' },
    ],
  },
  {
    id: 'learning', name: 'Learning', emoji: '📚', color: '#38bdf8', weight: 7,
    metrics: [
      { key: 'reading', label: 'Reading', type: 'number', target: 30, unit: 'min', step: 5, max: 240 },
    ],
  },
];

const PILLAR_BY_ID = Object.fromEntries(PILLARS.map(p => [p.id, p]));

/* ---- config-aware getters (Settings can override) ---- */
function getWeight(state, pillar) {
  const o = state.config?.weights?.[pillar.id];
  return (o === undefined || o === null || o === '') ? pillar.weight : Number(o);
}
function getTarget(state, pillarId, metric) {
  const o = state.config?.targets?.[pillarId]?.[metric.key];
  return (o === undefined || o === null || o === '') ? metric.target : Number(o);
}

/* ---- scoring ---- */
function metricProgress(state, pillar, metric) {
  const v = state.metrics?.[pillar.id]?.[metric.key];
  if (metric.type === 'toggle') return v ? 1 : 0;
  if (metric.type === 'derived') return 0; // handled by caller (productivity)
  const target = getTarget(state, pillar.id, metric) || 1;
  const val = Number(v) || 0;
  return clamp01(val / target);
}

function pillarScore(state, pillar, ctx = {}) {
  // productivity is derived from goals
  if (pillar.id === 'productivity') {
    const total = ctx.goalTotal ?? 0;
    const done = ctx.goalDone ?? 0;
    if (!total) return { score: 0, progresses: [{ key: 'goals', p: 0 }], empty: true };
    const p = clamp01(done / total);
    return { score: Math.round(p * 100), progresses: [{ key: 'goals', p }] };
  }
  const progresses = pillar.metrics.map(m => ({ key: m.key, p: metricProgress(state, pillar, m) }));
  const avg = progresses.reduce((s, x) => s + x.p, 0) / (progresses.length || 1);
  return { score: Math.round(avg * 100), progresses };
}

function lifeScore(state, ctx = {}) {
  let wsum = 0, acc = 0;
  const breakdown = {};
  for (const p of PILLARS) {
    const w = getWeight(state, p);
    const s = pillarScore(state, p, ctx).score;
    breakdown[p.id] = s;
    wsum += w; acc += w * s;
  }
  return { score: wsum ? Math.round(acc / wsum) : 0, breakdown, weightSum: wsum };
}

function clamp01(x) { return Math.max(0, Math.min(1, x)); }

/* expose */
window.PILLARS = PILLARS;
window.PILLAR_BY_ID = PILLAR_BY_ID;
window.getWeight = getWeight;
window.getTarget = getTarget;
window.pillarScore = pillarScore;
window.lifeScore = lifeScore;
