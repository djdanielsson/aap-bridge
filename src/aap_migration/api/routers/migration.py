import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from aap_migration.api.dependencies import get_app_state, get_db
from aap_migration.api.schemas import (
    CheckpointListRequest,
    JobCreatedResponse,
    MigratePreviewRequest,
    MigrateResumeRequest,
    MigrateRunRequest,
    MigrationPreviewResponse,
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


@router.get("/migrate/preview/{job_id}", response_model=MigrationPreviewResponse)
def get_preview(job_id: str) -> MigrationPreviewResponse:
    state = get_app_state()
    from aap_migration.api.services.migration_service import MigrationService

    mig_svc = MigrationService(state.job_service, state.db_session_factory, state.loop)
    status, preview = mig_svc.get_preview(job_id)
    if status == "not_found":
        raise HTTPException(status_code=404, detail="Preview not found")
    if not preview:
        return JSONResponse(status_code=202, content={"status": status})
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
    export_overrides = None
    if data.export_options:
        export_overrides = {
            k: v for k, v in data.export_options.model_dump().items() if v is not None
        }
    job_id = mig_svc.start_run(
        source,
        dest,
        data.job_id,
        data.exclusions,
        dry_run=data.dry_run,
        force_reimport=data.force_reimport,
        export_overrides=export_overrides or None,
    )
    return JobCreatedResponse(job_id=job_id)


@router.post("/migrate/resume", response_model=JobCreatedResponse)
def resume_migration(
    data: MigrateResumeRequest, db: Session = Depends(get_db)
) -> JobCreatedResponse:
    """Resume a migration from a checkpoint."""
    svc = ConnectionService(db)
    source = svc.get(data.source_id)
    dest = svc.get(data.destination_id)
    if not source or not dest:
        raise HTTPException(status_code=404, detail="Connection not found")
    state = get_app_state()
    from aap_migration.api.services.migration_service import MigrationService

    mig_svc = MigrationService(state.job_service, state.db_session_factory, state.loop)
    job_id = mig_svc.start_resume(source, dest, data.checkpoint_id)
    return JobCreatedResponse(job_id=job_id)


@router.post("/migrate/checkpoints")
def list_checkpoints(data: CheckpointListRequest, db: Session = Depends(get_db)) -> list[dict]:
    """List available checkpoints for a connection pair."""
    svc = ConnectionService(db)
    source = svc.get(data.source_id)
    dest = svc.get(data.destination_id)
    if not source or not dest:
        raise HTTPException(status_code=404, detail="Connection not found")
    state = get_app_state()
    from aap_migration.api.services.migration_service import MigrationService

    mig_svc = MigrationService(state.job_service, state.db_session_factory, state.loop)
    return mig_svc.list_checkpoints(source, dest)


@router.post("/migrate/compare-credentials", response_model=JobCreatedResponse)
def compare_credentials(
    data: CheckpointListRequest, db: Session = Depends(get_db)
) -> JobCreatedResponse:
    """Start a credential comparison between source and destination."""
    svc = ConnectionService(db)
    source = svc.get(data.source_id)
    dest = svc.get(data.destination_id)
    if not source or not dest:
        raise HTTPException(status_code=404, detail="Connection not found")
    state = get_app_state()
    from aap_migration.api.services.migration_service import MigrationService

    mig_svc = MigrationService(state.job_service, state.db_session_factory, state.loop)
    job_id = mig_svc.start_credential_comparison(source, dest)
    return JobCreatedResponse(job_id=job_id)


@router.post("/migrate/clear-state", status_code=200)
def clear_state() -> dict:
    """Clear migration state (progress records and ID mappings)."""
    import os

    from aap_migration.cli.commands.cleanup import clear_database

    db_url = os.environ.get("MIGRATION_STATE_DB_PATH", "sqlite:///aap_bridge.db")
    cleared, deleted = clear_database(db_url)
    return {
        "cleared_progress": cleared,
        "deleted_mappings": deleted,
    }


@router.get("/migrate/state")
def get_state_summary() -> dict:
    """Get migration state summary (overall stats, resource counts, mappings count)."""
    db_url = os.environ.get("MIGRATION_STATE_DB_PATH", "sqlite:///aap_bridge.db")

    from aap_migration.config import StateConfig
    from aap_migration.migration.state import MigrationState

    state = MigrationState(StateConfig(db_path=db_url))
    return state.get_overall_stats()


@router.get("/migrate/state/mappings")
def get_state_mappings(resource_type: str | None = None, limit: int = 100) -> list[dict]:
    """Get ID mappings, optionally filtered by resource type."""
    db_url = os.environ.get("MIGRATION_STATE_DB_PATH", "sqlite:///aap_bridge.db")

    from aap_migration.config import StateConfig
    from aap_migration.migration.state import MigrationState

    state = MigrationState(StateConfig(db_path=db_url))
    return state.get_all_mappings(resource_type=resource_type, limit=limit)


@router.post("/migrate/state/reset", status_code=200)
def reset_state(resource_type: str | None = None) -> dict:
    """Reset migration progress (optionally for a specific resource type)."""
    db_url = os.environ.get("MIGRATION_STATE_DB_PATH", "sqlite:///aap_bridge.db")

    from aap_migration.config import StateConfig
    from aap_migration.migration.state import MigrationState

    state = MigrationState(StateConfig(db_path=db_url))
    cleared = state.clear_progress(resource_type=resource_type)
    return {"cleared_progress": cleared, "resource_type": resource_type or "all"}


REPORT_DIR = os.environ.get("MIGRATION_REPORT_DIR", "./reports")


@router.get("/migrate/reports")
def list_reports() -> list[dict]:
    """List available migration reports."""
    report_path = Path(REPORT_DIR)
    if not report_path.is_dir():
        return []
    reports = []
    for f in sorted(report_path.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if f.is_file() and f.suffix in (".json", ".md", ".html"):
            reports.append(
                {
                    "filename": f.name,
                    "format": f.suffix.lstrip("."),
                    "size_bytes": f.stat().st_size,
                    "modified": f.stat().st_mtime,
                }
            )
    return reports


@router.get("/migrate/reports/{filename}")
def download_report(filename: str) -> FileResponse:
    """Download a specific migration report."""
    report_path = Path(REPORT_DIR) / filename
    if not report_path.is_file() or ".." in filename:
        raise HTTPException(status_code=404, detail="Report not found")
    media_types = {
        ".json": "application/json",
        ".md": "text/markdown",
        ".html": "text/html",
    }
    media_type = media_types.get(report_path.suffix, "application/octet-stream")
    return FileResponse(path=str(report_path), media_type=media_type, filename=filename)


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
