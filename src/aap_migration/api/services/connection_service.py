from datetime import UTC, datetime

import httpx
from sqlalchemy.orm import Session

from aap_migration.api.models import Connection
from aap_migration.api.schemas import ConnectionCreate, ConnectionUpdate, TestResult
from aap_migration.api.services.connection_layout import (
    me_probe_url,
    normalize_connection_url,
    ping_probe_candidates,
    resolve_connection_version,
    split_connection_url,
)

__all__ = [
    "ConnectionService",
    "MASKED_TOKEN",
    "normalize_connection_url",
    "split_connection_url",
]
from aap_migration.api.services.token_crypto import decrypt_token, encrypt_token
from aap_migration.client.api_layout import parse_aap_major_minor

MASKED_TOKEN = "********"


def validate_connection_type_role(connection_type: str, role: str) -> None:
    if connection_type == "awx" and role != "source":
        raise ValueError("AWX connections can only use the source role")


class ConnectionService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, data: ConnectionCreate) -> Connection:
        normalized_url, api_prefix = split_connection_url(data.url)
        validate_connection_type_role(data.type, data.role)
        conn = Connection(
            name=data.name,
            type=data.type,
            role=data.role,
            url=normalized_url,
            token=encrypt_token(data.token),
            verify_ssl=data.verify_ssl,
            api_prefix=api_prefix,
        )
        self.db.add(conn)
        self.db.commit()
        self.db.refresh(conn)
        return conn

    def list_all(self) -> list[Connection]:
        return self.db.query(Connection).order_by(Connection.name).all()

    def get(self, connection_id: str) -> Connection | None:
        return self.db.query(Connection).filter(Connection.id == connection_id).first()

    @staticmethod
    def get_token(conn: Connection) -> str | None:
        return decrypt_token(conn.token)

    def update(self, connection_id: str, data: ConnectionUpdate) -> Connection | None:
        conn = self.get(connection_id)
        if not conn:
            return None
        update_data = data.model_dump(exclude_unset=True)
        if update_data.get("token") in ("", MASKED_TOKEN):
            update_data.pop("token", None)
        elif "token" in update_data:
            update_data["token"] = encrypt_token(update_data["token"])
        next_type = update_data.get("type", conn.type)
        next_role = update_data.get("role", conn.role)
        validate_connection_type_role(next_type, next_role)

        discovery_needs_reset = False
        if "url" in update_data and update_data["url"]:
            normalized_url, api_prefix = split_connection_url(update_data["url"])
            update_data["url"] = normalized_url
            update_data["api_prefix"] = api_prefix
            discovery_needs_reset = True
        elif "type" in update_data:
            update_data["api_prefix"] = None
            discovery_needs_reset = True

        if discovery_needs_reset:
            update_data.update(
                {
                    "version": None,
                    "ping_status": "unknown",
                    "ping_error": None,
                    "auth_status": "unknown",
                    "auth_error": None,
                    "last_checked": None,
                }
            )
        for key, value in update_data.items():
            setattr(conn, key, value)
        self.db.commit()
        self.db.refresh(conn)
        return conn

    def delete(self, connection_id: str) -> bool:
        conn = self.get(connection_id)
        if not conn:
            return False
        self.db.delete(conn)
        self.db.commit()
        return True

    def test_connection(self, conn: Connection) -> TestResult:
        ping_status = "error"
        auth_status = "error"
        ping_error = None
        auth_error = None
        version = None
        api_prefix = None
        bearer_token = self.get_token(conn)

        for ping_url, prefix in ping_probe_candidates(conn):
            try:
                resp = httpx.get(
                    ping_url,
                    verify=conn.verify_ssl,
                    timeout=10,
                )
                if resp.status_code == 200:
                    ping_status = "ok"
                    api_prefix = prefix
                    data = resp.json()
                    version = data.get("version", data.get("active_node", None))
                    break
                ping_error = f"HTTP {resp.status_code}"
            except Exception as e:
                ping_error = str(e)

        if ping_status == "ok" and api_prefix is not None:
            stored_version = version
            if stored_version:
                try:
                    major, minor = parse_aap_major_minor(stored_version)
                    stored_version = f"{major}.{minor}"
                except ValueError:
                    pass
            try:
                resp = httpx.get(
                    me_probe_url(conn, stored_version),
                    headers={"Authorization": f"Bearer {bearer_token}"},
                    verify=conn.verify_ssl,
                    timeout=10,
                )
                if resp.status_code == 200:
                    auth_status = "ok"
                else:
                    auth_status = "error"
                    auth_error = f"HTTP {resp.status_code}"
            except Exception as e:
                auth_error = str(e)

        if ping_status == "ok" and version:
            try:
                major, minor = parse_aap_major_minor(version)
                version = f"{major}.{minor}"
            except ValueError:
                pass
        elif ping_status == "ok":
            version = resolve_connection_version(conn)

        conn.ping_status = ping_status
        conn.ping_error = ping_error
        conn.auth_status = auth_status
        conn.auth_error = auth_error
        conn.version = version
        conn.api_prefix = api_prefix
        conn.last_checked = datetime.now(UTC)
        self.db.commit()

        error = ping_error or auth_error
        return TestResult(
            ok=(ping_status == "ok" and auth_status == "ok"),
            ping_status=ping_status,
            auth_status=auth_status,
            version=version,
            api_prefix=api_prefix,
            error=error,
        )
