from __future__ import annotations
import httpx
import pytest
import respx

from app.ingestion.world_bank import IndicatorArchivedError, WorldBankClient, WorldBankError


@pytest.fixture
def client() -> WorldBankClient:
    return WorldBankClient(base_url="https://api.worldbank.org/v2", timeout_seconds=5.0)


@respx.mock
def test_fetch_indicator_for_year_returns_iso3_to_value(client):
    respx.get("https://api.worldbank.org/v2/country/all/indicator/NY.GDP.PCAP.CD").respond(
        200,
        json=[
            {"page": 1, "pages": 1, "per_page": 500, "total": 2, "sourceid": "2"},
            [
                {"indicator": {"id": "NY.GDP.PCAP.CD", "value": "GDP per capita"},
                 "country": {"id": "US", "value": "United States"},
                 "countryiso3code": "USA", "date": "2021",
                 "value": 70248.6258893, "unit": "", "obs_status": "", "decimal": 1},
                {"indicator": {"id": "NY.GDP.PCAP.CD", "value": "GDP per capita"},
                 "country": {"id": "ZA", "value": "South Africa"},
                 "countryiso3code": "ZAF", "date": "2021",
                 "value": 6994.2, "unit": "", "obs_status": "", "decimal": 1},
            ],
        ],
    )

    result = client.fetch_indicator_for_year(indicator_id="NY.GDP.PCAP.CD", year=2021)

    assert result == {"USA": 70248.6258893, "ZAF": 6994.2}


@respx.mock
def test_fetch_indicator_handles_null_values(client):
    respx.get("https://api.worldbank.org/v2/country/all/indicator/NY.GDP.PCAP.CD").respond(
        200,
        json=[
            {"page": 1, "pages": 1, "per_page": 500, "total": 1, "sourceid": "2"},
            [
                {"indicator": {"id": "NY.GDP.PCAP.CD", "value": "GDP per capita"},
                 "country": {"id": "EX", "value": "Example"},
                 "countryiso3code": "EXX", "date": "2021",
                 "value": None, "unit": "", "obs_status": "", "decimal": 1},
            ],
        ],
    )

    result = client.fetch_indicator_for_year(indicator_id="NY.GDP.PCAP.CD", year=2021)

    assert result == {"EXX": None}


@respx.mock
def test_fetch_indicator_follows_pagination(client):
    respx.get("https://api.worldbank.org/v2/country/all/indicator/NY.GDP.PCAP.CD", params__contains={"page": "1"}).respond(
        200,
        json=[
            {"page": 1, "pages": 2, "per_page": 1, "total": 2, "sourceid": "2"},
            [{"countryiso3code": "USA", "date": "2021", "value": 70248.6,
              "indicator": {"id": "NY.GDP.PCAP.CD", "value": ""},
              "country": {"id": "US", "value": ""}, "unit": "", "obs_status": "", "decimal": 1}],
        ],
    )
    respx.get("https://api.worldbank.org/v2/country/all/indicator/NY.GDP.PCAP.CD", params__contains={"page": "2"}).respond(
        200,
        json=[
            {"page": 2, "pages": 2, "per_page": 1, "total": 2, "sourceid": "2"},
            [{"countryiso3code": "ZAF", "date": "2021", "value": 6994.2,
              "indicator": {"id": "NY.GDP.PCAP.CD", "value": ""},
              "country": {"id": "ZA", "value": ""}, "unit": "", "obs_status": "", "decimal": 1}],
        ],
    )

    result = client.fetch_indicator_for_year(indicator_id="NY.GDP.PCAP.CD", year=2021)

    assert result == {"USA": 70248.6, "ZAF": 6994.2}


@respx.mock
def test_fetch_indicator_raises_on_http_error(client):
    respx.get("https://api.worldbank.org/v2/country/all/indicator/NY.GDP.PCAP.CD").respond(500, text="server error")

    with pytest.raises(WorldBankError, match="status 500"):
        client.fetch_indicator_for_year(indicator_id="NY.GDP.PCAP.CD", year=2021)


@respx.mock
def test_fetch_indicator_raises_on_invalid_shape(client):
    respx.get("https://api.worldbank.org/v2/country/all/indicator/NY.GDP.PCAP.CD").respond(
        200, json={"this_is_not": "an_array"}
    )

    with pytest.raises(WorldBankError, match="unexpected response shape"):
        client.fetch_indicator_for_year(indicator_id="NY.GDP.PCAP.CD", year=2021)


@respx.mock
def test_fetch_indicator_raises_archived_when_wb_reports_indicator_deleted(client):
    # The WB API returns `[{"message": [...]}]` when an indicator has been archived/removed.
    respx.get("https://api.worldbank.org/v2/country/all/indicator/IC.BUS.EASE.XQ").respond(
        200,
        json=[{"message": [{"id": "175", "key": "Invalid format",
                            "value": "The indicator was not found. It may have been deleted or archived."}]}],
    )

    with pytest.raises(IndicatorArchivedError, match="archived"):
        client.fetch_indicator_for_year(indicator_id="IC.BUS.EASE.XQ", year=2021)
