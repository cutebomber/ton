"""
OxaPay API wrapper — v1 endpoints (api.oxapay.com/v1)

Create invoice:
  POST /v1/payment/invoice
  Response: {"status": 200, "data": {"track_id": "...", "payment_url": "...", ...}}

Check invoice status:
  POST /v1/payment/info  with {"track_id": "..."}
  Response: {"status": 200, "data": {"status": "New|Waiting|Paying|Paid|Expired|Failed", ...}}
"""

import aiohttp
from config import OXAPAY_MERCHANT_KEY

API_BASE = "https://api.oxapay.com/v1"

HEADERS = {
    "merchant_api_key": OXAPAY_MERCHANT_KEY,
    "Content-Type": "application/json",
}


async def create_invoice(
    amount: float,
    currency: str,
    order_id: str,
    description: str = "",
    lifetime: int = 60,
) -> dict:
    """
    Create an OxaPay invoice.
    Returns data dict with: track_id, payment_url, expired_at
    """
    payload = {
        "amount":            amount,
        "currency":          currency,
        "lifetime":          lifetime,
        "order_id":          order_id,
        "description":       description,
        "fee_paid_by_payer": 1,
    }

    url = f"{API_BASE}/payment/invoice"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=HEADERS) as r:
            raw = await r.text()
            data = await r.json(content_type=None)
            if data.get("status") != 200:
                raise RuntimeError(
                    f"status={data.get('status')} message={data.get('message', raw)}"
                )
            return data["data"]   # {"track_id": "...", "payment_url": "...", "expired_at": ...}


async def get_invoice(track_id: str) -> dict:
    """
    Poll status of an invoice.
    Returns data dict with: status, amount, currency, ...
    Statuses: New | Waiting | Paying | Confirming | Paid | Expired | Failed
    """
    url = f"{API_BASE}/payment/info"
    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            json={"track_id": track_id},
            headers=HEADERS,
        ) as r:
            data = await r.json(content_type=None)
            if data.get("status") != 200:
                raise RuntimeError(
                    f"status={data.get('status')} message={data.get('message', data)}"
                )
            return data["data"]
