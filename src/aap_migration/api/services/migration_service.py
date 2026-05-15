import asyncio
import logging
import re
import time
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from aap_migration.api.models import Connection, Job
from aap_migration.api.schemas import MigrationPreviewResponse
from aap_migration.api.services.job_service import JobService
from aap_migration.migration.coordinator import MigrationCoordinator


def _build_resource_type_to_phase_map() -> dict[str, str]:
    """Build a reverse map from resource_type -> phase name for MIGRATION_PHASES."""
    mapping: dict[str, str] = {}
    for phase in MigrationCoordinator.MIGRATION_PHASES:
        for rt in phase["resource_types"]:
            mapping[rt] = phase["name"]
    return mapping


def _build_preview_resource_types() -> list[str]:
    """Derive previewable resource types from coordinator phases."""
    types: list[str] = []
    for phase in MigrationCoordinator.MIGRATION_PHASES:
        types.extend(phase["resource_types"])
    return types


_RESOURCE_TYPE_TO_PHASE = _build_resource_type_to_phase_map()
PREVIEW_RESOURCE_TYPES = _build_preview_resource_types()


_NEXT_KEY_RE = re.compile(r"\s+[a-z_][a-z0-9_]*=")


class JobLogHandler(logging.Handler):
    def __init__(self, job_service: JobService, job_id: str) -> None:
        super().__init__()
        self.job_service = job_service
        self.job_id = job_id
        self._phase_desc = ""
        self._exported = 0
        self._created = 0
        self._skipped = 0
        self._failed = 0
        self._phase_start = 0.0
        self._last_emitted = 0
        self._total_created = 0
        self._total_skipped = 0
        self._total_failed = 0
        self._phase_num = 0
        self._total_phases = 0
        self._phase_finished = False
        self._phase_warnings: dict[str, int] = {}
        self._phase_warning_samples: dict[str, list[str]] = {}

    def _log(self, msg: str) -> None:
        self.job_service.append_log(self.job_id, msg)

    def _emit_event(self, data: dict) -> None:
        self.job_service.append_event(self.job_id, data)

    def _rate(self) -> str:
        elapsed = time.time() - self._phase_start if self._phase_start else 0
        total = self._created + self._skipped + self._failed
        if elapsed > 0 and total > 0:
            return f"{total / elapsed:.1f}/s"
        return "--/s"

    def _elapsed(self) -> str:
        elapsed = time.time() - self._phase_start if self._phase_start else 0
        if elapsed < 60:
            return f"{elapsed:.0f}s"
        return f"{int(elapsed // 60)}m{int(elapsed % 60)}s"

    def _emit_progress_event(self) -> None:
        """Emit a structured progress event for the Output tab (no text log line)."""
        self._emit_event(
            {
                "_event": "phase_progress",
                "phase_num": self._phase_num,
                "exported": self._exported,
                "created": self._created,
                "skipped": self._skipped,
                "failed": self._failed,
                "rate": self._rate(),
                "elapsed": self._elapsed(),
            }
        )

    def _track_warning(self, warning_type: str, msg: str) -> None:
        self._phase_warnings[warning_type] = self._phase_warnings.get(warning_type, 0) + 1
        samples = self._phase_warning_samples.setdefault(warning_type, [])
        if len(samples) < 5:
            name = self._extract("source_name=", msg) or self._extract("name=", msg)
            if name:
                samples.append(name)

    def _finish_phase(self) -> None:
        if self._phase_finished:
            return
        total = self._created + self._skipped + self._failed
        if total == 0 and self._exported == 0:
            return
        self._phase_finished = True
        self._total_created += self._created
        self._total_skipped += self._skipped
        self._total_failed += self._failed
        for warn_type, count in self._phase_warnings.items():
            label = warn_type.replace("_", " ")
            self._log(f"  ⚠ {count} {label}")
        status = "✓" if self._failed == 0 else "⚠"
        self._log(
            f"  {status} Done: {self._created} created, "
            f"{self._skipped} skipped, {self._failed} failed "
            f"({self._elapsed()})"
        )
        self._emit_event(
            {
                "_event": "phase_complete",
                "phase_num": self._phase_num,
                "description": self._phase_desc,
                "created": self._created,
                "skipped": self._skipped,
                "failed": self._failed,
                "exported": self._exported,
                "duration": self._elapsed(),
                "warnings": dict(self._phase_warnings),
                "warning_samples": dict(self._phase_warning_samples),
            }
        )

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)

        # --- Phase lifecycle ---
        if "migration_started" in msg:
            self._total_phases = int(self._extract("total_phases=", msg) or "0")
            self._log(f"Migration started ({self._total_phases} phases)")
            self._emit_event(
                {
                    "_event": "migration_start",
                    "total_phases": self._total_phases,
                }
            )
            return

        if "phase_starting" in msg:
            self._finish_phase()
            self._phase_num += 1
            desc = self._extract("description=", msg)
            self._phase_desc = desc or "unknown"
            rt = self._extract("resource_types=", msg)
            self._exported = 0
            self._created = 0
            self._skipped = 0
            self._failed = 0
            self._last_emitted = 0
            self._phase_start = time.time()
            self._phase_finished = False
            self._phase_warnings = {}
            self._phase_warning_samples = {}
            self._log(f"\n[{self._phase_num}/{self._total_phases}] {self._phase_desc}")
            self._emit_event(
                {
                    "_event": "phase_start",
                    "phase_num": self._phase_num,
                    "total_phases": self._total_phases,
                    "description": self._phase_desc,
                    "resource_type": rt,
                }
            )
            return

        if "phase_completed" in msg:
            self._emit_progress_event()
            self._finish_phase()
            return

        if "phase_failed" in msg:
            self._emit_progress_event()
            self._finish_phase()
            return

        if "migration_completed" in msg or "migration_failed" in msg:
            self._log(
                f"\nMigration complete: "
                f"{self._total_created} created, "
                f"{self._total_skipped} skipped, "
                f"{self._total_failed} failed"
            )
            self._emit_event(
                {
                    "_event": "migration_complete",
                    "total_created": self._total_created,
                    "total_skipped": self._total_skipped,
                    "total_failed": self._total_failed,
                }
            )
            return

        # --- Export counts ---
        if "export_completed" in msg:
            exported_str = self._extract("total_exported=", msg)
            if exported_str:
                self._exported = int(exported_str)
                if self._exported > 0:
                    self._log(f"  Exported {self._exported} resources")
            return

        # --- Per-resource verbose logging ---
        if "resource_import_failed" in msg:
            self._failed += 1
            name = self._extract("source_name=", msg) or self._extract("source_id=", msg)
            rt = self._extract("resource_type=", msg)
            err = self._extract("error=", msg)[:80] if "error=" in msg else ""
            self._log(f"  ✗ Failed: {name} — {err}")
            self._emit_event(
                {
                    "_event": "resource_result",
                    "phase_num": self._phase_num,
                    "name": name,
                    "resource_type": rt,
                    "result": "failed",
                    "detail": err,
                }
            )
            self._emit_progress_event()
            return

        if "resources_skipped_summary" in msg:
            return

        if "resource_skipped" in msg or "resource_skipped_exists" in msg:
            name = self._extract("source_name=", msg) or self._extract("name=", msg)
            rt = self._extract("resource_type=", msg)
            reason = self._extract("reason=", msg)
            self._skipped += 1
            self._log(f"  → Skipped: {name or 'unknown'}{' — ' + reason if reason else ''}")
            self._emit_event(
                {
                    "_event": "resource_result",
                    "phase_num": self._phase_num,
                    "name": name or "unknown",
                    "resource_type": rt,
                    "result": "skipped",
                    "detail": reason or "",
                }
            )
            self._emit_progress_event()
            return

        if "resource_created" in msg:
            self._created += 1
            name = self._extract("source_name=", msg) or self._extract("name=", msg)
            rt = self._extract("resource_type=", msg)
            self._log(f"  ✓ Created: {name or 'unknown'}")
            self._emit_event(
                {
                    "_event": "resource_result",
                    "phase_num": self._phase_num,
                    "name": name or "unknown",
                    "resource_type": rt,
                    "result": "created",
                    "detail": "",
                }
            )
            self._emit_progress_event()
            return

        if "resource_already_exists" in msg:
            self._track_warning("already_exists", msg)
            self._skipped += 1
            name = self._extract("source_name=", msg) or self._extract("name=", msg)
            rt = self._extract("resource_type=", msg)
            self._log(f"  → Exists: {name or 'unknown'}")
            self._emit_event(
                {
                    "_event": "resource_result",
                    "phase_num": self._phase_num,
                    "name": name or "unknown",
                    "resource_type": rt,
                    "result": "exists",
                    "detail": "",
                }
            )
            self._emit_progress_event()
            return

        if "credential_duplicate_renamed" in msg:
            self._track_warning("credential_renamed", msg)
            return

        # --- Suppress noisy events ---
        noisy = (
            "api_request",
            "Marked resource",
            "_creating",
            "_created",
            "credential_creating",
            "credential_created",
            "resource_creating",
            "resource_imported",
            "resource_conflict",
            "precheck_batch_complete",
            "transforming_resource",
        )
        for n in noisy:
            if n in msg:
                return

        # --- Capture pipeline errors as structured events ---
        if "etl_pipeline_failed" in msg:
            error_msg = self._extract("error=", msg)
            if len(error_msg) > 120:
                error_msg = error_msg[:120] + "..."
            self._log(f"  ✗ Error: {error_msg}")
            self._emit_event(
                {
                    "_event": "phase_error",
                    "phase_num": self._phase_num,
                    "error": error_msg,
                }
            )
            return

        if "resource_type_failed" in msg:
            return

        # --- Show remaining warnings/errors ---
        if record.levelno >= logging.WARNING:
            clean = msg.split("version=")[0].strip() if "version=" in msg else msg
            if len(clean) > 200:
                clean = clean[:200] + "..."
            self._log(f"  ⚠ {clean}")

    @staticmethod
    def _extract(prefix: str, msg: str) -> str:
        if prefix not in msg:
            return ""
        start = msg.index(prefix) + len(prefix)
        rest = msg[start:]
        m = _NEXT_KEY_RE.search(rest)
        if m:
            return rest[: m.start()].strip()
        return rest.strip()


class MigrationService:
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

    def _create_job(self, job_type: str, connection_id: str | None = None) -> str:
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

    def _finish_job(
        self, job_id: str, status: str, error: str | None = None, metadata: dict | None = None
    ) -> None:
        db = self.session_factory()
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                job.status = status
                job.finished_at = datetime.now(UTC)
                job.error = error
                merged = dict(metadata) if metadata else {}
                events = self.job_service.get_events_since(job_id, 0)
                if events:
                    merged["events"] = events
                if merged:
                    job.job_metadata = merged
                logs = self.job_service.get_logs_since(job_id, 0)
                job.output = logs
                db.commit()
        finally:
            db.close()

    def _attach_log_handler(self, job_id: str) -> JobLogHandler:
        handler = JobLogHandler(self.job_service, job_id)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter("%(message)s"))
        root = logging.getLogger()
        root.addHandler(handler)
        return handler

    def _detach_log_handler(self, handler: JobLogHandler) -> None:
        root = logging.getLogger()
        root.removeHandler(handler)

    def _snapshot_connection(self, conn: Connection) -> dict:
        from aap_migration.api.crypto import decrypt_token

        return {
            "id": conn.id,
            "name": conn.name,
            "url": conn.url,
            "token": decrypt_token(conn.token) if conn.token else None,
            "verify_ssl": conn.verify_ssl,
            "type": conn.type,
            "api_prefix": conn.api_prefix,
        }

    def start_preview(self, source: Connection, dest: Connection) -> str:
        job_id = self._create_job("migration-preview", source.id)
        src_snap = self._snapshot_connection(source)
        dst_snap = self._snapshot_connection(dest)

        async def _run() -> None:
            handler = self._attach_log_handler(job_id)
            try:
                from aap_migration.api.models import Connection as ConnModel
                from aap_migration.api.services.platform_adapter import PlatformAdapter

                src_conn = ConnModel()
                for k, v in src_snap.items():
                    setattr(src_conn, k, v)
                dst_conn = ConnModel()
                for k, v in dst_snap.items():
                    setattr(dst_conn, k, v)

                src_adapter = PlatformAdapter(src_conn)
                dst_adapter = PlatformAdapter(dst_conn)

                self.job_service.append_log(
                    job_id, f"Starting migration preview: {src_snap['name']} -> {dst_snap['name']}"
                )

                resources: dict[str, list[dict]] = {}
                host_counts: dict[str, int] = {}
                group_counts: dict[str, int] = {}
                warnings: list[str] = []

                for rt in PREVIEW_RESOURCE_TYPES:
                    self.job_service.append_log(job_id, f"Fetching {rt} from source...")
                    src_items = await asyncio.to_thread(src_adapter.fetch_all, rt)
                    if not src_items:
                        continue

                    self.job_service.append_log(job_id, f"  Found {len(src_items)} {rt} on source")
                    self.job_service.append_log(job_id, f"Fetching {rt} from destination...")
                    dst_items = await asyncio.to_thread(dst_adapter.fetch_all, rt)
                    dst_names = {item.get("name", "") for item in dst_items}
                    self.job_service.append_log(
                        job_id, f"  Found {len(dst_items)} {rt} on destination"
                    )

                    type_resources = []
                    for item in src_items:
                        name = item.get("name", item.get("username", f"id-{item.get('id', '?')}"))
                        action = "skip_exists" if name in dst_names else "create"
                        type_resources.append(
                            {
                                "source_id": item.get("id", 0),
                                "name": name,
                                "type": rt,
                                "action": action,
                            }
                        )

                    if type_resources:
                        resources[rt] = type_resources

                    if rt == "inventories":
                        for item in src_items:
                            inv_name = item.get("name", "")
                            host_counts[inv_name] = item.get("total_hosts", 0)
                            group_counts[inv_name] = item.get("total_groups", 0)

                total_create = sum(
                    1 for items in resources.values() for i in items if i["action"] == "create"
                )
                total_skip = sum(
                    1 for items in resources.values() for i in items if i["action"] != "create"
                )
                self.job_service.append_log(
                    job_id, f"Preview complete: {total_create} to create, {total_skip} to skip"
                )

                preview_data = {
                    "source_id": src_snap["id"],
                    "destination_id": dst_snap["id"],
                    "resources": resources,
                    "warnings": warnings,
                    "host_counts": host_counts,
                    "group_counts": group_counts,
                }
                self.job_service.mark_completed(job_id)
                self._finish_job(job_id, "completed", metadata=preview_data)
            except asyncio.CancelledError:
                self.job_service.mark_failed(job_id, "Cancelled")
                self._finish_job(job_id, "cancelled")
            except Exception as e:
                self.job_service.append_log(job_id, f"ERROR: {e}")
                self.job_service.mark_failed(job_id, str(e))
                self._finish_job(job_id, "failed", str(e))
            finally:
                self._detach_log_handler(handler)

        task = self.loop.create_task(_run())
        self.job_service.register_task(job_id, task)
        return job_id

    def get_preview(self, job_id: str) -> tuple[str, MigrationPreviewResponse | None]:
        db = self.session_factory()
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            if not job:
                return ("not_found", None)
            if not job.job_metadata:
                return (job.status, None)
            return (job.status, MigrationPreviewResponse(**job.job_metadata))
        finally:
            db.close()

    def start_run(
        self,
        source: Connection,
        dest: Connection,
        preview_job_id: str,
        exclusions: dict | None = None,
        dry_run: bool = False,
        force_reimport: bool = False,
        export_overrides: dict | None = None,
    ) -> str:
        job_id = self._create_job("migration-run", source.id)
        src_snap = self._snapshot_connection(source)
        dst_snap = self._snapshot_connection(dest)
        db_url = self._get_db_url()

        async def _run() -> None:
            handler = self._attach_log_handler(job_id)
            try:
                from aap_migration.api.services.engine_adapter import build_migration_config
                from aap_migration.client.aap_source_client import AAPSourceClient
                from aap_migration.client.aap_target_client import AAPTargetClient
                from aap_migration.migration.coordinator import MigrationCoordinator
                from aap_migration.migration.state import MigrationState

                self.job_service.append_log(
                    job_id, f"Starting migration: {src_snap['name']} -> {dst_snap['name']}"
                )

                src_conn = Connection()
                for k, v in src_snap.items():
                    setattr(src_conn, k, v)
                dst_conn = Connection()
                for k, v in dst_snap.items():
                    setattr(dst_conn, k, v)

                config = build_migration_config(
                    src_conn,
                    dst_conn,
                    db_url,
                    dry_run=dry_run,
                    export_overrides=export_overrides,
                )

                self.job_service.append_log(job_id, "Initializing clients...")
                source_client = AAPSourceClient(config.source)
                target_client = AAPTargetClient(config.target)

                # Validate version compatibility before proceeding
                from aap_migration.resources import get_version_path

                try:
                    src_version = await source_client.get_version()
                    tgt_version = await target_client.get_version()
                    self.job_service.append_log(
                        job_id, f"Source version: {src_version}, Target version: {tgt_version}"
                    )
                    vpath = get_version_path(src_version, tgt_version)
                    if vpath is None:
                        raise ValueError(
                            f"Unsupported migration path: {src_version} → {tgt_version}"
                        )
                    if vpath.status == "partial":
                        self.job_service.append_log(job_id, f"⚠ Partial support: {vpath.notes}")
                except ValueError:
                    raise
                except Exception as e:
                    self.job_service.append_log(
                        job_id,
                        f"⚠ Version detection failed ({e}), proceeding anyway",
                    )

                self.job_service.append_log(job_id, "Initializing migration state...")
                state = MigrationState(config.state)

                if force_reimport:
                    cleared = state.clear_progress()
                    self.job_service.append_log(
                        job_id,
                        f"Force reimport: cleared {cleared} progress records",
                    )

                coordinator = MigrationCoordinator(
                    config=config,
                    source_client=source_client,
                    target_client=target_client,
                    state=state,
                    enable_progress=False,
                    show_stats=False,
                )

                # Apply exclusions: mark excluded resources as skipped and
                # determine if any full resource types should be skipped entirely
                skip_phases: list[str] = []
                if exclusions:
                    # Get the preview data to know total counts per type
                    preview_job = None
                    db = self.session_factory()
                    try:
                        from aap_migration.api.models import Job

                        preview_job = db.query(Job).filter(Job.id == preview_job_id).first()
                    finally:
                        db.close()

                    preview_resources = {}
                    if preview_job and preview_job.job_metadata:
                        preview_resources = preview_job.job_metadata.get("resources", {})

                    for resource_type, excluded_ids in exclusions.items():
                        if not excluded_ids:
                            continue

                        # Check if ALL resources of this type are excluded
                        type_resources = preview_resources.get(resource_type, [])
                        all_ids = (
                            {r.get("source_id") for r in type_resources}
                            if type_resources
                            else set()
                        )

                        if all_ids and set(excluded_ids) >= all_ids:
                            phase_name = _RESOURCE_TYPE_TO_PHASE.get(resource_type, resource_type)
                            if phase_name not in skip_phases:
                                skip_phases.append(phase_name)
                            self.job_service.append_log(
                                job_id,
                                f"Skipping entire phase: {phase_name} (all {resource_type} excluded)",
                            )
                        else:
                            # Mark individual resources as skipped in state
                            for source_id in excluded_ids:
                                try:
                                    state.create_source_mapping(
                                        resource_type,
                                        source_id,
                                        source_name=f"excluded-{source_id}",
                                    )
                                    state.mark_skipped(
                                        resource_type,
                                        source_id,
                                        "Excluded by user in migration preview",
                                    )
                                except Exception:
                                    pass
                            self.job_service.append_log(
                                job_id,
                                f"Excluded {len(excluded_ids)} {resource_type} resource(s) from migration",
                            )

                self.job_service.append_log(job_id, "Running migration...")
                summary = await coordinator.migrate_all(
                    skip_phases=skip_phases if skip_phases else None,
                    generate_report=True,
                    report_dir="./reports",
                )

                status_msg = summary.get("status", "unknown")
                exported = summary.get("total_resources_exported", 0)
                imported = summary.get("total_resources_imported", 0)
                failed = summary.get("total_resources_failed", 0)
                skipped = summary.get("total_resources_skipped", 0)

                self.job_service.append_log(
                    job_id,
                    f"Migration {status_msg}: exported={exported} imported={imported} "
                    f"failed={failed} skipped={skipped}",
                )

                self.job_service.mark_completed(job_id)
                self._finish_job(job_id, "completed", metadata=summary)
            except asyncio.CancelledError:
                self.job_service.append_log(job_id, "Migration cancelled")
                self.job_service.mark_failed(job_id, "Cancelled")
                self._finish_job(job_id, "cancelled")
            except Exception as e:
                self.job_service.append_log(job_id, f"Migration failed: {e}")
                self.job_service.mark_failed(job_id, str(e))
                self._finish_job(job_id, "failed", str(e))
            finally:
                self._detach_log_handler(handler)

        task = self.loop.create_task(_run())
        self.job_service.register_task(job_id, task)
        return job_id

    def start_resume(
        self,
        source: Connection,
        dest: Connection,
        checkpoint_id: int,
    ) -> str:
        """Resume a migration from a checkpoint."""
        job_id = self._create_job("migration-run", source.id)
        src_snap = self._snapshot_connection(source)
        dst_snap = self._snapshot_connection(dest)
        db_url = self._get_db_url()

        async def _run() -> None:
            handler = self._attach_log_handler(job_id)
            try:
                from aap_migration.api.services.engine_adapter import build_migration_config
                from aap_migration.client.aap_source_client import AAPSourceClient
                from aap_migration.client.aap_target_client import AAPTargetClient
                from aap_migration.migration.coordinator import MigrationCoordinator
                from aap_migration.migration.state import MigrationState

                self.job_service.append_log(
                    job_id,
                    f"Resuming migration from checkpoint {checkpoint_id}: "
                    f"{src_snap['name']} -> {dst_snap['name']}",
                )

                src_conn = Connection()
                for k, v in src_snap.items():
                    setattr(src_conn, k, v)
                dst_conn = Connection()
                for k, v in dst_snap.items():
                    setattr(dst_conn, k, v)

                config = build_migration_config(src_conn, dst_conn, db_url)

                source_client = AAPSourceClient(config.source)
                target_client = AAPTargetClient(config.target)
                state = MigrationState(config.state)

                coordinator = MigrationCoordinator(
                    config=config,
                    source_client=source_client,
                    target_client=target_client,
                    state=state,
                    enable_progress=False,
                    show_stats=False,
                )

                self.job_service.append_log(job_id, "Resuming from checkpoint...")
                summary = await coordinator.resume_from_checkpoint(checkpoint_id)

                status_msg = summary.get("status", "unknown")
                imported = summary.get("total_resources_imported", 0)
                failed = summary.get("total_resources_failed", 0)
                skipped = summary.get("total_resources_skipped", 0)

                self.job_service.append_log(
                    job_id,
                    f"Migration resumed {status_msg}: imported={imported} "
                    f"failed={failed} skipped={skipped}",
                )

                self.job_service.mark_completed(job_id)
                self._finish_job(job_id, "completed", metadata=summary)
            except asyncio.CancelledError:
                self.job_service.append_log(job_id, "Migration cancelled")
                self.job_service.mark_failed(job_id, "Cancelled")
                self._finish_job(job_id, "cancelled")
            except Exception as e:
                self.job_service.append_log(job_id, f"Resume failed: {e}")
                self.job_service.mark_failed(job_id, str(e))
                self._finish_job(job_id, "failed", str(e))
            finally:
                self._detach_log_handler(handler)

        task = self.loop.create_task(_run())
        self.job_service.register_task(job_id, task)
        return job_id

    def list_checkpoints(self, source: Connection, dest: Connection) -> list[dict]:
        """List available checkpoints for the given connection pair."""
        db_url = self._get_db_url()

        from aap_migration.api.services.engine_adapter import build_migration_config
        from aap_migration.migration.checkpoint import CheckpointManager
        from aap_migration.migration.state import MigrationState

        src_conn = Connection()
        for k, v in self._snapshot_connection(source).items():
            setattr(src_conn, k, v)
        dst_conn = Connection()
        for k, v in self._snapshot_connection(dest).items():
            setattr(dst_conn, k, v)

        config = build_migration_config(src_conn, dst_conn, db_url)
        state = MigrationState(config.state)
        checkpoint_mgr = CheckpointManager(state)
        return checkpoint_mgr.list_checkpoints(limit=20)

    def start_credential_comparison(
        self,
        source: Connection,
        dest: Connection,
    ) -> str:
        """Start an async credential comparison job."""
        job_id = self._create_job("credential-comparison", source.id)
        src_snap = self._snapshot_connection(source)
        dst_snap = self._snapshot_connection(dest)
        db_url = self._get_db_url()

        async def _run() -> None:
            handler = self._attach_log_handler(job_id)
            try:
                from aap_migration.api.services.engine_adapter import build_migration_config
                from aap_migration.client.aap_source_client import AAPSourceClient
                from aap_migration.client.aap_target_client import AAPTargetClient
                from aap_migration.migration.coordinator import MigrationCoordinator
                from aap_migration.migration.state import MigrationState

                self.job_service.append_log(
                    job_id,
                    f"Comparing credentials: {src_snap['name']} vs {dst_snap['name']}",
                )

                src_conn = Connection()
                for k, v in src_snap.items():
                    setattr(src_conn, k, v)
                dst_conn = Connection()
                for k, v in dst_snap.items():
                    setattr(dst_conn, k, v)

                config = build_migration_config(src_conn, dst_conn, db_url)
                source_client = AAPSourceClient(config.source)
                target_client = AAPTargetClient(config.target)
                state = MigrationState(config.state)

                coordinator = MigrationCoordinator(
                    config=config,
                    source_client=source_client,
                    target_client=target_client,
                    state=state,
                    enable_progress=False,
                )

                summary = await coordinator.compare_and_verify_credentials(
                    report_path="./reports/credential_comparison.md"
                )

                self.job_service.append_log(
                    job_id,
                    f"Comparison complete: {summary.get('matching_count', 0)} matching, "
                    f"{summary.get('missing_count', 0)} missing in target",
                )
                self.job_service.mark_completed(job_id)
                self._finish_job(job_id, "completed", metadata=summary)
            except asyncio.CancelledError:
                self.job_service.mark_failed(job_id, "Cancelled")
                self._finish_job(job_id, "cancelled")
            except Exception as e:
                self.job_service.append_log(job_id, f"Comparison failed: {e}")
                self.job_service.mark_failed(job_id, str(e))
                self._finish_job(job_id, "failed", str(e))
            finally:
                self._detach_log_handler(handler)

        task = self.loop.create_task(_run())
        self.job_service.register_task(job_id, task)
        return job_id
