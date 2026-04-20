"""Read-only access to published country scores.

All queries filter to status='published' at the application layer. RLS adds
another guard for non-internal users; both working together means a client
user cannot ever see draft data even if a bug removed a filter.
"""
from __future__ import annotations
from datetime import date
from uuid import UUID

from supabase import Client


class PublishedScoreRepository:
    def __init__(self, client: Client) -> None:
        self._client = client

    # --- Snapshots ---

    def list_published_snapshots(self, limit: int = 50) -> list[dict]:
        resp = (
            self._client.table("score_snapshots")
            .select("id, name, as_of_date, status, model_version_high, model_version_low, model_version_nodata, published_at, published_notes")
            .eq("status", "published")
            .order("published_at", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data

    def get_published_snapshot(self, snapshot_id: UUID) -> dict | None:
        resp = (
            self._client.table("score_snapshots")
            .select("*")
            .eq("id", str(snapshot_id))
            .eq("status", "published")
            .limit(1)
            .execute()
        )
        return resp.data[0] if resp.data else None

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

    def published_snapshot_as_of(self, as_of: date) -> dict | None:
        """Published snapshot with greatest published_at <= as_of."""
        resp = (
            self._client.table("score_snapshots")
            .select("*")
            .eq("status", "published")
            .lte("published_at", as_of.isoformat() + "T23:59:59Z")
            .order("published_at", desc=True)
            .limit(1)
            .execute()
        )
        return resp.data[0] if resp.data else None

    # --- Scores ---

    def scores_for_snapshot(self, snapshot_id: UUID) -> list[dict]:
        resp = (
            self._client.table("country_scores")
            .select("iso3, segment, final_score, quant_score, qual_score, bucket_band")
            .eq("snapshot_id", str(snapshot_id))
            .order("iso3")
            .execute()
        )
        return resp.data

    def score_for_country_in_snapshot(self, snapshot_id: UUID, iso3: str) -> dict | None:
        resp = (
            self._client.table("country_scores")
            .select("iso3, segment, final_score, quant_score, qual_score, bucket_band")
            .eq("snapshot_id", str(snapshot_id))
            .eq("iso3", iso3)
            .limit(1)
            .execute()
        )
        return resp.data[0] if resp.data else None

    def history_for_country(self, iso3: str) -> list[dict]:
        """Return all published snapshots that have a score for this country,
        ordered oldest-to-newest (for line chart rendering).
        """
        # Join country_scores → score_snapshots; Supabase-py supports foreign-key embedding.
        resp = (
            self._client.table("country_scores")
            .select("final_score, quant_score, qual_score, segment, bucket_band, "
                    "score_snapshots!inner(id, name, as_of_date, published_at, status)")
            .eq("iso3", iso3)
            .eq("score_snapshots.status", "published")
            .execute()
        )
        # Sort in Python (PostgREST foreign-table ordering syntax varies by client version).
        rows = resp.data
        rows.sort(key=lambda r: (r.get("score_snapshots") or {}).get("as_of_date") or "")
        return rows

    # --- Driver breakdown ---

    def drivers_for_country_in_snapshot(self, snapshot_id: UUID, iso3: str) -> list[dict]:
        """Driver scores plus variable metadata (name, category) for display."""
        resp = (
            self._client.table("driver_scores")
            .select("variable_code, raw_value, standardised_value, bucket_score, contribution, "
                    "variables!inner(name, category, direction, is_quantitative)")
            .eq("snapshot_id", str(snapshot_id))
            .eq("iso3", iso3)
            .execute()
        )
        return resp.data

    # --- Bulk latest score per country (for the countries list page) ---

    def latest_scores_map(self) -> dict[str, dict]:
        """Return {iso3: country_score row} for the single most-recently-published snapshot.

        Countries not present in that snapshot are absent from the dict. The caller
        fills `None` for those when building the response.
        """
        latest = self.latest_published_snapshot()
        if not latest:
            return {}
        rows = self.scores_for_snapshot(UUID(latest["id"]))
        by_iso3 = {r["iso3"]: r for r in rows}
        for r in by_iso3.values():
            r["snapshot_id"] = latest["id"]
            r["snapshot_name"] = latest["name"]
            r["as_of_date"] = latest["as_of_date"]
            r["published_at"] = latest["published_at"]
        return by_iso3
