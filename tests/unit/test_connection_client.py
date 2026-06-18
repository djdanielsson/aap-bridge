"""Unit tests for web connection AAP client helpers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aap_migration.api.models import Connection
from aap_migration.api.services.connection_client import (
    create_connection_client,
    discover_connection_resource_types,
    fetch_connection_resources,
)
from aap_migration.client.aap_source_client import AAPSourceClient
from aap_migration.client.aap_target_client import AAPTargetClient
from aap_migration.client.api_layout import CONTROLLER_API_PREFIX, GATEWAY_API_PREFIX


def _connection(**kwargs) -> Connection:
    defaults = {
        "name": "AAP",
        "type": "aap",
        "url": "https://aap.example.com",
        "token": "token",
        "verify_ssl": True,
        "version": "2.6",
    }
    defaults.update(kwargs)
    return Connection(**defaults)


def test_create_connection_client_uses_target_for_destination() -> None:
    client = create_connection_client(_connection(role="destination"))

    assert isinstance(client, AAPTargetClient)
    assert client._build_url("organizations/") == (
        f"https://aap.example.com{GATEWAY_API_PREFIX}/organizations/"
    )
    assert client._build_url("projects/") == (
        f"https://aap.example.com{CONTROLLER_API_PREFIX}/projects/"
    )


def test_create_connection_client_uses_source_for_source_role() -> None:
    client = create_connection_client(_connection(role="source", version="2.4"))

    assert isinstance(client, AAPSourceClient)
    assert client._build_url("organizations/").endswith("/api/v2/organizations/")


@pytest.mark.asyncio
async def test_discover_connection_resource_types_maps_endpoint_discovery() -> None:
    conn = _connection(role="destination")
    mock_client = AsyncMock()
    mock_client.close = AsyncMock()

    with (
        patch(
            "aap_migration.api.services.connection_client.create_connection_client",
            return_value=mock_client,
        ),
        patch(
            "aap_migration.api.services.connection_client.discover_endpoints",
            new_callable=AsyncMock,
            return_value={
                "endpoints": {
                    "projects": {"url": "projects/"},
                    "organizations": {"url": "organizations/"},
                }
            },
        ),
        patch(
            "aap_migration.api.services.connection_client.connection_to_aap_config",
            return_value=MagicMock(version="2.6"),
        ),
    ):
        result = await discover_connection_resource_types(conn)

    assert result == [
        {"name": "organizations", "label": "Organizations", "api_path": "organizations/"},
        {"name": "projects", "label": "Projects", "api_path": "projects/"},
    ]
    mock_client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_connection_resources_uses_target_list_resources() -> None:
    conn = _connection(role="destination")
    mock_client = AsyncMock()
    mock_client.close = AsyncMock()
    mock_client.list_resources = AsyncMock(return_value=[{"id": 1, "name": "Default"}])

    with patch(
        "aap_migration.api.services.connection_client.create_connection_client",
        return_value=mock_client,
    ):
        items = await fetch_connection_resources(conn, "organizations")

    assert items == [{"id": 1, "name": "Default"}]
    mock_client.list_resources.assert_awaited_once_with("organizations", page_size=200)
    mock_client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_connection_resources_uses_source_pagination() -> None:
    conn = _connection(role="source", version="2.4")
    mock_client = AsyncMock(spec=AAPSourceClient)
    mock_client.close = AsyncMock()
    mock_client.get_paginated = AsyncMock(return_value=[{"id": 1, "name": "Org"}])

    with patch(
        "aap_migration.api.services.connection_client.create_connection_client",
        return_value=mock_client,
    ):
        items = await fetch_connection_resources(conn, "organizations")

    assert items == [{"id": 1, "name": "Org"}]
    mock_client.get_paginated.assert_awaited_once()
    mock_client.close.assert_awaited_once()
