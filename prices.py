"""
Live TON/USD rate from CoinGecko (free, no API key needed).
Rate is cached for 5 minutes to avoid hammering the API.
"""

import asyncio
import aiohttp
import time
import logging

logger = logging.getLogger(__name__)

_cache = {"rate": None, "ts": 0}
CACHE_TTL = 300  # seconds


async def get_ton_usd_rate() -> float:
    """Return current TON price in USD."""
    now = time.time()
    if _cache["rate"] and now - _cache["ts"] < CACHE_TTL:
        return _cache["rate"]

    try:
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {"ids": "the-open-network", "vs_currencies": "usd"}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as r:
                data = await r.json()
                rate = float(data["the-open-network"]["usd"])
                _cache["rate"] = rate
                _cache["ts"]   = now
                logger.info(f"TON/USD rate: ${rate}")
                return rate
    except Exception as e:
        logger.warning(f"CoinGecko fetch failed: {e}")
        # Return cached rate if available, else fallback
        return _cache["rate"] or 2.0


async def usd_to_ton(usd: float) -> float:
    """Convert a USD amount to TON at current market rate."""
    rate = await get_ton_usd_rate()
    return round(usd / rate, 6)


async def ton_to_usd(ton: float) -> float:
    """Convert a TON amount to USD at current market rate."""
    rate = await get_ton_usd_rate()
    return round(ton * rate, 4)