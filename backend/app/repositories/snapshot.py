"""Persist + read score_snapshots, country_scores, driver_scores.

Writes use service_client (service_role); reads route through whichever client
the caller provides (typically user_client for RLS enforcement on /v1/ reads,
service_client for internal admin reads)."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from supabase import Client


@dataclass
class DraftSnapshotCreate:
    name: str
    as_of_date: date
    model_version_high: UUID | None
    model_version_low: UUID | None
    model_version_nodata: UUID | None
    created_by: UUID | None


@dataclass
class CountryScoreRow:
    iso3: str
    segment: str
    final_score: float
    quant_score: float
    qual_score: float
    bucket_band: str | None


@dataclass
class DriverScoreRow:
    iso3: str
    variable_code: str
    raw_value: float | None
    standardised_value: float | None
    bucket_score: float | None
    contribution: float


class SnapshotRepository:
    def __init__(self, client: Client) -> None:
        self._client = client

    # --- CRUD on score_snapshots ---

    def create_draft(self, draft: DraftSnapshotCreate) -> UUID:
        payload: dict[str, Any] = {
            "name": draft.name,
            "as_of_date": draft.as_of_date.isoformat(),
            "status": "draft",
            "model_version_high": str(draft.model_version_high) if draft.model_version_high else None,
            "model_version_low": str(draft.model_version_low) if draft.model_version_low else None,
            "model_version_nodata": str(draft.model_version_nodata) if draft.model_version_nodata else None,
            "created_by": str(draft.created_by) if draft.created_by else None,
        }
        resp = self._client.table("score_snapshots").insert(payload).execute()
        return UUID(resp.data[0]["id"])

    def get(self, snapshot_id: UUID) -> dict:
        resp = (
            self._client.table("score_snapshots")
            .select("*")
            .eq("id", str(snapshot_id))
            .single()
            .execute()
        )
        return resp.data

    def list_snapshots(self, statuses: list[str] | None = None, limit: int = 50) -> list[dict]:
        q = self._client.table("score_snapshots").select("*").order("as_of_date", desc=True).limit(limit)
        if statuses:
            q = q.in_("status", statuses)
        return q.execute().data

    def publish(self, snapshot_id: UUID, published_by: UUID | None, notes: str | None) -> dict:
        payload: dict[str, Any] = {
            "status": "published",
            "published_at": datetime.utcnow().isoformat() + "Z",
            "published_notes": notes,
        }
        if published_by is not None:
            payload["published_by"] = str(published_by)
        resp = (
            self._client.table("score_snapshots")
            .update(payload)
            .eq("id", str(snapshot_id))
            .execute()
        )
        return resp.data[0]

    def archive(self, snapshot_id: UUID) -> dict:
        resp = (
            self._client.table("score_snapshots")
            .update({"status": "archived"})
            .eq("id", str(snapshot_id))
            .execute()
        )
        return resp.data[0]

    # --- Writing draft score rows ---

    def wipe_draft_scores(self, snapshot_id: UUID) -> None:
        """Delete all country_scores + driver_scores for a snapshot.
        The DB trigger blocks this if the snapshot is published."""
        self._client.table("driver_scores").delete().eq("snapshot_id", str(snapshot_id)).execute()
        self._client.table("country_scores").delete().eq("snapshot_id", str(snapshot_id)).execute()

    def insert_country_scores(
        self, snapshot_id: UUID, rows: list[CountryScoreRow]
    ) -> int:
        if not rows:
            return 0
        payload = [
            {
                "snapshot_id": str(snapshot_id),
                "iso3": r.iso3,
                "segment": r.segment,
                "final_score": r.final_score,
                "quant_score": r.quant_score,
                "qual_score": r.qual_score,
                "bucket_band": r.bucket_band,
            }
            for r in rows
        ]
        return _chunked_insert(self._client, "country_scores", payload)

    def insert_driver_scores(
        self, snapshot_id: UUID, rows: list[DriverScoreRow]
    ) -> int:
        if not rows:
            return 0
        payload = [
            {
                "snapshot_id": str(snapshot_id),
                "iso3": r.iso3,
                "variable_code": r.variable_code,
                "raw_value": r.raw_value,
                "standardised_value": r.standardised_value,
                "bucket_score": r.bucket_score,
                "contribution": r.contribution,
            }
            for r in rows
        ]
        return _chunked_insert(self._client, "driver_scores", payload)

    # --- Reads for diff computation ---

    def latest_published_snapshot(self) -> dict | None:
        resp = (
            self._client.table("score_snapshots")
            .select("*")
            .eq("status", "published")
            .order("published_at", desc=True)
            .limit(1)
            .execute()
        )
        return resp.data[0] if resp.data else None

    def country_scores_for(self, snapshot_id: UUID) -> list[dict]:
        resp = (
            self._client.table("country_scores")
            .select("iso3, segment, final_score, quant_score, qual_score, bucket_band")
            .eq("snapshot_id", str(snapshot_id))
            .execute()
        )
        return resp.data


def _chunked_insert(client: Client, table: str, rows: list[dict], chunk_size: int = 500) -> int:
    """Insert in chunks to stay under Supabase-py batch limits."""
    inserted = 0
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i : i + chunk_size]
        resp = client.table(table).insert(chunk).execute()
        inserted += len(resp.data)
    return inserted
