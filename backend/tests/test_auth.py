from __future__ import annotations
import time
import pytest
from jose import jwt
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

JWT_SECRET = "test-jwt-secret"


def _token(user_id: str = "11111111-1111-1111-1111-111111111111", email: str = "u@example.com") -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
        "aud": "authenticated",
        "role": "authenticated",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


@pytest.fixture
def app_with_protected() -> FastAPI:
    from app.core.auth import get_current_user
    from app.schemas.user import CurrentUser

    app = FastAPI()

    @app.get("/me")
    def me(user: CurrentUser = Depends(get_current_user)) -> dict:
        return {"user_id": str(user.user_id), "email": user.email}

    return app


def test_missing_token_returns_401(app_with_protected):
    c = TestClient(app_with_protected)
    r = c.get("/me")
    assert r.status_code == 401


def test_invalid_token_returns_401(app_with_protected):
    c = TestClient(app_with_protected)
    r = c.get("/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401


def test_valid_token_returns_user(app_with_protected):
    c = TestClient(app_with_protected)
    r = c.get("/me", headers={"Authorization": f"Bearer {_token()}"})
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == "11111111-1111-1111-1111-111111111111"
    assert body["email"] == "u@example.com"
