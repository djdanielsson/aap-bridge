import httpx

from aap_migration.api.models import Connection
from aap_migration.api.services.connection_layout import build_connection_layout
from aap_migration.api.services.token_crypto import decrypt_token
from aap_migration.client.api_layout import ApiLayout


class PlatformAdapter:
    def __init__(self, conn: Connection) -> None:
        self.conn = conn
        self._layout: ApiLayout = build_connection_layout(conn)
        self.headers = {}
        token = decrypt_token(conn.token)
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    @property
    def base_url(self) -> str:
        return self._layout.default_base_url

    def _request_url(self, path: str) -> str:
        endpoint = path.lstrip("/")
        if not endpoint:
            return f"{self._layout.default_base_url}/"
        base = self._layout.base_for_endpoint(endpoint)
        return f"{base}/{endpoint}"

    def _get(self, path: str, params: dict | None = None) -> dict:
        resp = httpx.get(
            self._request_url(path),
            headers=self.headers,
            params=params,
            verify=self.conn.verify_ssl,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise ValueError(f"Unexpected response type for {path}: expected object")
        return data

    def discover_resource_types(self) -> list[dict]:
        data = self._get("/")
        if not isinstance(data, dict):
            return []
        return [
            {"name": key, "label": key.replace("_", " ").title(), "api_path": path}
            for key, path in sorted(data.items())
            if isinstance(path, str)
        ]

    def fetch_all(self, resource_type: str) -> list[dict]:
        results = []
        page = 1
        while True:
            data = self._get(f"/{resource_type}/", params={"page": page, "page_size": 200})
            results.extend(data.get("results", []))
            if not data.get("next"):
                break
            page += 1
        return results

    def list_resources(self, resource_type: str, page: int, page_size: int, search: str) -> dict:
        params: dict = {"page": page, "page_size": page_size}
        if search:
            params["search"] = search
        data = self._get(f"/{resource_type}/", params=params)
        return {
            "count": data.get("count", 0),
            "results": data.get("results", []),
            "page": page,
            "page_size": page_size,
        }
