from __future__ import annotations
import time
from uuid import UUID
import pytest
from jose import jwt
from fastapi.testclient import TestClient

JWT_SECRET = "test-jwt-secret"
SID = UUID("11111111-1111-1111-1111-111111111111")


def _token(user_id: str = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa") -> str:
    payload = {
        "sub": user_id,
        "email": "tester@example.com",
        "aud": "authenticated",
        "role": "authenticated",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


class _FakeRefRepo:
    def list_countries(self):
        from app.schemas.country import CountryOut
        return [
            CountryOut(iso3="USA", name="UNITED STATES", region="DEVELOPED"),
            CountryOut(iso3="ZAF", name="SOUTH AFRICA", region="AFRICA"),
        ]

    def list_variables(self):
        return []


class _FakePubRepo:
    def __init__(self) -> None:
        self.snap = {
            "id": str(SID),
            "name": "2022-FY-subset",
            "as_of_date": "2022-12-31",
            "status": "published",
            "model_version_high": None,
            "model_version_low": None,
            "model_version_nodata": None,
            "published_at": "2026-04-20T10:00:00Z",
            "published_notes": "first",
        }

    def latest_published_snapshot(self):
        return self.snap

    def get_published_snapshot(self, _id):
        return self.snap if str(_id) == self.snap["id"] else None

    def published_snapshot_as_of(self, _date):
        return self.snap

    def list_published_snapshots(self, limit=50):
        return [self.snap]

    def latest_scores_map(self):
        return {
            "USA": {
                "iso3": "USA", "segment": "HIGH", "final_score": 1.5,
                "quant_score": 1.0, "qual_score": 0.5, "bucket_band": None,
                "snapshot_id": self.snap["id"], "snapshot_name": self.snap["name"],
                "as_of_date": self.snap["as_of_date"], "published_at": self.snap["published_at"],
            }
        }

    def scores_for_snapshot(self, _id):
        return [
            {"iso3": "USA", "segment": "HIGH", "final_score": 1.5,
             "quant_score": 1.0, "qual_score": 0.5, "bucket_band": None},
        ]

    def score_for_country_in_snapshot(self, _id, iso3):
        if iso3 != "USA":
            return None
        return self.scores_for_snapshot(_id)[0]

    def history_for_country(self, _iso3):
        return [
            {
                "final_score": 1.2, "quant_score": 1.0, "qual_score": 0.2,
                "segment": "HIGH", "bucket_band": None,
                "score_snapshots": self.snap,
            },
        ]

    def drivers_for_country_in_snapshot(self, _id, _iso3):
        return [
            {
                "variable_code": "gdp_capita",
                "raw_value": 70000.0, "standardised_value": 1.0,
                "bucket_score": 1.0, "contribution": 1.0,
                "variables": {"name": "GDP per capita", "category": "Economic",
                              "direction": "higher_better", "is_quantitative": True},
            },
        ]


@pytest.fixture
def client(monkeypatch):
    from app.main import create_app
    app = create_app()
    monkeypatch.setattr("app.api.public.ReferenceRepository", lambda _client: _FakeRefRepo())
    monkeypatch.setattr("app.api.public.PublishedScoreRepository", lambda _client: _FakePubRepo())
    monkeypatch.setattr("app.api.public.user_client", lambda _jwt: object())
    return TestClient(app)


def test_list_countries_includes_latest_score(client):
    r = client.get("/v1/countries", headers={"Authorization": f"Bearer {_token()}"})
    assert r.status_code == 200, r.text
    body = r.json()
    usa = next(b for b in body if b["iso3"] == "USA")
    zaf = next(b for b in body if b["iso3"] == "ZAF")
    assert usa["latest_final_score"] == 1.5
    assert zaf["latest_final_score"] is None  # not in the latest_scores_map


def test_country_detail_returns_latest_score(client):
    r = client.get("/v1/countries/USA", headers={"Authorization": f"Bearer {_token()}"})
    assert r.status_code == 200
    body = r.json()
    assert body["iso3"] == "USA"
    assert body["latest_final_score"] == 1.5


def test_country_detail_404_for_unknown(client):
    r = client.get("/v1/countries/QQQ", headers={"Authorization": f"Bearer {_token()}"})
    assert r.status_code == 404


def test_country_score_default_returns_latest(client):
    r = client.get("/v1/countries/USA/score", headers={"Authorization": f"Bearer {_token()}"})
    assert r.status_code == 200
    body = r.json()
    assert body["final_score"] == 1.5
    assert body["snapshot_id"] == str(SID)


def test_country_score_rejects_both_query_params(client):
    r = client.get(
        "/v1/countries/USA/score?as_of=2022-12-31&snapshot_id=" + str(SID),
        headers={"Authorization": f"Bearer {_token()}"},
    )
    assert r.status_code == 400


def test_country_history_returns_list(client):
    r = client.get("/v1/countries/USA/history", headers={"Authorization": f"Bearer {_token()}"})
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["segment"] == "HIGH"


def test_country_drivers_requires_snapshot_id(client):
    r = client.get("/v1/countries/USA/score/drivers", headers={"Authorization": f"Bearer {_token()}"})
    assert r.status_code == 422  # FastAPI validation error for missing query param


def test_country_drivers_with_snapshot_id(client):
    r = client.get(
        f"/v1/countries/USA/score/drivers?snapshot_id={SID}",
        headers={"Authorization": f"Bearer {_token()}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body[0]["variable_code"] == "gdp_capita"
    assert body[0]["variable_name"] == "GDP per capita"


def test_list_snapshots_returns_published_only(client):
    r = client.get("/v1/snapshots", headers={"Authorization": f"Bearer {_token()}"})
    assert r.status_code == 200
    assert r.json()[0]["status"] == "published"


def test_snapshot_scores_returns_country_scores(client):
    r = client.get(f"/v1/snapshots/{SID}/scores", headers={"Authorization": f"Bearer {_token()}"})
    assert r.status_code == 200
    body = r.json()
    assert body[0]["iso3"] == "USA"
    assert body[0]["snapshot_id"] == str(SID)
