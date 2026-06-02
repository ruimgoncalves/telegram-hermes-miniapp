# Hermes Secrets API

A small FastAPI service that gives the [Telegram Mini App](../) a
secure way to write secrets into `~/.hermes/.env` (the same file
Hermes already loads at process startup, so secrets become immediately
visible to the agent without a restart-needed reload).

## Endpoints

All endpoints (except `/healthz`) require an `X-Telegram-Init-Data`
header. The init data is validated per the
[Telegram Mini App spec](https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app)
(HMAC-SHA256 with the bot token from `~/.hermes/.env`). The decoded
`user.id` must appear in `TELEGRAM_ALLOWED_USERS`.

| Method | Path                       | Body / Params       | Returns         |
|--------|----------------------------|---------------------|-----------------|
| GET    | `/healthz`                 | —                   | `{status, env_file, secret_count}` (no auth) |
| GET    | `/v1/secrets`              | —                   | `{secrets: [{name}]}` — names only, no values |
| POST   | `/v1/secrets`              | `{name, value}`     | `{name}` (201)  |
| DELETE | `/v1/secrets/{name}`       | —                   | `{secrets: [{name}]}` (200) |
| OPTIONS| `/v1/secrets`              | CORS preflight      | 204 with headers |

CORS: only `https://ruimgoncalves.github.io` is allowed.

## Local development

```bash
cd services/secrets-api
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pytest test_server.py -v
HERMES_ENV_FILE=/tmp/test.env .venv/bin/python server.py
```

## Deployment (this box)

```bash
# 1. Install Caddy and Python deps (already done on hermes.localdomain)
apt-get install -y caddy
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 2. Generate self-signed cert (1 year, covers hermes.localdomain + IPs)
mkdir -p /var/lib/caddy/.local/share/caddy
openssl req -x509 -newkey rsa:2048 \
  -keyout /var/lib/caddy/.local/share/caddy/hermes.localdomain.key \
  -out /var/lib/caddy/.local/share/caddy/hermes.localdomain.crt \
  -days 365 -nodes \
  -subj '/CN=hermes.localdomain' \
  -addext 'subjectAltName=DNS:hermes.localdomain,DNS:localhost,IP:192.168.200.220,IP:127.0.0.1'
chown caddy:caddy /var/lib/caddy/.local/share/caddy/hermes.localdomain.{crt,key}
chmod 644 /var/lib/caddy/.local/share/caddy/hermes.localdomain.crt
chmod 600 /var/lib/caddy/.local/share/caddy/hermes.localdomain.key

# 3. Install systemd unit + Caddyfile
cp hermes-secrets-api.service /etc/systemd/system/
cp Caddyfile /etc/caddy/Caddyfile
systemctl daemon-reload
systemctl enable --now hermes-secrets-api.service
systemctl enable --now caddy.service
```

The public URL becomes **https://hermes.localdomain/secrets-api/**.

## Trusting the self-signed cert on your phone

iOS Safari and Android Chrome will reject HTTPS to hermes.localdomain
until you install the cert in the system trust store:

- **Android:** Settings → Security → Encryption & credentials → Install
  a certificate → CA certificate → pick `hermes.localdomain.crt`
- **iOS:** AirDrop or download the `.crt`, then Settings → General →
  VPN & Device Management → tap the profile → Install, then Settings →
  General → About → Certificate Trust Settings → enable the cert

The cert file is checked in at `services/secrets-api/hermes.localdomain.crt`
for convenience (re-generate yearly).

## Security notes

- **Plaintext at rest** in `~/.hermes/.env`, same as every other Hermes
  key. The threat model is "stop stray requests from random web pages",
  NOT a hardened vault.
- **Single-user** — the service trusts the first user id in
  `TELEGRAM_ALLOWED_USERS` that presents valid init data.
- **No rate limiting** — fine for a single-user LAN deployment; would
  need to be added before internet exposure.
- **No secret redaction on read** — `GET /v1/secrets` returns names
  only, not values. The Mini App "View Secrets" tab will need to either
  call a separate `GET /v1/secrets/{name}` (which doesn't exist yet) or
  get a one-time reveal token.
- **.env is rewritten on every write** — atomic via temp file + rename,
  with a single `.bak` snapshot before each write. The structure of
  unrelated keys is preserved; new keys are appended alphabetically.

## What this does NOT do

- Doesn't touch `hermes-gateway.service` or any existing Hermes
  process.
- Doesn't read or change `~/.hermes/config.yaml`.
- Doesn't expose `~/.hermes/agentgateway/secrets/` (that's an
  AgentGateway config dir, separate from this).
- Doesn't migrate secrets to/from `hermes secrets bitwarden` (Bitwarden
  Secrets Manager is a different subsystem for read-at-startup keys).
