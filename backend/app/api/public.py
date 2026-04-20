from __future__ import annotations
from fastapi import APIRouter, Depends

from datetime import date as _date
from uuid import UUID

from fastapi import HTTPException, Query
from fastapi import status as _status

from app.core.auth import get_current_user
from app.core.supabase import user_client
from app.repositories.published_score import PublishedScoreRepository
from app.repositories.reference import ReferenceRepository
from app.schemas.country import CountryOut, CountryScoreOut, CountrySummaryOut
from app.schemas.snapshot import DriverBreakdownOut, HistoryPointOut, PublishedSnapshotOut
from app.schemas.user import CurrentUser
from app.schemas.variable import VariableOut

router = APIRouter(prefix="/v1", tags=["public"])


@router.get("/countries", response_model=list[CountrySummaryOut])
def list_countries(user: CurrentUser = Depends(get_current_user)) -> list[CountrySummaryOut]:
    ref_repo = ReferenceRepository(user_client(user.raw_jwt))
    pub_repo = PublishedScoreRepository(user_client(user.raw_jwt))

    countries = ref_repo.list_countries()
    latest = pub_repo.latest_scores_map()

    out: list[CountrySummaryOut] = []
    for c in countries:
        score = latest.get(c.iso3)
        out.append(CountrySummaryOut(
            iso3=c.iso3,
            name=c.name,
            region=c.region,
            latest_final_score=float(score["final_score"]) if score else None,
            latest_bucket_band=score["bucket_band"] if score else None,
            latest_segment=score["segment"] if score else None,
            latest_snapshot_id=score["snapshot_id"] if score else None,
            latest_as_of_date=score["as_of_date"] if score else None,
            latest_published_at=score["published_at"] if score else None,
        ))
    return out


@router.get("/variables", response_model=list[VariableOut])
def list_variables(user: CurrentUser = Depends(get_current_user)) -> list[VariableOut]:
    repo = ReferenceRepository(user_client(user.raw_jwt))
    return repo.list_variables()
