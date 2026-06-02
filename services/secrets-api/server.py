"""Hermes secrets API.

A small FastAPI service that exposes a CRUD endpoint over a single user's
Telegram-vetted secret store, backed by the standard ``~/.hermes/.env`` file
that Hermes already loads at process startup.

Auth: every request must carry an ``X-Telegram-Init-Data`` header. The init
data is validated against the bot token from ``~/.hermes/.env`` per the
Telegram Mini App spec (HMAC-SHA256 over ``bot_token`` from
``WebhookSecret`` derivation). The decoded ``user.id`` must appear in
``TELEGRAM_ALLOWED_USERS``.

Endpoints:
  POST   /v1/secrets           — write {name, value} to .env
  GET    /v1/secrets           — list secret NAMES (never values)
  DELETE /v1/secrets/{name}    — remove by name
  GET    /healthz              — liveness probe (no auth)

Security: secrets are stored in plaintext in ``~/.hermes/.env``, same as
every other Hermes key today. The threat model is "stop stray requests
from random web pages" — it is NOT a hardened vault.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, List, Optional

import dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Path as PathParam, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

LOG = logging.getLogger("secrets-api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HERMES_HOME = Path(os.environ.get("HERMES_HOME", "/root/.hermes")).expanduser()
ENV_FILE = Path(os.environ.get("HERMES_ENV_FILE", str(HERMES_HOME / ".env"))).expanduser()
ENV_FILE_BACKUP = ENV_FILE.with_suffix(ENV_FILE.suffix + ".bak.secrets-api")
LISTEN_HOST = os.environ.get("SECRETS_API_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("SECRETS_API_PORT", "9876"))

# Telegram init data validation window (seconds). 24h matches Telegram's
# own client-side limit per their docs.
INIT_DATA_MAX_AGE_SECONDS = 24 * 60 * 60

# Valid name pattern: same as the Mini App frontend so what works in the UI
# works at the API too.
NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,128}$")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class SecretIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    value: str = Field(..., min_length=1, max_length=8192)

    @field_validator("name")
    @classmethod
    def _name_shape(cls, v: str) -> str:
        if not NAME_RE.match(v):
            raise ValueError(
                "name must match [A-Za-z0-9_.-]{1,128} (letters, digits, _, ., -)"
            )
        return v

    @field_validator("value")
    @classmethod
    def _value_no_newlines(cls, v: str) -> str:
        # .env files use newlines as record separators; reject them.
        if "\n" in v or "\r" in v:
            raise ValueError("value must not contain newlines")
        return v


class SecretOut(BaseModel):
    name: str


class SecretList(BaseModel):
    secrets: List[SecretOut]


class HealthOut(BaseModel):
    status: str
    env_file: str
    secret_count: int


# ---------------------------------------------------------------------------
# .env file handling
# ---------------------------------------------------------------------------


def read_env_pairs() -> dict[str, str]:
    """Read the .env file as a flat dict. Comments and blanks are skipped."""
    if not ENV_FILE.exists():
        return {}
    raw = dotenv.dotenv_values(ENV_FILE)
    return {k: ("" if v is None else v) for k, v in raw.items()}


def atomic_write_env(pairs: dict[str, str]) -> None:
    """Write the .env file atomically.

    Strategy: write to a temp file, fsync, then rename. We also keep a
    single ``.bak`` of the previous state so a botched write is recoverable.
    """
    # Serialize in stable order: existing keys (in their original order)
    # first, then any new keys alphabetically. This keeps diffs small and
    # reviewable.
    body_lines: list[str] = []
    if ENV_FILE.exists():
        with ENV_FILE.open("r", encoding="utf-8") as fh:
            for line in fh:
                # Preserve blank/comment lines exactly
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    body_lines.append(line if line.endswith("\n") else line + "\n")
                else:
                    # Recompose from our pairs dict
                    m = re.match(r"^([A-Za-z_][A-Za-z0-9_.\-]*)\s*=", line)
                    if m:
                        k = m.group(1)
                        if k in pairs:
                            body_lines.append(f"{k}={_escape_env_value(pairs[k])}\n")
                            del pairs[k]
    # Append remaining new keys in sorted order
    for k in sorted(pairs.keys()):
        body_lines.append(f"{k}={_escape_env_value(pairs[k])}\n")

    tmp_path = ENV_FILE.with_suffix(ENV_FILE.suffix + ".tmp")
    try:
        # Back up current file first (best effort)
        if ENV_FILE.exists():
            ENV_FILE_BACKUP.write_text(ENV_FILE.read_text(encoding="utf-8"), encoding="utf-8")
        with tmp_path.open("w", encoding="utf-8") as fh:
            fh.write("".join(body_lines))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, ENV_FILE)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def _escape_env_value(v: str) -> str:
    # Quote with double-quotes; escape backslashes and embedded double-quotes.
    # .env parsers (including python-dotenv) handle this format.
    escaped = v.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


@contextmanager
def _locked_env() -> Iterator[None]:
    """File lock via O_EXCL on a sentinel — good enough for a single-writer
    service. Not bulletproof, but the actual state-of-the-world lives in
    .env and that's what the .env loader reads on Hermes startup."""
    lock_path = ENV_FILE.with_suffix(ENV_FILE.suffix + ".lock")
    fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(fd, b"locked")
    finally:
        os.close(fd)
    try:
        yield
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------------------
# Telegram init data validation
# ---------------------------------------------------------------------------


def _load_bot_token() -> Optional[str]:
    if not ENV_FILE.exists():
        return None
    vals = dotenv.dotenv_values(ENV_FILE)
    tok = vals.get("TELEGRAM_BOT_TOKEN")
    if tok is None:
        return None
    tok = tok.strip().strip('"').strip("'")
    return tok or None


def _load_allowed_users() -> set[int]:
    if not ENV_FILE.exists():
        return set()
    vals = dotenv.dotenv_values(ENV_FILE)
    raw = vals.get("TELEGRAM_ALLOWED_USERS", "")
    out: set[int] = set()
    for chunk in raw.replace("\n", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            out.add(int(chunk))
        except ValueError:
            pass
    return out


def _validate_init_data(init_data: str, bot_token: str) -> Optional[dict]:
    """Validate ``X-Telegram-Init-Data`` per
    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app

    Returns the parsed payload dict on success, None on failure.
    """
    from urllib.parse import unquote, parse_qsl

    pairs_in = parse_qsl(init_data, keep_blank_values=True)
    params: dict[str, str] = {k: v for k, v in pairs_in}
    hash_received = params.pop("hash", None)
    if not hash_received:
        return None
    # data-check-string: pairs sorted by key, joined with '\n', each
    # value URL-decoded.
    sorted_pairs = []
    for k in sorted(params.keys()):
        sorted_pairs.append(f"{k}={unquote(params[k])}")
    data_check_string = "\n".join(sorted_pairs)

    # Secret key = HMAC_SHA256(bot_token, "WebAppData")
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    computed = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, hash_received):
        return None

    # Decode the user object (always URL-encoded JSON)
    user_raw = unquote(params.get("user", ""))
    try:
        user_obj = json.loads(user_raw) if user_raw else None
    except json.JSONDecodeError:
        user_obj = None
    if not user_obj or "id" not in user_obj:
        return None

    # Check freshness
    auth_date_raw = params.get("auth_date", "")
    try:
        auth_date = int(auth_date_raw)
    except ValueError:
        return None
    if abs(int(time.time()) - auth_date) > INIT_DATA_MAX_AGE_SECONDS:
        return None

    return {"user": user_obj, "auth_date": auth_date}


def require_telegram_user(
    x_telegram_init_data: Optional[str] = Header(default=None, alias="X-Telegram-Init-Data"),
) -> int:
    """FastAPI dependency. Returns the validated Telegram user id, or raises 401/403."""
    if not x_telegram_init_data:
        raise HTTPException(status_code=401, detail="X-Telegram-Init-Data header required")
    bot_token = _load_bot_token()
    if not bot_token:
        LOG.error("TELEGRAM_BOT_TOKEN not found in %s", ENV_FILE)
        raise HTTPException(status_code=503, detail="server is missing TELEGRAM_BOT_TOKEN")
    payload = _validate_init_data(x_telegram_init_data, bot_token)
    if not payload:
        raise HTTPException(status_code=401, detail="invalid init data")
    user_id = int(payload["user"]["id"])
    if user_id not in _load_allowed_users():
        LOG.warning("rejected user id %s (not in TELEGRAM_ALLOWED_USERS)", user_id)
        raise HTTPException(status_code=403, detail="user not permitted")
    return user_id


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Hermes Secrets API", version="0.1.0", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://ruimgoncalves.github.io"],  # only the Mini App origin
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["X-Telegram-Init-Data", "Content-Type"],
    max_age=3600,
)


@app.get("/healthz", response_model=HealthOut)
def healthz() -> HealthOut:
    pairs = read_env_pairs()
    # We count only entries that look like real secrets (skip framework vars
    # if you want a tighter count, but plain count is fine for liveness)
    return HealthOut(
        status="ok",
        env_file=str(ENV_FILE),
        secret_count=len(pairs),
    )


@app.get("/v1/secrets", response_model=SecretList, dependencies=[Depends(require_telegram_user)])
def list_secrets() -> SecretList:
    pairs = read_env_pairs()
    return SecretList(secrets=[SecretOut(name=k) for k in sorted(pairs.keys())])


class SecretValueOut(BaseModel):
    name: str
    value: str


@app.get(
    "/v1/secrets/{name}",
    response_model=SecretValueOut,
    dependencies=[Depends(require_telegram_user)],
)
def get_secret(name: str = PathParam(..., pattern=NAME_RE.pattern)) -> SecretValueOut:
    pairs = read_env_pairs()
    if name not in pairs:
        raise HTTPException(status_code=404, detail=f"no such secret: {name}")
    return SecretValueOut(name=name, value=pairs[name])


@app.post(
    "/v1/secrets",
    response_model=SecretOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_telegram_user)],
)
def create_or_update_secret(body: SecretIn) -> SecretOut:
    with _locked_env():
        pairs = read_env_pairs()
        pairs[body.name] = body.value
        atomic_write_env(pairs)
    LOG.info("wrote secret name=%s (user_id validated by auth)", body.name)
    return SecretOut(name=body.name)


@app.delete(
    "/v1/secrets/{name}",
    response_model=SecretList,
    dependencies=[Depends(require_telegram_user)],
)
def delete_secret(name: str = PathParam(..., pattern=NAME_RE.pattern)) -> SecretList:
    with _locked_env():
        pairs = read_env_pairs()
        if name not in pairs:
            raise HTTPException(status_code=404, detail=f"no such secret: {name}")
        del pairs[name]
        atomic_write_env(pairs)
    LOG.info("deleted secret name=%s", name)
    remaining = [SecretOut(name=k) for k in sorted(pairs.keys())]
    return SecretList(secrets=remaining)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    LOG.info("Hermes secrets API listening on http://%s:%s", LISTEN_HOST, LISTEN_PORT)
    LOG.info("env file: %s", ENV_FILE)
    uvicorn.run(app, host=LISTEN_HOST, port=LISTEN_PORT, log_level="info")
