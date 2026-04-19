"""Mapping: our internal variable codes → external data source identifiers.

Only single-year, directly-mapped variables are listed here. Multi-year aggregates
(e.g. 5-year inflation averages) will be computed in a later plan and aren't in
scope for Plan 3.

The tuple is (source, indicator_id). `source` is one of our `observation_source`
enum values. `indicator_id` for source='WB' or source='WGI' is the World Bank
Open Data indicator code.
"""
from __future__ import annotations
from typing import Literal

SourceTag = Literal["WB", "WGI"]

# Single-year mappings. Extend this dict when adding indicators.
WORLD_BANK_SOURCES: dict[str, tuple[SourceTag, str]] = {
    "gdp_capita":          ("WB",  "NY.GDP.PCAP.CD"),      # GDP per capita (current US$)
    "rol":                 ("WGI", "RL.EST"),              # WGI: Rule of Law, estimate
    "pr":                  ("WGI", "PV.EST"),              # WGI: Political Stability estimate
    "db":                  ("WB",  "IC.BUS.EASE.XQ"),      # Ease of doing business (discontinued 2022, historical still available)
    "cof":                 ("WB",  "FR.INR.LEND"),         # Lending interest rate (%)
    "debt_service_ratio":  ("WB",  "DT.TDS.DECT.EX.ZS"),   # Total debt service (% of exports of goods, services and primary income)
}


def indicator_for(variable_code: str) -> tuple[SourceTag, str]:
    """Return (source, indicator_id) for a variable code, or raise KeyError."""
    if variable_code not in WORLD_BANK_SOURCES:
        raise KeyError(f"no World Bank mapping for variable '{variable_code}'")
    return WORLD_BANK_SOURCES[variable_code]


def variables_available_via_api() -> tuple[str, ...]:
    """All variable codes currently fetchable via the World Bank API."""
    return tuple(WORLD_BANK_SOURCES.keys())
