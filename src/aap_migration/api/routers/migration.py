from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from aap_migration.api.dependencies import get_app_state, get_db
from aap_migration.api.schemas import (
    JobCreatedResponse,
    MigratePreviewRequest,
    MigrateRunRequest,
    PreviewStatusResponse,
)
from aap_migration.api.services.connection_service import ConnectionService

router = APIRouter(tags=["migration"])


@router.post("/migrate/preview", response_model=JobCreatedResponse)
def start_preview(data: MigratePreviewRequest, db: Session = Depends(get_db)) -> JobCreatedResponse:
    svc = ConnectionService(db)
    source = svc.get(data.source_id)
    dest = svc.get(data.destination_id)
    if not source or not dest:
        raise HTTPException(status_code=404, detail="Connection not found")
    state = get_app_state()
    from aap_migration.api.services.migration_service import MigrationService

    mig_svc = MigrationService(state.job_service, state.db_session_factory, state.loop)
    job_id = mig_svc.start_preview(source, dest)
    return JobCreatedResponse(job_id=job_id)


@router.get("/migrate/preview/{job_id}", response_model=PreviewStatusResponse)
def get_preview(job_id: str) -> PreviewStatusResponse:
    state = get_app_state()
    from aap_migration.api.services.migration_service import MigrationService

    mig_svc = MigrationService(state.job_service, state.db_session_factory, state.loop)
    preview = mig_svc.get_preview(job_id)
    if preview is None:
        raise HTTPException(status_code=404, detail="Preview not found")
    if preview.status == "running":
        return JSONResponse(status_code=202, content=preview.model_dump())
    return preview


@router.post("/migrate/run", response_model=JobCreatedResponse)
def run_migration(data: MigrateRunRequest, db: Session = Depends(get_db)) -> JobCreatedResponse:
    svc = ConnectionService(db)
    source = svc.get(data.source_id)
    dest = svc.get(data.destination_id)
    if not source or not dest:
        raise HTTPException(status_code=404, detail="Connection not found")
    state = get_app_state()
    from aap_migration.api.services.migration_service import MigrationService

    mig_svc = MigrationService(state.job_service, state.db_session_factory, state.loop)
    try:
        job_id = mig_svc.start_run(source, dest, data.job_id, data.exclusions)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JobCreatedResponse(job_id=job_id)


@router.post("/migrate/clear-state", status_code=200)
def clear_state() -> dict:
    """Clear migration state (progress records and ID mappings)."""
    from aap_migration.cli.commands.cleanup import clear_database

    db_url = get_app_state().db_url or "sqlite:///aap_bridge.db"
    cleared, deleted = clear_database(db_url)
    return {
        "cleared_progress": cleared,
        "deleted_mappings": deleted,
    }


@router.get("/exclusions")
def get_exclusions() -> dict:
    return {
        "migration": {
            "credential_types": [],
            "execution_environments": [],
            "organizations": [],
        },
        "cleanup": {},
    }
