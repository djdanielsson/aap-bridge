"""Unit tests for web CLI workflow helpers."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aap_migration.api.models import Connection
from aap_migration.api.services.cli_workflows import (
    run_connection_cleanup,
    run_connection_export,
)


def _connection(**kwargs) -> Connection:
    defaults = {
        "name": "AAP",
        "type": "aap",
        "role": "destination",
        "url": "https://aap.example.com",
        "token": "token",
        "verify_ssl": True,
        "version": "2.6",
    }
    defaults.update(kwargs)
    return Connection(**defaults)


@pytest.mark.asyncio
async def test_run_connection_export_uses_parallel_export_coordinator(tmp_path: Path) -> None:
    conn = _connection(role="source", version="2.5")
    mock_ctx = MagicMock()
    mock_ctx.config.performance.parallel_resource_types = True
    mock_ctx.config.export.records_per_file = 1000
    mock_ctx.source_client.close = AsyncMock()

    coordinator = MagicMock()
    coordinator.export_all_parallel = AsyncMock(
        return_value={
            "organizations": {"exported": 2, "failed": 0},
            "projects": {"exported": 0, "failed": 1},
        }
    )

    with (
        patch(
            "aap_migration.api.services.cli_workflows.build_migration_context",
            return_value=mock_ctx,
        ),
        patch(
            "aap_migration.api.services.cli_workflows._export_resource_types",
            return_value=["organizations", "projects"],
        ),
        patch(
            "aap_migration.api.services.cli_workflows.ParallelExportCoordinator",
            return_value=coordinator,
        ),
    ):
        result = await run_connection_export(conn, "sqlite:///test.db", tmp_path)

    assert result.total_resources == 2
    assert result.resource_types == 1
    assert result.errors == 1
    assert (tmp_path / "metadata.json").exists()
    mock_ctx.source_client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_connection_cleanup_uses_cli_cleanup_helpers() -> None:
    conn = _connection(role="destination")
    mock_ctx = MagicMock()
    mock_ctx.config.performance.rate_limit = 20
    mock_client = AsyncMock()
    mock_client.close = AsyncMock()

    with (
        patch(
            "aap_migration.api.services.cli_workflows.build_migration_context",
            return_value=mock_ctx,
        ),
        patch(
            "aap_migration.api.services.cli_workflows.AAPTargetClient",
            return_value=mock_client,
        ),
        patch(
            "aap_migration.api.services.cli_workflows.cancel_all_jobs",
            new_callable=AsyncMock,
            return_value={"jobs": 1},
        ),
        patch(
            "aap_migration.api.services.cli_workflows.get_cleanup_resource_types",
            new_callable=AsyncMock,
            return_value=["projects", "organizations"],
        ),
        patch(
            "aap_migration.api.services.cli_workflows.delete_resources",
            new_callable=AsyncMock,
            side_effect=[
                (3, 1, 0, []),
                (2, 0, 1, []),
            ],
        ),
    ):
        result = await run_connection_cleanup(conn, "sqlite:///test.db")

    assert result.deleted == 5
    assert result.skipped == 1
    assert result.errors == 1
    assert mock_client.close.await_count == 1
