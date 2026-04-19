from __future__ import annotations
import os
import time
import pytest
from jose import jwt
from fastapi.testclient import TestClient


def _dev_token(user_id: str, jwt_secret: str) -> str:
    payload = {
        "sub": user_id,
        "email": "tester@example.com",
        "aud": "authenticated",
        "role": "authenticated",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    return jwt.encode(payload, jwt_secret, algorithm="HS256")


def _env_or_skip(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        pytest.skip(f"Integration test requires env var {name}")
    return v


@pytest.mark.integration
def test_list_countries_requires_auth(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", _env_or_skip("SUPABASE_URL_DEV"))
    monkeypatch.setenv("SUPABASE_ANON_KEY", _env_or_skip("SUPABASE_ANON_KEY_DEV"))
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", _env_or_skip("SUPABASE_SERVICE_ROLE_KEY_DEV"))
    monkeypatch.setenv("SUPABASE_JWT_SECRET", _env_or_skip("SUPABASE_JWT_SECRET_DEV"))

    from app.core.settings import get_settings
    get_settings.cache_clear()
    from app.main import create_app
    c = TestClient(create_app())

    r = c.get("/v1/countries")
    assert r.status_code == 401


@pytest.mark.integration
def test_list_countries_returns_full_list(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", _env_or_skip("SUPABASE_URL_DEV"))
    monkeypatch.setenv("SUPABASE_ANON_KEY", _env_or_skip("SUPABASE_ANON_KEY_DEV"))
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", _env_or_skip("SUPABASE_SERVICE_ROLE_KEY_DEV"))
    monkeypatch.setenv("SUPABASE_JWT_SECRET", _env_or_skip("SUPABASE_JWT_SECRET_DEV"))

    from app.core.settings import get_settings
    get_settings.cache_clear()
    from app.main import create_app
    c = TestClient(create_app())

    token = _dev_token(
        _env_or_skip("TEST_OWNER_USER_ID"),
        _env_or_skip("SUPABASE_JWT_SECRET_DEV"),
    )
    r = c.get("/v1/countries", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    # Full country list from the prototype; the CSV you generated in Task 6 is the source of truth.
    assert len(r.json()) >= 150
