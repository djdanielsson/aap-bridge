from datetime import UTC, datetime

import httpx
from sqlalchemy.orm import Session

from aap_migration.api.models import Connection
from aap_migration.api.schemas import ConnectionCreate, ConnectionUpdate, TestResult


class ConnectionService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, data: ConnectionCreate) -> Connection:
        conn = Connection(
            name=data.name,
            type=data.type,
            role=data.role,
            url=data.url.rstrip("/"),
            token=data.token,
            verify_ssl=data.verify_ssl,
        )
        self.db.add(conn)
        self.db.commit()
        self.db.refresh(conn)
        return conn

    def list_all(self) -> list[Connection]:
        return self.db.query(Connection).order_by(Connection.name).all()

    def get(self, connection_id: str) -> Connection | None:
        return self.db.query(Connection).filter(Connection.id == connection_id).first()

    def update(self, connection_id: str, data: ConnectionUpdate) -> Connection | None:
        conn = self.get(connection_id)
        if not conn:
            return None
        update_data = data.model_dump(exclude_unset=True)
        if "url" in update_data and update_data["url"]:
            update_data["url"] = update_data["url"].rstrip("/")
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

        api_prefixes = ["/api/controller/v2", "/api/v2"]
        if conn.type == "awx":
            api_prefixes = ["/api/v2"]

        base_url = conn.url
        for known_path in ["/api/controller/v2", "/api/v2"]:
            if base_url.endswith(known_path):
                api_prefixes = [""]
                break

        for prefix in api_prefixes:
            try:
                resp = httpx.get(
                    f"{conn.url}{prefix}/ping/",
                    verify=conn.verify_ssl,
                    timeout=10,
                )
                if resp.status_code == 200:
                    ping_status = "ok"
                    api_prefix = prefix
                    data = resp.json()
                    version = data.get("version", data.get("active_node", None))
                    break
                else:
                    ping_error = f"HTTP {resp.status_code}"
            except Exception as e:
                ping_error = str(e)

        if ping_status == "ok" and api_prefix:
            try:
                resp = httpx.get(
                    f"{conn.url}{api_prefix}/me/",
                    headers={"Authorization": f"Bearer {conn.token}"},
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
