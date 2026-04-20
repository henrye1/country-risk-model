"""Minimal World Bank Open Data API client.

Fetches one indicator for all countries for one year, follows pagination,
returns a plain dict mapping iso3 country codes → value (float or None).

No Supabase, no FastAPI. Only httpx + stdlib.
"""
from __future__ import annotations
from dataclasses import dataclass

import httpx


class WorldBankError(RuntimeError):
    """Raised when the WB API returns an unexpected response or non-2xx status."""


class IndicatorArchivedError(WorldBankError):
    """Raised when the WB API reports the indicator was deleted/archived.

    Callers that want to continue processing other indicators should catch this
    specifically and add a warning, not abort the whole batch.
    """


@dataclass
class WorldBankClient:
    base_url: str = "https://api.worldbank.org/v2"
    timeout_seconds: float = 60.0  # WGI / interest-rate endpoints are slow
    per_page: int = 500
    max_retries: int = 2            # retry transient errors (e.g. read timeouts)

    def fetch_indicator_for_year(
        self,
        indicator_id: str,
        year: int,
    ) -> dict[str, float | None]:
        """Convenience wrapper: return {iso3: value} for a single year."""
        triples = self.fetch_indicator(indicator_id, start_year=year, end_year=year)
        return {iso3: value for iso3, _year, value in triples}

    def fetch_indicator(
        self,
        indicator_id: str,
        start_year: int,
        end_year: int,
    ) -> list[tuple[str, int, float | None]]:
        """Return (iso3, year, value) tuples for every country-year in range.

        Uses the WB API's native date range (`date=YYYY:YYYY`) so one logical
        call covers many years. Pagination is still followed. Country-years
        with null values are kept with value=None.

        Raises `IndicatorArchivedError` if the WB API reports the indicator
        has been deleted or archived.
        """
        if end_year < start_year:
            raise ValueError(f"end_year ({end_year}) < start_year ({start_year})")

        out: list[tuple[str, int, float | None]] = []
        page = 1
        while True:
            params = {
                "format": "json",
                "date": f"{start_year}:{end_year}",
                "per_page": str(self.per_page),
                "page": str(page),
            }
            url = f"{self.base_url}/country/all/indicator/{indicator_id}"

            # Retry on network / timeout errors.
            resp = None
            last_exc: Exception | None = None
            for attempt in range(self.max_retries + 1):
                try:
                    with httpx.Client(timeout=self.timeout_seconds) as http:
                        resp = http.get(url, params=params)
                    break
                except httpx.HTTPError as exc:
                    last_exc = exc
            if resp is None:
                raise WorldBankError(
                    f"HTTP error fetching {indicator_id} after {self.max_retries + 1} attempts: {last_exc}"
                ) from last_exc

            if resp.status_code != 200:
                raise WorldBankError(
                    f"World Bank API returned status {resp.status_code} for {indicator_id}"
                )

            try:
                payload = resp.json()
            except Exception as exc:
                raise WorldBankError(f"could not parse JSON from WB response: {exc}") from exc

            # The API sometimes returns [{"message": [...]}] for archived/invalid indicators.
            if (
                isinstance(payload, list)
                and len(payload) == 1
                and isinstance(payload[0], dict)
                and "message" in payload[0]
            ):
                messages = payload[0]["message"]
                text = messages[0].get("value", "indicator unavailable") if messages else "indicator unavailable"
                raise IndicatorArchivedError(f"{indicator_id}: {text}")

            if not isinstance(payload, list) or len(payload) != 2 or not isinstance(payload[1], list):
                raise WorldBankError(f"unexpected response shape for {indicator_id}")

            meta, rows = payload
            for row in rows:
                iso3 = row.get("countryiso3code")
                if not iso3:
                    continue
                date_str = row.get("date")
                try:
                    year = int(date_str) if date_str is not None else None
                except (TypeError, ValueError):
                    year = None
                if year is None:
                    continue
                val = row.get("value")
                parsed = float(val) if isinstance(val, (int, float)) else None
                out.append((iso3, year, parsed))

            total_pages = int(meta.get("pages", 1))
            if page >= total_pages:
                break
            page += 1
        return out
