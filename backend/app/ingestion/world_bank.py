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


@dataclass
class WorldBankClient:
    base_url: str = "https://api.worldbank.org/v2"
    timeout_seconds: float = 30.0
    per_page: int = 500

    def fetch_indicator_for_year(
        self,
        indicator_id: str,
        year: int,
    ) -> dict[str, float | None]:
        """Return {iso3: value} for every country with a reported observation.

        Countries absent from the response are simply not in the returned dict.
        Values reported as null by the WB API are kept as None in the dict.
        """
        out: dict[str, float | None] = {}
        page = 1
        while True:
            params = {
                "format": "json",
                "date": str(year),
                "per_page": str(self.per_page),
                "page": str(page),
            }
            url = f"{self.base_url}/country/all/indicator/{indicator_id}"
            try:
                with httpx.Client(timeout=self.timeout_seconds) as http:
                    resp = http.get(url, params=params)
            except httpx.HTTPError as exc:
                raise WorldBankError(f"HTTP error fetching {indicator_id}: {exc}") from exc

            if resp.status_code != 200:
                raise WorldBankError(
                    f"World Bank API returned status {resp.status_code} for {indicator_id}"
                )

            try:
                payload = resp.json()
            except Exception as exc:
                raise WorldBankError(f"could not parse JSON from WB response: {exc}") from exc

            if not isinstance(payload, list) or len(payload) != 2 or not isinstance(payload[1], list):
                raise WorldBankError(f"unexpected response shape for {indicator_id}")

            meta, rows = payload
            for row in rows:
                iso3 = row.get("countryiso3code")
                if not iso3:
                    continue
                val = row.get("value")
                out[iso3] = float(val) if isinstance(val, (int, float)) else None

            total_pages = int(meta.get("pages", 1))
            if page >= total_pages:
                break
            page += 1
        return out
