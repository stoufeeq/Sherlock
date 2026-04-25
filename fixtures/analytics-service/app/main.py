from fastapi import FastAPI

from app.db import db
from app.ledger_report_reader import read_daily_summary

app = FastAPI(title="Analytics Service", version="1.0.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/reports/daily-volume")
def daily_volume() -> list[dict]:
    return db.daily_volume()


@app.get("/reports/customer-summary/{customer_id}")
def customer_summary(customer_id: str) -> dict:
    return db.customer_summary(customer_id)


@app.get("/reports/ledger-daily")
def ledger_daily() -> dict:
    """Summary of the previous night's ledger run, read from the shared report file."""
    return read_daily_summary()
