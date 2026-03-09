"""
OxaPay API wrapper.

Create invoice:  POST https://api.oxapay.com/v1/payment/invoice
  Headers: merchant_api_key
  Response: {"status": 200, "data": {"track_id": "...", "payment_url": "...", ...}}

Check invoice:   POST https://api.oxapay.com/merchants/inquiry
  Body: {"merchant": KEY, "trackId": TRACK_ID}
  Response: {"result": 100, "status": "New|Waiting|Paying|Confirming|Paid|Expired|Failed", ...}
"""

import aiohttp
from config import OXAPAY_MERCHANT_KEY


async def create_invoice(
    amount: float,
    currency: str,
    order_id: str,
    description: str = "",
    lifetime: int = 60,
) -> dict:
    """
    Create invoice. Returns data dict with: track_id, payment_url
    """
    url = "https://api.oxapay.com/v1/payment/invoice"
    headers = {
        "merchant_api_key": OXAPAY_MERCHANT_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "amount":            amount,
        "currency":          currency,
        "lifetime":          lifetime,
        "order_id":          order_id,
        "description":       description,
        "fee_paid_by_payer": 1,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers) as r:
            data = await r.json(content_type=None)
            if data.get("status") != 200:
                raise RuntimeError(
                    f"status={data.get('status')} message={data.get('message', data)}"
                )
            return data["data"]   # {"track_id": "...", "payment_url": "..."}


async def get_invoice(track_id: str) -> dict:
    """
    Check invoice status via merchants/inquiry endpoint.
    Returns full response dict with: result, status, amount, currency, ...
    Statuses: New | Waiting | Paying | Confirming | Paid | Expired | Failed
    """
    url = "https://api.oxapay.com/merchants/inquiry"
    payload = {
        "merchant": OXAPAY_MERCHANT_KEY,
        "trackId":  int(track_id),
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as r:
            data = await r.json(content_type=None)
            if data.get("result") != 100:
                raise RuntimeError(
                    f"status={data.get('result')} message={data.get('message', data)}"
                )
            return data   # status, amount, currency, payAmount, payCurrency, ...
