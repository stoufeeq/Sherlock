import asyncio
import json
import logging
import os

from confluent_kafka import Consumer

from app.account_client import AccountServiceClient

log = logging.getLogger(__name__)

TOPIC = "banking.transactions.created"


def _make_consumer() -> Consumer:
    return Consumer(
        {
            "bootstrap.servers": os.getenv("KAFKA_BROKER", "redpanda:29092"),
            "group.id": "fraud-detection",
            "auto.offset.reset": "latest",
        }
    )


async def run_consumer(account_client: AccountServiceClient) -> None:
    consumer = _make_consumer()
    consumer.subscribe([TOPIC])
    loop = asyncio.get_event_loop()
    try:
        while True:
            msg = await loop.run_in_executor(None, consumer.poll, 1.0)
            if msg is None or msg.error():
                continue
            event = json.loads(msg.value())
            # cross-service dep: we call account-service as part of scoring
            await account_client.get_account(event["fromAccount"])
            log.info("Scored transaction %s", event.get("transactionId"))
    finally:
        consumer.close()
