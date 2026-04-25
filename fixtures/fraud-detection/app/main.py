import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.account_client import AccountServiceClient
from app.kafka_consumer import run_consumer


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = AccountServiceClient()
    task = asyncio.create_task(run_consumer(client))
    yield
    task.cancel()


app = FastAPI(title="Fraud Detection", version="1.0.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/score/{transaction_id}")
def get_score(transaction_id: str) -> dict:
    return {"transactionId": transaction_id, "score": 0.12, "decision": "ALLOW"}
