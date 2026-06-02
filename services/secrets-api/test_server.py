"""Tests for the Hermes secrets API.

Run with:
    cd services/secrets-api
    pytest test_server.py -v

We don't touch the real ``~/.hermes/.env`` — every test points the
service at a temp dir via ``HERMES_ENV_FILE`` and writes a fake
``TELEGRAM_BOT_TOKEN`` / ``TELEGRAM_ALLOWED_USERS`` into it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from pathlib import Path
from typing import Iterator
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_BOT_TOKEN = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
ALLOWED_USER = 6677385662
OTHER_ALLOWED_USER = 999


def build_init_data(user_id: int, bot_token: str = FAKE_BOT_TOKEN, age_seconds: int = 0) -> str:
    """Build a valid X-Telegram-Init-Data string for the given user."""
    user_payload = {"id": user_id, "first_name": "Test", "username": "tester"}
    auth_date = int(time.time()) - age_seconds
    params = {
        "user": json.dumps(user_payload, separators=(",", ":")),
        "auth_date": str(auth_date),
        "query_id": "AAH12345",
    }
    # data-check-string: sorted by key, joined with '\n', raw values
    sorted_pairs = []
    for k in sorted(params.keys()):
        sorted_pairs.append(f"{k}={params[k]}")
    data_check_string = "\n".join(sorted_pairs)
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    computed = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    params["hash"] = computed
    # Serialize back into the form Telegram ships: each value URL-encoded
    return "&".join(f"{k}={quote(params[k], safe='')}" for k in sorted(params.keys()))


@pytest.fixture
def env_file(tmp_path, monkeypatch) -> Iterator[Path]:
    """A clean .env file in a temp dir, with bot token + allowed user."""
    p = tmp_path / ".env"
    p.write_text(
        f'TELEGRAM_BOT_TOKEN="{FAKE_BOT_TOKEN}"\n'
        f'TELEGRAM_ALLOWED_USERS="{ALLOWED_USER},{OTHER_ALLOWED_USER}"\n'
        f'EXISTING_KEY="old_value"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_ENV_FILE", str(p))
    # Force a fresh import so ENV_FILE is re-read
    import importlib
    import server  # noqa: F401
    importlib.reload(server)
    yield p


@pytest.fixture
def client(env_file) -> Iterator[TestClient]:
    from server import app
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# /healthz
# ---------------------------------------------------------------------------


def test_healthz_is_open(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["env_file"].endswith(".env")
    assert body["secret_count"] >= 3  # BOT_TOKEN, ALLOWED_USERS, EXISTING_KEY


# ---------------------------------------------------------------------------
# Auth gating
# ---------------------------------------------------------------------------


def test_list_without_init_data_returns_401(client):
    r = client.get("/v1/secrets")
    assert r.status_code == 401
    assert "X-Telegram-Init-Data" in r.json()["detail"]


def test_post_without_init_data_returns_401(client):
    r = client.post("/v1/secrets", json={"name": "FOO", "value": "bar"})
    assert r.status_code == 401


def test_delete_without_init_data_returns_401(client):
    r = client.delete("/v1/secrets/FOO")
    assert r.status_code == 401


def test_init_data_with_wrong_signature_returns_401(client):
    bad = build_init_data(ALLOWED_USER, bot_token="wrong:token")
    r = client.get("/v1/secrets", headers={"X-Telegram-Init-Data": bad})
    assert r.status_code == 401


def test_init_data_expired_returns_401(client):
    old = build_init_data(ALLOWED_USER, age_seconds=48 * 3600)  # 2 days old
    r = client.get("/v1/secrets", headers={"X-Telegram-Init-Data": old})
    assert r.status_code == 401


def test_init_data_for_unauthorized_user_returns_403(client):
    other = build_init_data(12345678)  # not in allowed list
    r = client.get("/v1/secrets", headers={"X-Telegram-Init-Data": other})
    assert r.status_code == 403


def test_init_data_for_allowed_user_succeeds(client):
    allowed = build_init_data(ALLOWED_USER)
    r = client.get("/v1/secrets", headers={"X-Telegram-Init-Data": allowed})
    assert r.status_code == 200
    names = [s["name"] for s in r.json()["secrets"]]
    # The .env is just a flat dict — we list everything, including the bot token
    assert "EXISTING_KEY" in names
    assert "TELEGRAM_BOT_TOKEN" in names


# ---------------------------------------------------------------------------
# POST /v1/secrets
# ---------------------------------------------------------------------------


def test_post_creates_new_secret(client, env_file):
    init = build_init_data(ALLOWED_USER)
    r = client.post(
        "/v1/secrets",
        json={"name": "GITHUB_TOKEN", "value": "ghp_test123"},
        headers={"X-Telegram-Init-Data": init},
    )
    assert r.status_code == 201
    assert r.json() == {"name": "GITHUB_TOKEN"}

    content = env_file.read_text()
    assert "GITHUB_TOKEN=" in content
    # And the original key is still there
    assert 'EXISTING_KEY="old_value"' in content


def test_post_updates_existing_secret(client, env_file):
    init = build_init_data(ALLOWED_USER)
    client.post(
        "/v1/secrets",
        json={"name": "API_KEY", "value": "v1"},
        headers={"X-Telegram-Init-Data": init},
    )
    r = client.post(
        "/v1/secrets",
        json={"name": "API_KEY", "value": "v2"},
        headers={"X-Telegram-Init-Data": init},
    )
    assert r.status_code == 201

    content = env_file.read_text()
    assert "API_KEY=" in content
    # No duplicates (only one definition line)
    assert content.count("API_KEY=") == 1
    # And it's the new value, not the old one
    from server import read_env_pairs
    assert read_env_pairs()["API_KEY"] == "v2"


def test_post_rejects_invalid_name(client):
    init = build_init_data(ALLOWED_USER)
    r = client.post(
        "/v1/secrets",
        json={"name": "BAD NAME WITH SPACES", "value": "x"},
        headers={"X-Telegram-Init-Data": init},
    )
    assert r.status_code == 422
    assert "name" in str(r.json()).lower()


def test_post_rejects_value_with_newlines(client):
    init = build_init_data(ALLOWED_USER)
    r = client.post(
        "/v1/secrets",
        json={"name": "OK_NAME", "value": "line1\nline2"},
        headers={"X-Telegram-Init-Data": init},
    )
    assert r.status_code == 422
    assert "newlines" in str(r.json()).lower()


def test_post_handles_value_with_quotes_and_backslashes(client, env_file):
    init = build_init_data(ALLOWED_USER)
    weird_value = 'has "quotes" and \\backslashes'
    r = client.post(
        "/v1/secrets",
        json={"name": "WEIRD", "value": weird_value},
        headers={"X-Telegram-Init-Data": init},
    )
    assert r.status_code == 201

    # Reload and verify the parser round-trips the value correctly
    from server import read_env_pairs
    pairs = read_env_pairs()
    assert pairs["WEIRD"] == weird_value


def test_post_rejects_oversized_value(client):
    init = build_init_data(ALLOWED_USER)
    r = client.post(
        "/v1/secrets",
        json={"name": "BIG", "value": "x" * 10_000},
        headers={"X-Telegram-Init-Data": init},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# GET /v1/secrets
# ---------------------------------------------------------------------------


def test_list_returns_sorted_names(client):
    init = build_init_data(ALLOWED_USER)
    for n in ["ZEBRA", "ALPHA", "MONKEY"]:
        client.post(
            "/v1/secrets",
            json={"name": n, "value": "v"},
            headers={"X-Telegram-Init-Data": init},
        )
    r = client.get("/v1/secrets", headers={"X-Telegram-Init-Data": init})
    assert r.status_code == 200
    names = [s["name"] for s in r.json()["secrets"]]
    assert "ZEBRA" in names and "ALPHA" in names and "MONKEY" in names
    assert names == sorted(names)


def test_list_does_not_leak_values(client):
    init = build_init_data(ALLOWED_USER)
    client.post(
        "/v1/secrets",
        json={"name": "SUPER_SECRET", "value": "hunter2"},
        headers={"X-Telegram-Init-Data": init},
    )
    r = client.get("/v1/secrets", headers={"X-Telegram-Init-Data": init})
    body = r.text
    assert "hunter2" not in body
    assert "SUPER_SECRET" in body  # name is fine


# ---------------------------------------------------------------------------
# DELETE /v1/secrets
# ---------------------------------------------------------------------------


def test_delete_removes_secret(client, env_file):
    init = build_init_data(ALLOWED_USER)
    client.post(
        "/v1/secrets",
        json={"name": "TO_DELETE", "value": "x"},
        headers={"X-Telegram-Init-Data": init},
    )
    r = client.delete(
        "/v1/secrets/TO_DELETE",
        headers={"X-Telegram-Init-Data": init},
    )
    assert r.status_code == 200
    content = env_file.read_text()
    assert "TO_DELETE" not in content


def test_delete_missing_returns_404(client):
    init = build_init_data(ALLOWED_USER)
    r = client.delete(
        "/v1/secrets/DOES_NOT_EXIST",
        headers={"X-Telegram-Init-Data": init},
    )
    assert r.status_code == 404


def test_delete_rejects_invalid_name(client):
    init = build_init_data(ALLOWED_USER)
    r = client.delete(
        "/v1/secrets/bad name with spaces",
        headers={"X-Telegram-Init-Data": init},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------


def test_cors_allows_github_pages_origin(client):
    r = client.options(
        "/v1/secrets",
        headers={
            "Origin": "https://ruimgoncalves.github.io",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Telegram-Init-Data",
        },
    )
    assert r.status_code in (200, 204)
    assert r.headers.get("access-control-allow-origin") == "https://ruimgoncalves.github.io"


def test_cors_blocks_random_origin(client):
    r = client.options(
        "/v1/secrets",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    # CORS middleware should not echo the evil origin
    assert r.headers.get("access-control-allow-origin") != "https://evil.example.com"
