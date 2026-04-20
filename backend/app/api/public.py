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


@router.get("/countries/{iso3}", response_model=CountrySummaryOut)
def get_country(
    iso3: str,
    user: CurrentUser = Depends(get_current_user),
) -> CountrySummaryOut:
    ref_repo = ReferenceRepository(user_client(user.raw_jwt))
    pub_repo = PublishedScoreRepository(user_client(user.raw_jwt))

    countries = {c.iso3: c for c in ref_repo.list_countries()}
    c = countries.get(iso3.upper())
    if not c:
        raise HTTPException(status_code=_status.HTTP_404_NOT_FOUND, detail=f"country '{iso3}' not found")

    latest = pub_repo.latest_scores_map().get(c.iso3)
    return CountrySummaryOut(
        iso3=c.iso3,
        name=c.name,
        region=c.region,
        latest_final_score=float(latest["final_score"]) if latest else None,
        latest_bucket_band=latest["bucket_band"] if latest else None,
        latest_segment=latest["segment"] if latest else None,
        latest_snapshot_id=latest["snapshot_id"] if latest else None,
        latest_as_of_date=latest["as_of_date"] if latest else None,
        latest_published_at=latest["published_at"] if latest else None,
    )


@router.get("/countries/{iso3}/score", response_model=CountryScoreOut)
def get_country_score(
    iso3: str,
    as_of: _date | None = Query(default=None),
    snapshot_id: UUID | None = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
) -> CountryScoreOut:
    if as_of is not None and snapshot_id is not None:
        raise HTTPException(status_code=_status.HTTP_400_BAD_REQUEST, detail="pass at most one of ?as_of and ?snapshot_id")

    ref_repo = ReferenceRepository(user_client(user.raw_jwt))
    pub_repo = PublishedScoreRepository(user_client(user.raw_jwt))

    countries = {c.iso3: c for c in ref_repo.list_countries()}
    c = countries.get(iso3.upper())
    if not c:
        raise HTTPException(status_code=_status.HTTP_404_NOT_FOUND, detail=f"country '{iso3}' not found")

    # Resolve which snapshot we're reading from.
    if snapshot_id is not None:
        snap = pub_repo.get_published_snapshot(snapshot_id)
    elif as_of is not None:
        snap = pub_repo.published_snapshot_as_of(as_of)
    else:
        snap = pub_repo.latest_published_snapshot()

    if snap is None:
        raise HTTPException(status_code=_status.HTTP_404_NOT_FOUND, detail="no published snapshot matches the query")

    score = pub_repo.score_for_country_in_snapshot(UUID(snap["id"]), c.iso3)
    if score is None:
        raise HTTPException(status_code=_status.HTTP_404_NOT_FOUND, detail=f"country '{iso3}' not scored in snapshot '{snap['id']}'")

    return CountryScoreOut(
        iso3=c.iso3,
        name=c.name,
        segment=score["segment"],
        final_score=float(score["final_score"]),
        quant_score=float(score["quant_score"]),
        qual_score=float(score["qual_score"]),
        bucket_band=score["bucket_band"],
        snapshot_id=UUID(snap["id"]),
        snapshot_name=snap["name"],
        as_of_date=snap["as_of_date"],
        published_at=snap["published_at"],
        model_version_high=UUID(snap["model_version_high"]) if snap.get("model_version_high") else None,
        model_version_low=UUID(snap["model_version_low"]) if snap.get("model_version_low") else None,
        model_version_nodata=UUID(snap["model_version_nodata"]) if snap.get("model_version_nodata") else None,
    )


@router.get("/countries/{iso3}/score/drivers", response_model=list[DriverBreakdownOut])
def get_country_drivers(
    iso3: str,
    snapshot_id: UUID,
    user: CurrentUser = Depends(get_current_user),
) -> list[DriverBreakdownOut]:
    pub_repo = PublishedScoreRepository(user_client(user.raw_jwt))

    # Verify the snapshot is published — prevents leaking draft drivers via this route.
    snap = pub_repo.get_published_snapshot(snapshot_id)
    if snap is None:
        raise HTTPException(status_code=_status.HTTP_404_NOT_FOUND, detail="snapshot not found or not published")

    rows = pub_repo.drivers_for_country_in_snapshot(snapshot_id, iso3.upper())
    out: list[DriverBreakdownOut] = []
    for r in rows:
        variable = r.get("variables") or {}
        out.append(DriverBreakdownOut(
            variable_code=r["variable_code"],
            variable_name=variable.get("name", r["variable_code"]),
            category=variable.get("category", ""),
            direction=variable.get("direction", ""),
            is_quantitative=variable.get("is_quantitative", False),
            raw_value=float(r["raw_value"]) if r.get("raw_value") is not None else None,
            standardised_value=float(r["standardised_value"]) if r.get("standardised_value") is not None else None,
            bucket_score=float(r["bucket_score"]) if r.get("bucket_score") is not None else None,
            contribution=float(r["contribution"]),
        ))
    return out


@router.get("/countries/{iso3}/history", response_model=list[HistoryPointOut])
def get_country_history(
    iso3: str,
    user: CurrentUser = Depends(get_current_user),
) -> list[HistoryPointOut]:
    pub_repo = PublishedScoreRepository(user_client(user.raw_jwt))
    rows = pub_repo.history_for_country(iso3.upper())

    out: list[HistoryPointOut] = []
    for r in rows:
        snap = r.get("score_snapshots") or {}
        out.append(HistoryPointOut(
            snapshot_id=UUID(snap["id"]),
            snapshot_name=snap["name"],
            as_of_date=snap["as_of_date"],
            published_at=snap["published_at"],
            segment=r["segment"],
            final_score=float(r["final_score"]),
            quant_score=float(r["quant_score"]),
            qual_score=float(r["qual_score"]),
            bucket_band=r.get("bucket_band"),
        ))
    return out


@router.get("/snapshots", response_model=list[PublishedSnapshotOut])
def list_published_snapshots(
    user: CurrentUser = Depends(get_current_user),
) -> list[PublishedSnapshotOut]:
    pub_repo = PublishedScoreRepository(user_client(user.raw_jwt))
    rows = pub_repo.list_published_snapshots(limit=100)
    return [PublishedSnapshotOut(**r) for r in rows]


@router.get("/snapshots/{snapshot_id}", response_model=PublishedSnapshotOut)
def get_published_snapshot_detail(
    snapshot_id: UUID,
    user: CurrentUser = Depends(get_current_user),
) -> PublishedSnapshotOut:
    pub_repo = PublishedScoreRepository(user_client(user.raw_jwt))
    snap = pub_repo.get_published_snapshot(snapshot_id)
    if snap is None:
        raise HTTPException(status_code=_status.HTTP_404_NOT_FOUND, detail="snapshot not found or not published")
    return PublishedSnapshotOut(**snap)


@router.get("/snapshots/{snapshot_id}/scores", response_model=list[CountryScoreOut])
def get_snapshot_scores(
    snapshot_id: UUID,
    user: CurrentUser = Depends(get_current_user),
) -> list[CountryScoreOut]:
    ref_repo = ReferenceRepository(user_client(user.raw_jwt))
    pub_repo = PublishedScoreRepository(user_client(user.raw_jwt))

    snap = pub_repo.get_published_snapshot(snapshot_id)
    if snap is None:
        raise HTTPException(status_code=_status.HTTP_404_NOT_FOUND, detail="snapshot not found or not published")

    countries = {c.iso3: c for c in ref_repo.list_countries()}
    rows = pub_repo.scores_for_snapshot(snapshot_id)

    out: list[CountryScoreOut] = []
    for r in rows:
        c = countries.get(r["iso3"])
        if c is None:
            continue  # orphaned score row; skip
        out.append(CountryScoreOut(
            iso3=c.iso3,
            name=c.name,
            segment=r["segment"],
            final_score=float(r["final_score"]),
            quant_score=float(r["quant_score"]),
            qual_score=float(r["qual_score"]),
            bucket_band=r.get("bucket_band"),
            snapshot_id=UUID(snap["id"]),
            snapshot_name=snap["name"],
            as_of_date=snap["as_of_date"],
            published_at=snap["published_at"],
            model_version_high=UUID(snap["model_version_high"]) if snap.get("model_version_high") else None,
            model_version_low=UUID(snap["model_version_low"]) if snap.get("model_version_low") else None,
            model_version_nodata=UUID(snap["model_version_nodata"]) if snap.get("model_version_nodata") else None,
        ))
    return out
