# LifeOS — Daily Score

A portable, **installable** personal dashboard that turns your day into a single
**Life Score** (0–100). Your life is split into weighted *pillars* — Sleep,
Nutrition, Fitness, Hydration, Productivity, Mind, Work/Brand, Finance, Learning
— and each thing you log rolls up into one number you can grow every day.

Phone-first, works on web and iPhone, no build step, no account, no backend.
Inspired by [@rowanthislebrooke](https://instagram.com/rowanthislebrooke)'s reel.

## Run it (localhost link you can bookmark)

```bash
cd dashboard
python3 serve.py            # or: python3 serve.py 5000
```

It prints two links:

- **This computer** — `http://localhost:8080` (bookmark on your laptop)
- **Phone (same Wi-Fi)** — `http://<your-computer-ip>:8080` (bookmark on your phone)

On iPhone, open the phone link in **Safari → Share → Add to Home Screen** to
install it as a full-screen app. On Chrome/Edge desktop, use the **Install
LifeOS** button in Settings. Once loaded it works **offline**.

## How the scoring works

| | |
|---|---|
| **Pillars** | Each pillar has a **weight** (how much it matters) and one or more **metrics** you log. |
| **Metric → progress** | Every metric maps to 0–100% of its target (e.g. 4h sleep / 8h target = 50%). |
| **Pillar score** | Average of its metrics, 0–100. |
| **Life Score** | Weight-weighted average of all pillars. |

Default allocation (editable in Settings, sums to 100%):

| Pillar | Weight | Logs |
|---|---|---|
| 🟦 Productivity | 15 | goals completed today |
| 😴 Sleep | 15 | hours + quality *(auto-sync later)* |
| 🍽️ Nutrition | 14 | meals + protein *(auto-sync later)* |
| 🏋️ Fitness | 14 | workout + active minutes |
| 📈 Work / Brand | 13 | deep-work hours + content shipped |
| 🧘 Mind | 10 | meditate + journal + gratitude |
| 💧 Hydration | 7 | water bottles |
| 📚 Learning | 7 | reading minutes |
| 💰 Finance | 5 | on budget + saved |

**Pillars marked "sync soon"** (Sleep, Nutrition) take manual inputs today but
are structured so an external source — a sleep tracker, a meal logger — can set
their score later without changing anything else. That's the foundation you
asked for.

## What's functional now

- **Today** — big Life Score ring, tap any pillar to log it (counters, toggles,
  sliders, numbers), goals checklist, and an **Overseer** assistant that reads
  your live scores ("recap", "what's my weak spot?").
- **Trends** — 14-day score chart, 7-day average, best day, streak, and per-pillar
  7-day averages.
- **Settings** — re-allocate weights, edit every target, set your name, connect
  Overseer to Claude, export/import/reset your data, install the app.
- **Day rollover** — at midnight today is snapshotted into history, unfinished
  goals carry forward, and your streak extends when you finish above 70.
- Everything persists in `localStorage`. Export to JSON anytime.

## Optional: power Overseer with Claude

Settings → paste an Anthropic API key. It's stored only in your browser and used
for direct browser calls to the Messages API (`claude-haiku-4-5`). Leave it
blank for local mode. *(A browser-stored key is visible to that browser — use a
scoped/disposable key, or add a server proxy for production.)*

## Files

| File | Purpose |
|------|---------|
| `index.html` | Layout / structure |
| `styles.css` | Dark theme, mobile-first |
| `pillars.js` | **Scoring engine** — pillar/metric config + math |
| `app.js` | State, rendering, logging, Overseer, PWA |
| `manifest.webmanifest`, `sw.js`, `icons/` | PWA install + offline |
| `serve.py` | Local server (computer + phone) |

## Adding / changing a pillar

Everything is data-driven. Edit the `PILLARS` array in `pillars.js`:

```js
{ id:'recovery', name:'Recovery', emoji:'🧊', color:'#38bdf8', weight:5,
  metrics:[ { key:'cold', label:'Cold plunge', type:'toggle' },
            { key:'stretch', label:'Stretch', type:'number', target:15, unit:'min' } ] }
```

Keep the weights summing to 100 (Settings shows the running total).
