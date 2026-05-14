"""Focused tests for the web API runtime layer."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from aap_migration.api.models import Connection
from aap_migration.api.routers import migration as migration_router
from aap_migration.api.routers import resources as resources_router
from aap_migration.api.services.connection_service import ConnectionService
from aap_migration.api.services.job_service import JobService
from aap_migration.api.services.migration_service import MigrationService
from aap_migration.client.exceptions import APIError
from aap_migration.config import StateConfig
from aap_migration.migration import database as migration_database
from aap_migration.migration.coordinator import MigrationCoordinator
from aap_migration.migration.importer import ResourceImporter
from aap_migration.migration.state import MigrationState


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


def _clear_database_cache() -> None:
    for engine in migration_database._engines.values():
        engine.dispose()
    migration_database._engines.clear()
    migration_database._session_factories.clear()


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


def test_database_engines_are_cached_per_database_url(tmp_path):
    """Different state DB URLs should not reuse the same global engine."""
    _clear_database_cache()
    url_one = f"sqlite:///{tmp_path / 'one.db'}"
    url_two = f"sqlite:///{tmp_path / 'two.db'}"

    try:
        engine_one = migration_database.init_database(url_one)
        engine_two = migration_database.init_database(url_two)

        assert engine_one is not engine_two
        assert migration_database.get_engine(url_one) is engine_one
        assert migration_database.get_engine(url_two) is engine_two
        assert migration_database.get_session_factory(
            url_one
        ) is not migration_database.get_session_factory(url_two)
    finally:
        _clear_database_cache()


def test_in_progress_state_is_not_treated_as_completed(tmp_path):
    """Crash leftovers in in_progress should be retried, not skipped as done."""
    _clear_database_cache()
    state = MigrationState(StateConfig(db_path=str(tmp_path / "state.db")))

    try:
        state.mark_in_progress("inventory", 123, "Test Inventory", "import")
        assert state.get_status("inventory", 123) == "in_progress"
        assert state.is_migrated("inventory", 123) is False
    finally:
        _clear_database_cache()


@pytest.mark.asyncio
async def test_importer_marks_unresolved_conflict_as_skipped():
    """Conflict fallback should record a skip instead of writing target_id=0."""
    client = MagicMock()
    client.create_resource = AsyncMock(
        side_effect=APIError(
            "already exists",
            status_code=400,
            response={"name": ["already exists"]},
        )
    )
    state = MagicMock()
    state.is_migrated.return_value = False

    importer = ResourceImporter(client, state, MagicMock())
    importer._handle_conflict = AsyncMock(return_value=None)

    result = await importer.import_resource("organizations", 1, {"name": "Default"})

    assert result == {"_skipped": True, "name": "Default"}
    state.mark_skipped.assert_called_once()
    state.mark_completed.assert_not_called()


def test_clear_state_uses_app_database_url():
    """Clear-state should target the app's configured DB, not ambient env vars."""
    with (
        patch.object(
            migration_router, "get_app_state", return_value=MagicMock(db_url="sqlite:///custom.db")
        ),
        patch(
            "aap_migration.cli.commands.cleanup.clear_database", return_value=(3, 7)
        ) as mock_clear,
    ):
        result = migration_router.clear_state()

    assert result == {"cleared_progress": 3, "deleted_mappings": 7}
    mock_clear.assert_called_once_with("sqlite:///custom.db")


def test_list_resources_returns_502_when_upstream_fetch_fails():
    """Resource browser requests should surface upstream errors instead of pretending results are empty."""
    db = MagicMock()
    conn = MagicMock()

    with (
        patch.object(resources_router, "ConnectionService") as mock_service,
        patch(
            "aap_migration.api.services.platform_adapter.PlatformAdapter.list_resources",
            side_effect=RuntimeError("boom"),
        ),
    ):
        mock_service.return_value.get.return_value = conn
        with pytest.raises(HTTPException) as excinfo:
            resources_router.list_resources("conn-1", "inventories", db=db)
    assert "Failed to load resources" in str(excinfo.value.detail)
