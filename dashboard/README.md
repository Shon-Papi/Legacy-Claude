# Rowan's Dashboard

A personal **life-OS dashboard** — a single screen that tracks your day, goals,
routines, brand, health, and gym, with an AI assistant ("Overseer") that reads
your whole dashboard and answers questions about it.

Built after [@rowanthislebrooke](https://instagram.com/rowanthislebrooke)'s reel
showing the dashboard he made with Claude.

![dashboard](https://img.shields.io/badge/stack-vanilla%20JS-f0a868) ![build](https://img.shields.io/badge/build-none-34d399)

## Features

- **Time of day** — a progress bar of your awake hours ("11h 17m of awake time left").
- **Overseer** — an assistant that knows your live dashboard. Ask *"what's left?"*,
  *"how's my streak?"*, *"give me a recap"*. Works fully offline; optionally
  upgradeable to Claude (see below).
- **Goalmaxxing** — today's checklist with add / check / delete, show-more,
  a day-streak, and **Push remaining → tomorrow**.
- **Plan tomorrow** — write tonight; a one-tap **Polish** cleans the list up.
- **Current struggles** & **Wins & positives** — quick capture for what's on your mind.
- **Water** tracker with bottle dots.
- **Schedule** modal — Morning + Night routines, switchable between locations
  (Les Roches / Bern), with checkable steps.
- **Finances · Brand · Health · Gym** tabs — net worth, YouTube subs + sparkline,
  macros, today's workout.
- **Universal search** across goals, schedule, struggles, and wins.
- **Day rollover** — a new day carries unfinished goals (or tomorrow's plan)
  forward and extends the streak when you finish everything.
- Everything persists in `localStorage`. No account, no backend.

## Run it

It's static — just open the file, or serve the folder:

```bash
cd dashboard
python3 -m http.server 8080
# open http://localhost:8080
```

Best viewed in a mobile/portrait viewport (it's designed phone-first).

## Optional: power Overseer with Claude

By default Overseer answers locally from your dashboard data. To have it answer
with **Claude**, tap the ⚙ icon and paste an Anthropic API key — it's stored
only in your browser's `localStorage` and used for direct browser calls to the
Messages API (`claude-haiku-4-5`). Leave it blank to stay in local mode; type
`clear` to remove the key.

> Note: putting an API key in the browser exposes it to that browser. Use a
> scoped/disposable key, or run a small proxy in production.

## Files

| File | Purpose |
|------|---------|
| `index.html` | Layout & structure |
| `styles.css` | Dark theme (amber + blue accents) |
| `app.js` | State, persistence, Overseer, all interactions |
