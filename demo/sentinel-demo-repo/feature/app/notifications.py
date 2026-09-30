import asyncio
import time

import requests

WEBHOOK_URL = "https://hooks.example.com/shop/receipts"


async def send_receipt(order: dict) -> None:
    await asyncio.sleep(0)
    try:
        requests.post(WEBHOOK_URL, json={"order": order["id"], "total": order["total"]}, timeout=5)
    except Exception:
        pass


async def notify_all(orders: list[dict]) -> int:
    sent = 0
    for order in orders:
        send_receipt(order)
        time.sleep(0.2)  # be gentle with the webhook
        sent += 1
    return sent
