"""Build AAP HTTP clients and resource helpers from saved web connections."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from aap_migration.api.models import Connection
from aap_migration.api.services.engine_adapter import connection_to_aap_config
from aap_migration.client.aap_source_client import AAPSourceClient
from aap_migration.client.aap_target_client import AAPTargetClient
from aap_migration.prep.endpoint_discovery import discover_endpoints
from aap_migration.resources import get_endpoint

AAPClient = AAPSourceClient | AAPTargetClient


def create_connection_client(conn: Connection) -> AAPClient:
    """Create the appropriate AAP client for a saved connection."""
    config = connection_to_aap_config(conn)
    if conn.role == "destination":
        return AAPTargetClient(config=config)
    return AAPSourceClient(config=config)


@asynccontextmanager
async def connection_client(conn: Connection):
    """Yield an AAP client and close it when done."""
    client = create_connection_client(conn)
    try:
        yield client
    finally:
        await client.close()


async def discover_connection_resource_types(conn: Connection) -> list[dict[str, str]]:
    """Discover browsable resource types for a saved connection."""
    async with connection_client(conn) as client:
        discovery = await discover_endpoints(
            client,
            api_version=connection_to_aap_config(conn).version or conn.version or "",
            instance=conn.role,
        )

    return [
        {
            "name": name,
            "label": name.replace("_", " ").title(),
            "api_path": details["url"],
        }
        for name, details in sorted(discovery.get("endpoints", {}).items())
    ]


async def fetch_connection_resources(conn: Connection, resource_type: str) -> list[dict[str, Any]]:
    """Fetch all pages of a resource type from a saved connection."""
    async with connection_client(conn) as client:
        return await fetch_resources_with_client(client, conn, resource_type)


async def fetch_resources_with_client(
    client: AAPClient,
    conn: Connection,
    resource_type: str,
) -> list[dict[str, Any]]:
    """Fetch all pages of a resource type using an existing client."""
    if conn.role == "destination":
        return await client.list_resources(resource_type, page_size=200)
    endpoint = get_endpoint(resource_type)
    return await client.get_paginated(endpoint, page_size=200)


async def list_connection_resources(
    conn: Connection,
    resource_type: str,
    page: int,
    page_size: int,
    search: str,
) -> dict[str, Any]:
    """Fetch a single page of resources for the object browser."""
    async with connection_client(conn) as client:
        endpoint = get_endpoint(resource_type)
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if search:
            params["search"] = search
        data = await client.get(endpoint, params=params)
        return {
            "count": data.get("count", 0),
            "results": data.get("results", []),
            "page": page,
            "page_size": page_size,
        }
