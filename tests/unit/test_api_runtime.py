"""Focused tests for the web API runtime layer."""

from unittest.mock import MagicMock, patch

import pytest

from aap_migration.api.models import Connection
from aap_migration.api.services.connection_service import ConnectionService
from aap_migration.api.services.job_service import JobService
from aap_migration.api.services.migration_service import MigrationService
from aap_migration.migration.coordinator import MigrationCoordinator


class _StubExporter:
    async def export(self):
        for resource in (
            {"id": 42, "name": "skip me"},
            {"id": 7, "name": "keep me"},
        ):
            yield dict(resource)


def _mock_session_with_job(job: MagicMock) -> MagicMock:
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = job
    return db


def test_connection_service_tests_auth_when_url_includes_api_prefix():
    """A URL that already ends in /api/v2 should still run the auth probe."""
    db = MagicMock()
    service = ConnectionService(db)
    conn = Connection(
        name="Source",
        type="awx",
        role="source",
        url="https://example.com/api/v2",
        token="secret",
        verify_ssl=True,
    )

    ping_response = MagicMock(status_code=200)
    ping_response.json.return_value = {"version": "24.6.1"}
    auth_response = MagicMock(status_code=200)

    with patch(
        "aap_migration.api.services.connection_service.httpx.get",
        side_effect=[ping_response, auth_response],
    ) as mock_get:
        result = service.test_connection(conn)

    assert result.ok is True
    assert conn.auth_status == "ok"
    assert mock_get.call_args_list[1].args[0] == "https://example.com/api/v2/me/"


def test_migration_service_validates_preview_job_connections():
    """Migration runs should only start from a completed matching preview."""
    preview_job = MagicMock(
        type="migration-preview",
        status="completed",
        job_metadata={"source_id": "source-1", "destination_id": "dest-1"},
    )
    db = _mock_session_with_job(preview_job)
    service = MigrationService(MagicMock(), MagicMock(return_value=db), MagicMock())

    metadata = service._validate_preview_job("preview-1", "source-1", "dest-1")
    assert metadata == {"source_id": "source-1", "destination_id": "dest-1"}

    with pytest.raises(ValueError, match="Preview destination does not match"):
        service._validate_preview_job("preview-1", "source-1", "other-dest")


@pytest.mark.asyncio
async def test_migration_coordinator_skips_user_excluded_resources():
    """User exclusions from the preview should skip matching source IDs."""
    config = MagicMock()
    config.source.url = "https://source.example.com/api/v2"
    config.target.url = "https://target.example.com/api/controller/v2"
    config.dry_run = True
    config.performance = MagicMock()
    config.resource_mappings = {}
    config.export.skip_execution_environment_names = []
    config.export.skip_credential_names = []

    transformer = MagicMock()
    transformer.transform_resource.side_effect = lambda **kwargs: dict(kwargs["data"])
    importer = MagicMock(import_errors=[])

    coordinator = MigrationCoordinator(
        config=config,
        source_client=MagicMock(),
        target_client=MagicMock(),
        state=MagicMock(),
        enable_progress=False,
        show_stats=False,
        resource_exclusions={"inventories": {42}},
    )

    with (
        patch("aap_migration.migration.coordinator.create_exporter", return_value=_StubExporter()),
        patch("aap_migration.migration.coordinator.create_transformer", return_value=transformer),
        patch("aap_migration.migration.coordinator.create_importer", return_value=importer),
    ):
        stats = await coordinator._execute_etl_pipeline("inventory", {"name": "inventory"})

    assert stats["exported"] == 2
    assert stats["skipped"] == 1
    assert stats["transformed"] == 1
    assert transformer.transform_resource.call_count == 1
    assert transformer.transform_resource.call_args.kwargs["data"]["id"] == 7


def test_job_service_cancelled_status_stays_cancelled():
    """Cancelling a running job should mark it cancelled, not failed."""
    job_service = JobService()
    task = MagicMock()
    job_service.register_job("job-1")
    job_service.register_task("job-1", task)

    assert job_service.cancel_job("job-1") is True
    assert job_service.get_job_status("job-1") == {"status": "cancelled"}
