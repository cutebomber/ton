"""
OxaPay API wrapper — v1 endpoint (api.oxapay.com/v1)

Response format:
  - Success: {"status": 200, "data": {...}}
  - Error:   {"status": 4xx, "message": "..."}

Invoice response fields (camelCase):
  payLink, trackId, expiredAt, ...

Invoice status poll fields:
  status: "New" | "Waiting" | "Confirming" | "Paid" | "Expired" | "Failed"
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
    Returns dict with at least: payLink, trackId
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
            data = await r.json()
            status = data.get("status")
            if status != 200:
                raise RuntimeError(
                    f"OxaPay error (status={status}): {data.get('message', data)}"
                )
            # data["data"] contains payLink, trackId, etc.
            return data.get("data", data)


async def get_invoice(track_id: str) -> dict:
    """
    Fetch current status of an invoice by trackId.
    Possible statuses: New | Waiting | Confirming | Paid | Expired | Failed
    """
    url = f"{API_BASE}/payment/info"
    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            json={"track_id": track_id},
            headers=HEADERS,
        ) as r:
            data = await r.json()
            status = data.get("status")
            if status != 200:
                raise RuntimeError(
                    f"OxaPay getInvoice error (status={status}): {data.get('message', data)}"
                )
            return data.get("data", data)
