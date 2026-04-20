from __future__ import annotations
import time
import pytest
from jose import jwt
from fastapi.testclient import TestClient

JWT_SECRET = "test-jwt-secret"


def _token(user_id: str = "11111111-1111-1111-1111-111111111111") -> str:
    payload = {
        "sub": user_id,
        "email": "tester@example.com",
        "aud": "authenticated",
        "role": "authenticated",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


class _FakeWB:
    def __init__(self) -> None:
        self.payloads = {
            ("NY.GDP.PCAP.CD", 2021, 2021): [
                ("USA", 2021, 70000.0),
                ("ZAF", 2021, 6000.0),
            ]
        }

    def fetch_indicator(self, indicator_id, start_year, end_year):
        return self.payloads[(indicator_id, start_year, end_year)]


class _FakeRepo:
    def __init__(self) -> None:
        from uuid import uuid4
        self.upload_id = uuid4()
        self.observations: list = []

    def create_upload(self, source, file_name, notes, uploaded_by):
        return self.upload_id

    def insert_observations(self, rows, upload_id, ingested_by):
        self.observations.extend(rows)
        return len(rows)

    def known_iso3_codes(self) -> set[str]:
        return {"USA", "ZAF"}


@pytest.fixture
def client(monkeypatch):
    from app.main import create_app
    from app.api import admin
    from app.schemas.user import CurrentUser
    from uuid import UUID

    app = create_app()

    async def _override_internal():
        return CurrentUser(
            user_id=UUID("11111111-1111-1111-1111-111111111111"),
            email="tester@example.com",
            raw_jwt="test",
        )

    app.dependency_overrides[admin._require_internal] = _override_internal

    fake_wb = _FakeWB()
    fake_repo = _FakeRepo()

    monkeypatch.setattr("app.api.admin.WorldBankClient", lambda: fake_wb)
    monkeypatch.setattr("app.api.admin.service_client", lambda: object())
    monkeypatch.setattr("app.api.admin.RawObservationRepository", lambda _client: fake_repo)

    return TestClient(app), fake_repo


def test_ingest_world_bank_happy_path(client):
    c, repo = client
    r = c.post(
        "/admin/ingest/world-bank",
        headers={"Authorization": f"Bearer {_token()}"},
        json={"variables": ["gdp_capita"], "year": 2021, "notes": "manual test"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rows_inserted"] == 2
    assert body["rows_skipped_null_value"] == 0
    assert body["year"] == 2021
    assert body["variables_ingested"] == ["gdp_capita"]
    assert len(repo.observations) == 2


def test_ingest_unknown_variable_returns_400(client):
    c, _ = client
    r = c.post(
        "/admin/ingest/world-bank",
        headers={"Authorization": f"Bearer {_token()}"},
        json={"variables": ["not_a_variable"], "year": 2021},
    )
    assert r.status_code == 400
    assert "not_a_variable" in r.text
