import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from aap_migration.api.dependencies import get_app_state

router = APIRouter()


@router.websocket("/ws/jobs/{job_id}/logs")
async def stream_logs(websocket: WebSocket, job_id: str) -> None:
    await websocket.accept()
    state = get_app_state()
    offset = 0
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
            await asyncio.sleep(0.2)
    except WebSocketDisconnect:
        pass
