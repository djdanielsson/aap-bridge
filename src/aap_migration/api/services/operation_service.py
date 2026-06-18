import asyncio
import contextvars
import logging
import re
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from aap_migration.api.models import Connection, Job
from aap_migration.api.services.cli_workflows import run_connection_cleanup, run_connection_export
from aap_migration.api.services.job_service import JobService

ACTIVE_JOB_ID: contextvars.ContextVar[str] = contextvars.ContextVar(
    "operation_service_active_job_id",
    default="",
)


class JobContextFilter(logging.Filter):
    def __init__(self, job_id: str) -> None:
        super().__init__()
        self.job_id = job_id

    def filter(self, record: logging.LogRecord) -> bool:
        return ACTIVE_JOB_ID.get() == self.job_id


class JobLogHandler(logging.Handler):
    def __init__(self, job_service: JobService, job_id: str) -> None:
        super().__init__()
        self.job_service = job_service
        self.job_id = job_id

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        self.job_service.append_log(self.job_id, msg)


class OperationService:
    def __init__(
        self,
        job_service: JobService,
        session_factory: sessionmaker[Session],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self.job_service = job_service
        self.session_factory = session_factory
        self.loop = loop

    def _get_db_url(self) -> str:
        import os

        return os.environ.get("MIGRATION_STATE_DB_PATH", "sqlite:///aap_bridge.db")

    def _create_job(self, job_type: str, connection_id: str) -> str:
        job_id = str(uuid4())
        db = self.session_factory()
        try:
            job = Job(id=job_id, type=job_type, connection_id=connection_id, status="running")
            db.add(job)
            db.commit()
        finally:
            db.close()
        self.job_service.register_job(job_id)
        return job_id

    def _finish_job(self, job_id: str, status: str, error: str | None = None) -> None:
        db = self.session_factory()
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                job.status = status
                job.finished_at = datetime.now(UTC)
                job.error = error
                logs = self.job_service.get_logs_since(job_id, 0)
                job.output = logs
                db.commit()
        finally:
            db.close()

    @staticmethod
    def _job_logger() -> logging.Logger:
        return logging.getLogger("aap_migration")

    def _attach_log_handler(self, job_id: str) -> JobLogHandler:
        handler = JobLogHandler(self.job_service, job_id)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.addFilter(JobContextFilter(job_id))
        self._job_logger().addHandler(handler)
        return handler

    def _detach_log_handler(self, handler: JobLogHandler) -> None:
        self._job_logger().removeHandler(handler)

    def _snapshot_connection(self, conn: Connection) -> dict:
        return {
            "id": conn.id,
            "name": conn.name,
            "url": conn.url,
            "token": conn.token,
            "verify_ssl": conn.verify_ssl,
            "type": conn.type,
            "role": conn.role,
            "api_prefix": conn.api_prefix,
            "version": conn.version,
            "ping_status": conn.ping_status,
        }

    def _connection_from_snapshot(self, snap: dict) -> Connection:
        conn_model = Connection()
        for key, value in snap.items():
            setattr(conn_model, key, value)
        return conn_model

    def start_cleanup(self, conn: Connection) -> str:
        job_id = self._create_job("cleanup", conn.id)
        snap = self._snapshot_connection(conn)
        db_url = self._get_db_url()

        async def _run() -> None:
            handler = self._attach_log_handler(job_id)
            context_token = ACTIVE_JOB_ID.set(job_id)
            try:
                conn_model = self._connection_from_snapshot(snap)
                self.job_service.append_log(
                    job_id, f"Starting cleanup on {snap['name']} ({snap['url']})"
                )
                result = await run_connection_cleanup(
                    conn_model,
                    db_url,
                    log=lambda message: self.job_service.append_log(job_id, message),
                )
                self.job_service.append_log(
                    job_id,
                    "Cleanup complete: "
                    f"deleted={result.deleted} skipped={result.skipped} errors={result.errors}; "
                    f"database cleared ({result.cleared_progress} progress, "
                    f"{result.deleted_mappings} mappings)"
                    + (
                        f"; removed directories: {', '.join(result.directories_removed)}"
                        if result.directories_removed
                        else ""
                    ),
                )
                if result.errors:
                    error_msg = f"Cleanup completed with {result.errors} errors"
                    self.job_service.append_log(job_id, error_msg)
                    self.job_service.mark_failed(job_id, error_msg)
                    self._finish_job(job_id, "failed", error_msg)
                else:
                    self.job_service.mark_completed(job_id)
                    self._finish_job(job_id, "completed")
            except asyncio.CancelledError:
                self.job_service.append_log(job_id, "Cleanup cancelled")
                self.job_service.mark_cancelled(job_id)
                self._finish_job(job_id, "cancelled")
            except Exception as e:
                self.job_service.append_log(job_id, f"Cleanup failed: {e}")
                self.job_service.mark_failed(job_id, str(e))
                self._finish_job(job_id, "failed", str(e))
            finally:
                ACTIVE_JOB_ID.reset(context_token)
                self._detach_log_handler(handler)

        task = asyncio.run_coroutine_threadsafe(_run(), self.loop)
        self.job_service.register_task(job_id, task)
        return job_id

    def start_export(self, conn: Connection) -> str:
        job_id = self._create_job("export", conn.id)
        snap = self._snapshot_connection(conn)

        async def _run() -> None:
            handler = self._attach_log_handler(job_id)
            context_token = ACTIVE_JOB_ID.set(job_id)
            try:
                from pathlib import Path

                conn_model = self._connection_from_snapshot(snap)
                self.job_service.append_log(
                    job_id, f"Starting export from {snap['name']} ({snap['url']})"
                )

                safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", snap["name"]).strip("._")
                if not safe_name:
                    safe_name = snap["id"]
                export_dir = Path("./exports") / f"{safe_name}-{snap['id'][:8]}-{job_id[:8]}"

                result = await run_connection_export(
                    conn_model,
                    self._get_db_url(),
                    export_dir,
                    log=lambda message: self.job_service.append_log(job_id, message),
                )
                self.job_service.append_log(
                    job_id,
                    f"Export complete: {result.total_resources} resources "
                    f"across {result.resource_types} types in {result.output_dir}",
                )
                if result.errors:
                    error_msg = f"Export completed with {result.errors} resource-type errors"
                    self.job_service.append_log(job_id, error_msg)
                    self.job_service.mark_failed(job_id, error_msg)
                    self._finish_job(job_id, "failed", error_msg)
                else:
                    self.job_service.mark_completed(job_id)
                    self._finish_job(job_id, "completed")
            except asyncio.CancelledError:
                self.job_service.append_log(job_id, "Export cancelled")
                self.job_service.mark_cancelled(job_id)
                self._finish_job(job_id, "cancelled")
            except Exception as e:
                self.job_service.append_log(job_id, f"Export failed: {e}")
                self.job_service.mark_failed(job_id, str(e))
                self._finish_job(job_id, "failed", str(e))
            finally:
                ACTIVE_JOB_ID.reset(context_token)
                self._detach_log_handler(handler)

        task = asyncio.run_coroutine_threadsafe(_run(), self.loop)
        self.job_service.register_task(job_id, task)
        return job_id
