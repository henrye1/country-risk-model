"""Live-network test against api.worldbank.org. Marked integration so it skips by default.

Enable with:
    pytest -m integration backend/tests/integration/test_world_bank_live.py
"""
from __future__ import annotations
import pytest

from app.ingestion.world_bank import WorldBankClient


@pytest.mark.integration
def test_fetch_gdp_capita_for_2021_returns_known_countries():
    client = WorldBankClient(timeout_seconds=20.0)
    result = client.fetch_indicator_for_year("NY.GDP.PCAP.CD", 2021)

    # We don't assert a specific number — the WB API restates history occasionally.
    # But these three ISO3 codes should always be in the response.
    assert "USA" in result
    assert "ZAF" in result
    assert "GBR" in result
    assert isinstance(result["USA"], float) or result["USA"] is None
