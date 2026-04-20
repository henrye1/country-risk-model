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
from app.schemas.snapshot import (
    ComputeSummaryOut,
    CreateSnapshotRequest,
    DiffOut,
    DiffRowOut,
    PublishRequest,
    SnapshotOut,
)
from app.services.snapshot import SnapshotService
from fastapi import Response
from app.schemas.model import ModelVersionOut, TrainModelRequest, TrainResultOut
from app.services.training import load_training_rows, train_segment
from app.services.training_diagnostics import generate_csv, generate_xlsx


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


def _require_owner(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Role gate: caller must be an internal_owner (the only role allowed to
    train, approve, activate, or retire models)."""
    client = service_client()
    resp = (
        client.table("memberships")
        .select("role, organisations(status)")
        .eq("user_id", str(user.user_id))
        .limit(1)
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="no membership")
    row = resp.data[0]
    org_status = (row.get("organisations") or {}).get("status")
    if org_status != "internal" or row.get("role") != "internal_owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="internal_owner role required")
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


# --- Model lifecycle ---

@router.post("/model-versions", response_model=TrainResultOut, status_code=status.HTTP_201_CREATED)
def train_model(
    req: TrainModelRequest,
    user: CurrentUser = Depends(_require_owner),
) -> TrainResultOut:
    repo = ModelVersionRepository(service_client())
    try:
        result = train_segment(
            repo=repo,
            segment=req.segment,  # type: ignore[arg-type]
            quant_codes=tuple(req.quant_codes),
            qual_codes=tuple(req.qual_codes),
            notes=req.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return TrainResultOut(
        model_version_id=result.model_version_id,
        segment=result.segment,
        fit_metrics=result.fit_metrics,
        n_training_rows=result.n_training_rows,
    )


@router.get("/model-versions", response_model=list[ModelVersionOut])
def list_models(user: CurrentUser = Depends(_require_internal)) -> list[ModelVersionOut]:
    repo = ModelVersionRepository(service_client())
    return [ModelVersionOut(**r) for r in repo.list()]


@router.get("/model-versions/{model_version_id}", response_model=ModelVersionOut)
def get_model(
    model_version_id: UUID,
    user: CurrentUser = Depends(_require_internal),
) -> ModelVersionOut:
    repo = ModelVersionRepository(service_client())
    row = repo.get(model_version_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="model_version not found")
    return ModelVersionOut(**row)


@router.post("/model-versions/{model_version_id}/approve", response_model=ModelVersionOut)
def approve_model(
    model_version_id: UUID,
    user: CurrentUser = Depends(_require_owner),
) -> ModelVersionOut:
    repo = ModelVersionRepository(service_client())
    try:
        row = repo.set_status(model_version_id, "approved")
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ModelVersionOut(**row)


@router.post("/model-versions/{model_version_id}/activate", response_model=ModelVersionOut)
def activate_model(
    model_version_id: UUID,
    user: CurrentUser = Depends(_require_owner),
) -> ModelVersionOut:
    repo = ModelVersionRepository(service_client())
    try:
        row = repo.set_status(model_version_id, "active")
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ModelVersionOut(**row)


@router.post("/model-versions/{model_version_id}/retire", response_model=ModelVersionOut)
def retire_model(
    model_version_id: UUID,
    user: CurrentUser = Depends(_require_owner),
) -> ModelVersionOut:
    repo = ModelVersionRepository(service_client())
    try:
        row = repo.set_status(model_version_id, "retired")
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ModelVersionOut(**row)


@router.get("/model-versions/{model_version_id}/diagnostics.csv")
def download_diagnostics_csv(
    model_version_id: UUID,
    user: CurrentUser = Depends(_require_internal),
) -> Response:
    repo = ModelVersionRepository(service_client())
    row = repo.get(model_version_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="model_version not found")
    model = repo.load(model_version_id)
    rows = load_training_rows(row["segment"])
    body = generate_csv(model, rows)
    fname = f"diagnostics_{row['segment']}_{model_version_id}.csv"
    return Response(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/model-versions/{model_version_id}/diagnostics.xlsx")
def download_diagnostics_xlsx(
    model_version_id: UUID,
    user: CurrentUser = Depends(_require_internal),
) -> Response:
    repo = ModelVersionRepository(service_client())
    row = repo.get(model_version_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="model_version not found")
    model = repo.load(model_version_id)
    rows = load_training_rows(row["segment"])
    body = generate_xlsx(model, rows)
    fname = f"diagnostics_{row['segment']}_{model_version_id}.xlsx"
    return Response(
        content=body,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
