import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from aap_migration.api.dependencies import get_app_state
from aap_migration.api.models import Job

router = APIRouter()

EVENT_WS_PREFIX = "\t"


@router.websocket("/ws/jobs/{job_id}/logs")
async def stream_logs(websocket: WebSocket, job_id: str) -> None:
    await websocket.accept()
    state = get_app_state()
    log_offset = 0
    evt_offset = 0
    try:
        while True:
            lines = state.job_service.get_logs_since(job_id, log_offset)
            for line in lines:
                await websocket.send_text(line)
                log_offset += 1

            events = state.job_service.get_events_since(job_id, evt_offset)
            for evt in events:
                await websocket.send_text(EVENT_WS_PREFIX + json.dumps(evt))
                evt_offset += 1

            job = state.job_service.get_job_status(job_id)
            if (
                job
                and job["status"] in ("completed", "failed", "cancelled")
                and not lines
                and not events
            ):
                if log_offset == 0 and evt_offset == 0:
                    await _replay_from_db(websocket, state, job_id, job["status"])
                else:
                    await websocket.close(code=1000, reason=job["status"])
                return
            if not job and log_offset == 0 and evt_offset == 0:
                await _replay_from_db(websocket, state, job_id, None)
                return
            await asyncio.sleep(0.2)
    except WebSocketDisconnect:
        pass


async def _replay_from_db(
    websocket: WebSocket, state: "object", job_id: str, status: str | None
) -> None:
    """Replay persisted output from the database for completed jobs."""
    db = state.db_session_factory()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job and job.output:
            for line in job.output:
                await websocket.send_text(line)
        if job and job.job_metadata and isinstance(job.job_metadata.get("events"), list):
            for evt in job.job_metadata["events"]:
                await websocket.send_text(EVENT_WS_PREFIX + json.dumps(evt))
        reason = (job.status if job else status) or "closed"
        await websocket.close(code=1000, reason=reason)
    finally:
        db.close()
