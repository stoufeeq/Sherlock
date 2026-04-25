from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException

app = FastAPI(title="Sherlock CMDB Stub", version="0.1.0")

DATA_PATH = Path(__file__).parent.parent / "data" / "services.yaml"


def load_services() -> dict[str, dict]:
    with DATA_PATH.open() as f:
        raw = yaml.safe_load(f)
    return {svc["id"]: svc for svc in raw}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/services")
def list_services(team: str | None = None, tier: int | None = None) -> list[dict]:
    services = list(load_services().values())
    if team:
        services = [s for s in services if s.get("team") == team]
    if tier is not None:
        services = [s for s in services if s.get("tier") == tier]
    return services


@app.get("/services/{service_id}")
def get_service(service_id: str) -> dict:
    services = load_services()
    if service_id not in services:
        raise HTTPException(status_code=404, detail=f"service '{service_id}' not registered")
    return services[service_id]
