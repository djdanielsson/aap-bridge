"""CLI-equivalent workflows for web API background jobs."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from aap_migration.api.models import Connection
from aap_migration.api.services.engine_adapter import load_runtime_config
from aap_migration.cli.commands.cleanup import (
    cancel_all_jobs,
    delete_resources,
    get_cleanup_resource_types,
)
from aap_migration.cli.context import MigrationContext
from aap_migration.client.aap_target_client import AAPTargetClient
from aap_migration.migration.parallel_exporter import ParallelExportCoordinator
from aap_migration.cli.commands.migrate import DEFAULT_MIGRATION_EXCLUDED_TYPES
from aap_migration.resources import (
    RESOURCE_REGISTRY,
    get_exportable_types,
    normalize_resource_type,
)

LogFn = Callable[[str], None]


def build_migration_context(conn: Connection, db_url: str) -> MigrationContext:
    """Build a MigrationContext for a single saved connection."""
    ctx = MigrationContext()
    ctx._config = load_runtime_config(conn, conn, db_url)
    return ctx


def _export_resource_types() -> list[str]:
    types_to_export: list[str] = []
    for resource_type in get_exportable_types(use_discovered=True):
        normalized = normalize_resource_type(resource_type)
        if normalized not in DEFAULT_MIGRATION_EXCLUDED_TYPES:
            types_to_export.append(normalized)
    types_to_export.sort(
        key=lambda rt: RESOURCE_REGISTRY[rt].migration_order if rt in RESOURCE_REGISTRY else 999
    )
    return types_to_export


@dataclass
class ExportWorkflowResult:
    output_dir: Path
    total_resources: int
    resource_types: int
    errors: int


@dataclass
class CleanupWorkflowResult:
    deleted: int
    skipped: int
    errors: int


async def run_connection_export(
    conn: Connection,
    db_url: str,
    output_dir: Path,
    *,
    log: LogFn | None = None,
) -> ExportWorkflowResult:
    """Export resources from a connection using the CLI parallel export coordinator."""
    ctx = build_migration_context(conn, db_url)
    output_dir.mkdir(parents=True, exist_ok=True)
    types_to_export = _export_resource_types()

    if log:
        log(f"Exporting {len(types_to_export)} resource types to {output_dir}")

    coordinator = ParallelExportCoordinator(
        source_client=ctx.source_client,
        migration_state=ctx.migration_state,
        performance_config=ctx.config.performance,
        output_dir=output_dir,
        records_per_file=ctx.config.export.records_per_file,
        export_config=ctx.config.export,
    )

    def progress_callback(resource_type: str, stats: dict) -> None:
        if not log:
            return
        exported = stats.get("exported", 0)
        failed = stats.get("failed", 0)
        if exported or failed:
            log(f"  {resource_type}: exported={exported} failed={failed}")

    if ctx.config.performance.parallel_resource_types:
        parallel_results = await coordinator.export_all_parallel(
            resource_types=types_to_export,
            resume=False,
            progress_callback=progress_callback,
        )
    else:
        parallel_results = {}
        for resource_type in types_to_export:
            if log:
                log(f"Exporting {resource_type}...")
            parallel_results[resource_type] = await coordinator.export_resource_type(
                resource_type,
                resume=False,
                progress_callback=progress_callback,
            )

    total_resources = 0
    total_errors = 0
    exported_types = 0
    for resource_type, stats in parallel_results.items():
        exported_count = stats.get("exported", 0)
        failed_count = stats.get("failed", 0)
        total_resources += exported_count
        total_errors += failed_count
        if exported_count > 0:
            exported_types += 1

    metadata = {
        "export_timestamp": datetime.now(UTC).isoformat(),
        "source_url": ctx.config.source.url,
        "source_version": ctx.config.source.version,
        "target_version": ctx.config.target.version,
        "total_resources": total_resources,
        "resource_types": parallel_results,
    }
    with open(output_dir / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2, default=str)

    await ctx.source_client.close()
    return ExportWorkflowResult(
        output_dir=output_dir,
        total_resources=total_resources,
        resource_types=exported_types,
        errors=total_errors,
    )


async def run_connection_cleanup(
    conn: Connection,
    db_url: str,
    *,
    log: LogFn | None = None,
) -> CleanupWorkflowResult:
    """Delete non-default resources from a destination connection.

    Uses the same discovery, job cancellation, and deletion helpers as the CLI
    cleanup command, but does not clear migration database state or local export
    directories.
    """
    ctx = build_migration_context(conn, db_url)
    target_client = AAPTargetClient(
        config=ctx.config.target,
        rate_limit=ctx.config.performance.rate_limit,
    )

    total_deleted = 0
    total_skipped = 0
    total_errors = 0

    try:
        if log:
            log("Cancelling active jobs...")
        cancel_result = await cancel_all_jobs(client=target_client, config=ctx.config)
        if log:
            log(f"Cancelled jobs: {cancel_result}")

        resource_types = await get_cleanup_resource_types(target_client, use_discovered=True)
        if log:
            log(f"Cleaning up {len(resource_types)} resource types...")

        for resource_type in resource_types:
            if log:
                log(f"Cleaning up {resource_type}...")
            try:
                deleted, skipped, errors, _failed = await delete_resources(
                    client=target_client,
                    resource_type=resource_type,
                    config=ctx.config,
                    skip_default=True,
                )
                total_deleted += deleted
                total_skipped += skipped
                total_errors += errors
                if log:
                    log(f"  {resource_type}: deleted={deleted} skipped={skipped} errors={errors}")
            except Exception as exc:
                total_errors += 1
                if log:
                    log(f"  {resource_type}: error - {exc}")

        return CleanupWorkflowResult(
            deleted=total_deleted,
            skipped=total_skipped,
            errors=total_errors,
        )
    finally:
        await target_client.close()
