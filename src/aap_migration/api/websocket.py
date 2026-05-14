import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from aap_migration.api.dependencies import get_app_state

router = APIRouter()


@router.websocket("/ws/jobs/{job_id}/logs")
async def stream_logs(websocket: WebSocket, job_id: str) -> None:
    await websocket.accept()
    state = get_app_state()
    offset = 0
    not_found_count = 0
    try:
        while True:
            lines = state.job_service.get_logs_since(job_id, offset)
            for line in lines:
                await websocket.send_text(line)
                offset += 1
            job = state.job_service.get_job_status(job_id)
            if job and job["status"] in ("completed", "failed", "cancelled") and not lines:
                await websocket.close(code=1000, reason=job["status"])
                return
            if not job:
                not_found_count += 1
                if not_found_count >= 15:
                    from aap_migration.api.models import Job

                    db = state.db_session_factory()
                    try:
                        db_job = db.query(Job).filter(Job.id == job_id).first()
                        if db_job and db_job.status in ("completed", "failed", "cancelled"):
                            for log_line in db_job.output or []:
                                await websocket.send_text(log_line)
                            await websocket.close(code=1000, reason=db_job.status)
                            return
                    finally:
                        db.close()
                    await websocket.close(code=1008, reason="Job not found")
                    return
            else:
                not_found_count = 0
            await asyncio.sleep(0.2)
    except WebSocketDisconnect:
        pass
