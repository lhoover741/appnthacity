# NThaCityRP

A GTA V roleplay server hub for Los Santos — civilian registration, Police CAD, DMV, business management, applications, and complaint handling, all backed by a Flask server with AI-powered dispatch via OpenRouter.

## Run & Operate

- **Start**: `python server.py` (port 5000)
- **Required env vars**:
  - `ADMIN_PASSWORD` — admin panel password (no default; must be set)
  - `FLASK_SECRET` — Flask session secret (sessions lost on restart if unset)
  - `OPENROUTER_API_KEY` — for all AI endpoints (dispatch, warrant, incident summary, suspect match, generate call)
  - `SMTP_EMAIL`, `SMTP_PASSWORD`, `SMTP_HOST`, `SMTP_PORT`, `NOTIFY_EMAIL` — email notifications (optional)
  - `DISCORD_WEBHOOK_URL` — Discord notifications for complaints/applications (optional)

## Stack

- Python 3.11, Flask
- Vanilla JS + HTML/CSS (no build step)
- JSON flat-file storage (complaints, applications, BOLOs, radio log, server status)
- OpenRouter (openai/gpt-4o-mini) for AI features

## Where things live

- `server.py` — all backend routes and logic
- `assets/js/main.js` — shared frontend data model, forms, and CAD rendering
- `assets/css/style.css` — global styles
- `*.html` — one file per page (index, police, civilian, dmv, businesses, complaints, applications, rules, join, donations, admin)
- `radio_log.json` — persisted radio log (pre-seeded)

## Architecture decisions

- Flat JSON files for persistence — simple, no DB dependency; not suitable for high write volume
- All client data (civilians, vehicles, warrants, arrests, etc.) stored in `localStorage` — police CAD data is browser-local only
- Flask serves static HTML files and exposes a REST API at `/api/*`
- Admin session uses Flask server-side session (cookie-based)
- AI prompts use `system` + `user` message split for better context separation

## Product

- Civilian registration and lookup
- Police CAD: 911 call queue, warrants, arrests, traffic stops, evidence, officer board
- DMV: plate/license lookup and registration
- Business & faction directory
- Staff applications and complaint submission with email + Discord notifications
- Admin panel for reviewing complaints and applications
- AI-powered: dispatch triage, warrant generation, incident summaries, suspect matching, call generation

## Gotchas

- Set `ADMIN_PASSWORD` and `FLASK_SECRET` as secrets before deploying — admin login fails silently with an empty password if unset
- CAD data (civilians, vehicles, warrants) lives in the browser's `localStorage`, not the server — data is per-device
- OpenRouter URL must be `https://openrouter.ai/api/v1/chat/completions` (not `api.openrouter.io`)
