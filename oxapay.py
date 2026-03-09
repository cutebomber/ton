"""
OxaPay crypto payment gateway wrapper — polling mode (no webhook/public URL needed).

Docs: https://docs.oxapay.com/api-reference/payment/generate-invoice

Flow:
  1. create_invoice() — generate a pay link and get back a track_id
  2. Scheduler polls get_invoice(track_id) every 10 seconds
  3. When status == "paid", deposit is confirmed and user/advertiser is credited
"""

import hashlib
import hmac
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
    lifetime: int = 60,   # minutes until invoice expires
) -> dict:
    """
    Create an OxaPay invoice.
    Returns dict containing at least: pay_link, track_id, status
    No callback_url needed — we poll for status instead.
    """
    payload = {
        "amount":            amount,
        "currency":          currency,
        "lifetime":          lifetime,
        "order_id":          order_id,    # we store telegram_id (or -adv_id) here
        "description":       description,
        "fee_paid_by_payer": 1,           # payer covers OxaPay's fee
    }

    url = f"{API_BASE}/payment/invoice"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=HEADERS) as r:
            data = await r.json()
            if data.get("result") != 100:
                raise RuntimeError(
                    f"OxaPay invoice error (result={data.get('result')}): "
                    f"{data.get('message', data)}"
                )
            return data   # contains pay_link, track_id, expiredAt, ...


async def get_invoice(track_id: str) -> dict:
    """
    Fetch the current status of an invoice by track_id.
    Returns dict with at least: status, amount, currency, pay_amount, pay_currency
    Possible statuses: waiting | paying | paid | expired | cancelled
    """
    url = f"{API_BASE}/payment/info"
    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            json={"track_id": track_id},
            headers=HEADERS,
        ) as r:
            data = await r.json()
            if data.get("result") != 100:
                raise RuntimeError(
                    f"OxaPay getInvoice error (result={data.get('result')}): "
                    f"{data.get('message', data)}"
                )
            return data