import httpx

from app.config import settings


class CMDBClient:
    def __init__(self) -> None:
        self._http = httpx.Client(base_url=settings.cmdb_url, timeout=5.0)

    def list_services(self) -> list[dict]:
        r = self._http.get("/services")
        r.raise_for_status()
        return r.json()

    def get(self, service_id: str) -> dict | None:
        r = self._http.get(f"/services/{service_id}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
