from typing import Any

from aap_migration.api.models import Connection
from aap_migration.config import AAPInstanceConfig, ExportConfig, MigrationConfig, StateConfig


def connection_to_aap_config(conn: Connection) -> AAPInstanceConfig:
    api_prefix = conn.api_prefix or ("/api/v2" if conn.type == "awx" else "/api/controller/v2")
    url = conn.url.rstrip("/") + api_prefix

    return AAPInstanceConfig(
        url=url,
        token=conn.token,
        verify_ssl=conn.verify_ssl,
        timeout=30,
    )


def build_migration_config(
    source: Connection,
    dest: Connection,
    db_url: str,
    *,
    dry_run: bool = False,
    export_overrides: dict[str, Any] | None = None,
) -> MigrationConfig:
    export_kwargs = dict(export_overrides) if export_overrides else {}
    return MigrationConfig(
        source=connection_to_aap_config(source),
        target=connection_to_aap_config(dest),
        state=StateConfig(db_path=db_url),
        dry_run=dry_run,
        export=ExportConfig(**export_kwargs),
    )
