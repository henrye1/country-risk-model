"""Admin API router — internal organisation members only."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import get_current_user
from app.core.supabase import service_client
from app.ingestion.world_bank import WorldBankClient
from app.repositories.raw_observations import RawObservationRepository
from app.schemas.ingestion import IngestResultOut, WorldBankIngestRequest
from app.schemas.user import CurrentUser
from app.services.ingestion import IngestionService, UnknownVariable
from datetime import date as _date
from uuid import UUID
from app.repositories.segment import SegmentRepository
from app.repositories.snapshot import DraftSnapshotCreate, SnapshotRepository
from app.repositories.model_version import ModelVersionRepository
from app.schemas.snapshot import (
    ComputeSummaryOut,
    CreateSnapshotRequest,
    DiffOut,
    DiffRowOut,
    PublishRequest,
    SnapshotOut,
)
from app.services.snapshot import SnapshotService


router = APIRouter(prefix="/admin", tags=["admin"])


def _require_internal(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Role gate: the caller must belong to an organisation with status='internal'.
    We determine this by asking the service_client to read the caller's membership
    (bypasses RLS for this check).
    """
    client = service_client()
    resp = (
        client.table("memberships")
        .select("organisation_id, role, organisations(status)")
        .eq("user_id", str(user.user_id))
        .limit(1)
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="no membership")
    org_status = (resp.data[0].get("organisations") or {}).get("status")
    if org_status != "internal":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="internal only")
    return user


@router.post("/ingest/world-bank", response_model=IngestResultOut)
def ingest_world_bank(
    req: WorldBankIngestRequest,
    user: CurrentUser = Depends(_require_internal),
) -> IngestResultOut:
    client = service_client()
    repo = RawObservationRepository(client)
    wb = WorldBankClient()
    service = IngestionService(wb_client=wb, repo=repo)

    try:
        return service.ingest_world_bank(
            variable_codes=req.variables,
            start_year=req.start_year or req.year,
            end_year=req.end_year or req.year,
            user_id=user.user_id,
            notes=req.notes,
        )
    except UnknownVariable as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _snapshot_service() -> SnapshotService:
    client = service_client()
    return SnapshotService(
        obs_repo=RawObservationRepository(client),
        model_repo=ModelVersionRepository(client),
        snapshot_repo=SnapshotRepository(client),
        segment_repo=SegmentRepository(client),
    )


def _draft_from_db(row: dict) -> DraftSnapshotCreate:
    """Rehydrate the service's in-memory draft cache from a persisted snapshot row."""
    return DraftSnapshotCreate(
        name=row["name"],
        as_of_date=_date.fromisoformat(row["as_of_date"]),
        model_version_high=UUID(row["model_version_high"]) if row.get("model_version_high") else None,
        model_version_low=UUID(row["model_version_low"]) if row.get("model_version_low") else None,
        model_version_nodata=UUID(row["model_version_nodata"]) if row.get("model_version_nodata") else None,
        created_by=UUID(row["created_by"]) if row.get("created_by") else None,
    )


@router.post("/snapshots", response_model=SnapshotOut, status_code=status.HTTP_201_CREATED)
def create_snapshot(
    req: CreateSnapshotRequest,
    user: CurrentUser = Depends(_require_internal),
) -> SnapshotOut:
    service = _snapshot_service()
    snapshot_id = service.create_draft(
        name=req.name,
        as_of_date=req.as_of_date,
        model_version_high=req.model_version_high,
        model_version_low=req.model_version_low,
        model_version_nodata=req.model_version_nodata,
        created_by=user.user_id,
    )
    row = SnapshotRepository(service_client()).get(snapshot_id)
    return SnapshotOut(**row)


@router.post("/snapshots/{snapshot_id}/compute", response_model=ComputeSummaryOut)
def compute_snapshot(
    snapshot_id: UUID,
    user: CurrentUser = Depends(_require_internal),
) -> ComputeSummaryOut:
    service = _snapshot_service()
    row = SnapshotRepository(service_client()).get(snapshot_id)
    if row["status"] != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="snapshot is not a draft")
    service._drafts[snapshot_id] = _draft_from_db(row)  # noqa: SLF001
    result = service.compute(snapshot_id)
    return ComputeSummaryOut(**result.__dict__)


@router.get("/snapshots", response_model=list[SnapshotOut])
def list_snapshots(
    user: CurrentUser = Depends(_require_internal),
) -> list[SnapshotOut]:
    service = _snapshot_service()
    rows = service.list()
    return [SnapshotOut(**r) for r in rows]


@router.get("/snapshots/{snapshot_id}/diff", response_model=DiffOut)
def diff_snapshot(
    snapshot_id: UUID,
    user: CurrentUser = Depends(_require_internal),
) -> DiffOut:
    service = _snapshot_service()
    d = service.diff_against_latest_published(snapshot_id)
    return DiffOut(
        snapshot_id=d["snapshot_id"],
        previous_snapshot_id=d["previous_snapshot_id"],
        rows=[DiffRowOut(**r) for r in d["rows"]],
    )


@router.post("/snapshots/{snapshot_id}/publish", response_model=SnapshotOut)
def publish_snapshot(
    snapshot_id: UUID,
    req: PublishRequest,
    user: CurrentUser = Depends(_require_internal),
) -> SnapshotOut:
    service = _snapshot_service()
    row = service.publish(snapshot_id, published_by=user.user_id, notes=req.notes)
    return SnapshotOut(**row)


@router.post("/snapshots/{snapshot_id}/archive", response_model=SnapshotOut)
def archive_snapshot(
    snapshot_id: UUID,
    user: CurrentUser = Depends(_require_internal),
) -> SnapshotOut:
    service = _snapshot_service()
    row = service.archive(snapshot_id)
    return SnapshotOut(**row)
