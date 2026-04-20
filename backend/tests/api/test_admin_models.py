from __future__ import annotations
import time
from uuid import UUID, uuid4
import pytest
from jose import jwt
from fastapi.testclient import TestClient

JWT_SECRET = "test-jwt-secret"


def _token(user_id: str = "11111111-1111-1111-1111-111111111111") -> str:
    payload = {
        "sub": user_id,
        "email": "owner@anchorpointrisk.local",
        "aud": "authenticated",
        "role": "authenticated",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


class _FakeRepo:
    def __init__(self) -> None:
        self.rows: dict[UUID, dict] = {}
        self.created_id = uuid4()

    def list(self):
        return list(self.rows.values())

    def get(self, mid):
        return self.rows.get(UUID(str(mid)))

    def set_status(self, mid, new_status):
        row = self.rows[UUID(str(mid))]
        row["status"] = new_status
        return row

    def save(self, trained, training_notes=None):
        new = {
            "id": str(self.created_id),
            "segment": trained.segment,
            "status": "pending_review",
            "trained_at": "2026-04-20T13:00:00Z",
            "training_notes": training_notes,
            "training_data_hash": trained.training_data_hash,
            "fit_metrics_json": dict(trained.fit_metrics),
        }
        self.rows[self.created_id] = new
        return self.created_id


@pytest.fixture
def client(monkeypatch):
    from app.main import create_app
    from app.api import admin
    from app.schemas.user import CurrentUser
    from uuid import UUID

    app = create_app()

    async def _override_owner():
        return CurrentUser(
            user_id=UUID("11111111-1111-1111-1111-111111111111"),
            email="owner@anchorpointrisk.local",
            raw_jwt="test",
        )

    async def _override_internal():
        return CurrentUser(
            user_id=UUID("11111111-1111-1111-1111-111111111111"),
            email="analyst@anchorpointrisk.local",
            raw_jwt="test",
        )

    app.dependency_overrides[admin._require_owner] = _override_owner
    app.dependency_overrides[admin._require_internal] = _override_internal

    fake_repo = _FakeRepo()
    monkeypatch.setattr("app.api.admin.ModelVersionRepository", lambda _client: fake_repo)
    monkeypatch.setattr("app.api.admin.service_client", lambda: object())

    # Patch train_segment to bypass real CSV/sklearn work
    from app.services.training import TrainResult

    def _fake_train(*args, **kwargs):
        return TrainResult(
            model_version_id=fake_repo.created_id,
            segment=kwargs.get("segment", "HIGH"),
            fit_metrics={"r2": 0.05, "rmse": 0.9, "n_training_rows": 50.0},
            n_training_rows=50,
        )

    # Inject a fake row into the repo so transitions/get/list have something to work with
    fake_repo.rows[fake_repo.created_id] = {
        "id": str(fake_repo.created_id),
        "segment": "HIGH",
        "status": "pending_review",
        "trained_at": "2026-04-20T13:00:00Z",
        "training_notes": "test",
        "training_data_hash": "deadbeef" * 8,
        "fit_metrics_json": {"r2": 0.05},
    }

    monkeypatch.setattr("app.api.admin.train_segment", _fake_train)
    return TestClient(app), fake_repo


def test_list_models(client):
    c, _ = client
    r = c.get("/admin/model-versions", headers={"Authorization": f"Bearer {_token()}"})
    assert r.status_code == 200
    assert len(r.json()) >= 1


def test_get_model_404(client):
    c, _ = client
    r = c.get(f"/admin/model-versions/{uuid4()}", headers={"Authorization": f"Bearer {_token()}"})
    assert r.status_code == 404


def test_train_returns_201_and_pending_review(client):
    c, repo = client
    r = c.post(
        "/admin/model-versions",
        headers={"Authorization": f"Bearer {_token()}"},
        json={
            "segment": "HIGH",
            "quant_codes": ["gdp_capita"],
            "qual_codes": ["pr"],
            "notes": "test",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["segment"] == "HIGH"
    assert "fit_metrics" in body


def test_approve_then_activate_transitions(client):
    c, repo = client
    mid = repo.created_id
    r1 = c.post(f"/admin/model-versions/{mid}/approve", headers={"Authorization": f"Bearer {_token()}"})
    assert r1.status_code == 200
    assert r1.json()["status"] == "approved"

    r2 = c.post(f"/admin/model-versions/{mid}/activate", headers={"Authorization": f"Bearer {_token()}"})
    assert r2.status_code == 200
    assert r2.json()["status"] == "active"


def test_retire_works_from_pending(client):
    c, repo = client
    mid = repo.created_id
    r = c.post(f"/admin/model-versions/{mid}/retire", headers={"Authorization": f"Bearer {_token()}"})
    assert r.status_code == 200
    assert r.json()["status"] == "retired"
