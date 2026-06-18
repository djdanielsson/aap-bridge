import os
from collections.abc import Iterator
from contextlib import contextmanager

from aap_migration.api.models import Connection
from aap_migration.api.services.token_crypto import decrypt_token
from aap_migration.client.api_layout import normalize_host_url
from aap_migration.config import (
    AAPInstanceConfig,
    MigrationConfig,
    StateConfig,
    load_config_from_yaml,
    normalize_aap_version,
)


def connection_to_aap_config(conn: Connection) -> AAPInstanceConfig:
    if not conn.version or not conn.version.strip():
        raise ValueError(
            f"Connection '{conn.name}' has no AAP version. "
            "Test the connection first to discover the version."
        )

    return AAPInstanceConfig(
        url=normalize_host_url(conn.url),
        token=decrypt_token(conn.token),
        version=normalize_aap_version(conn.version),
        verify_ssl=conn.verify_ssl,
        timeout=30,
    )


def _connection_env(prefix: str, conn: Connection) -> dict[str, str]:
    config = connection_to_aap_config(conn)
    return {
        f"{prefix}__URL": config.url,
        f"{prefix}__TOKEN": config.token or "",
        f"{prefix}__VERSION": config.version or "",
        f"{prefix}__VERIFY_SSL": str(conn.verify_ssl).lower(),
        f"{prefix}__TIMEOUT": "30",
    }


@contextmanager
def _temporary_env(overrides: dict[str, str]) -> Iterator[None]:
    original: dict[str, str | None] = {key: os.environ.get(key) for key in overrides}
    try:
        for key, value in overrides.items():
            os.environ[key] = value
        yield
    finally:
        for key, original_value in original.items():
            saved_value = original_value
            if saved_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = saved_value


def load_runtime_config(source: Connection, dest: Connection, db_url: str) -> MigrationConfig:
    config_path = os.environ.get("AAP_BRIDGE_CONFIG")
    if config_path:
        overrides = {}
        overrides.update(_connection_env("SOURCE", source))
        overrides.update(_connection_env("TARGET", dest))
        with _temporary_env(overrides):
            config = load_config_from_yaml(config_path)
    else:
        config = MigrationConfig(
            source=connection_to_aap_config(source),
            target=connection_to_aap_config(dest),
        )

    config.source = connection_to_aap_config(source)
    config.target = connection_to_aap_config(dest)
    config.state = StateConfig(db_path=db_url)
    return config


def build_migration_config(source: Connection, dest: Connection, db_url: str) -> MigrationConfig:
    return load_runtime_config(source, dest, db_url)
