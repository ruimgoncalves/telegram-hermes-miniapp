# Hermes Secrets — Telegram Mini App

A static Telegram Mini App for submitting secrets to the Hermes vault, bypassing Telegram and any LLM in the path.

> **Status:** UI-only. The submit button persists secrets to the device's `localStorage`. Wiring the form to a real Hermes vault endpoint is a follow-up.

## What it does

- ☰ Menu button (top-left) opens a slide-out panel with *Add Secret*, *View Secrets* (placeholder), and *About*.
- Form to add a secret: **name** + **value** (password-masked, with eye toggle).
- **Live byte counter** under the value field — display only, never stored or sent.
- **Inline error messages** below the form: name required, value required, invalid name, *secret already exists*, storage failure, etc.
- Secrets stored in `localStorage` under the key `hermes-miniapp-secrets` as `{ name, value }` — no size field, no metadata.

## Running

### As a plain web page
Open `index.html` directly, or serve the folder:
```bash
python3 -m http.server 8000
# then visit http://localhost:8000
```

### As a Telegram Mini App
1. Host this folder somewhere reachable over HTTPS (e.g. **GitHub Pages**).
2. In BotFather, register the menu button URL pointing at the hosted `index.html`.
3. Open the Mini App from your bot. `window.Telegram.WebApp` will populate, and the app will expand to full height.

## Project layout

```
telegram-hermes-miniapp/
├── index.html                          # markup + Telegram Web App SDK include
├── style.css                           # theme-aware (uses --tg-theme-* CSS vars)
├── app.js                              # menu, view switching, form, localStorage
├── services/
│   └── secrets-api/                    # FastAPI backend (separate branch)
│       ├── server.py
│       ├── test_server.py              # 21 tests
│       ├── hermes-secrets-api.service  # systemd unit
│       ├── Caddyfile                   # HTTPS reverse proxy config
│       ├── hermes.localdomain.crt      # self-signed cert (for phone)
│       └── README.md
└── README.md
```

No build step. No frontend dependencies. The backend uses FastAPI + Caddy.

## Status

- **UI is live** at https://ruimgoncalves.github.io/telegram-hermes-miniapp/ (GitHub Pages).
- The submit button still persists to `localStorage` — the backend is wired in a follow-up branch.
- The **backend ships on branch `feature/secrets-api-backend`**: a FastAPI service exposed at `https://hermes.localdomain/secrets-api/` with Telegram initData auth, reverse-proxied via Caddy with a self-signed cert. See `services/secrets-api/README.md` for the deployment guide.
