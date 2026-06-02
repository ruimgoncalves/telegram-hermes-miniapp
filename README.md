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
├── index.html      # markup + Telegram Web App SDK include
├── style.css       # theme-aware (uses --tg-theme-* CSS vars)
├── app.js          # menu, view switching, form, localStorage
└── README.md
```

No build step. No dependencies. No backend.

## Security notes

- `localStorage` is **per-browser/per-device** and **not encrypted at rest**. Treat it as a clipboard, not a vault.
- Until the backend is wired, secrets never leave the device. That's by design for this stage.
- When the backend is added, the value should be POSTed over HTTPS and the local copy should be wiped.
