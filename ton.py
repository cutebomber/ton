"""
TON sender using pytoniq_core + correct TON mnemonic key derivation + toncenter v2.
pip install pytoniq-core pynacl
"""

import aiohttp
import asyncio
import logging
import base64
import time
import hmac
import hashlib

from config import TON_API_URL, TON_API_KEY, ADMIN_TON_WALLET, ADMIN_TON_MNEMONIC

logger = logging.getLogger(__name__)

HEADERS = {"Content-Type": "application/json"}
if TON_API_KEY:
    HEADERS["X-API-Key"] = TON_API_KEY

WALLET_ID = 698983191  # WalletV4R2 mainnet subwallet id


# ── TON mnemonic → private key (correct algorithm) ───────────────────────────

def _mnemonic_to_privkey(words: list) -> bytes:
    """
    TON official mnemonic derivation:
    1. PBKDF2-HMAC-SHA512(mnemonic, "TON default seed", 100000) → 64 bytes seed
    2. HMAC-SHA512(seed, "ed25519 seed") → intermediate
    3. First 32 bytes = private key
    See: https://github.com/toncenter/tonweb-mnemonic
    """
    mnemonic_str = " ".join(words).encode("utf-8")

    # Step 1: derive seed from mnemonic
    seed = hashlib.pbkdf2_hmac(
        "sha512",
        mnemonic_str,
        b"TON default seed",
        iterations=100000,
        dklen=64,
    )

    # Step 2: derive ed25519 key via HMAC-SHA512
    h = hmac.new(b"ed25519 seed", seed, hashlib.sha512).digest()
    return h[:32]


# ── Toncenter helpers ─────────────────────────────────────────────────────────

async def get_wallet_balance(address: str) -> float:
    try:
        url = f"{TON_API_URL}/getAddressBalance"
        async with aiohttp.ClientSession() as s:
            async with s.get(url, params={"address": address}, headers=HEADERS) as r:
                data = await r.json(content_type=None)
                if data.get("ok"):
                    return int(data["result"]) / 1e9
    except Exception as e:
        logger.error(f"Balance check failed: {e}")
    return 0.0


async def _get_seqno(address: str) -> int:
    try:
        url = f"{TON_API_URL}/runGetMethod"
        async with aiohttp.ClientSession() as s:
            async with s.post(
                url,
                json={"address": address, "method": "seqno", "stack": []},
                headers=HEADERS,
            ) as r:
                data = await r.json(content_type=None)
                if data.get("ok"):
                    stack = data["result"].get("stack", [])
                    if stack:
                        val = stack[0][1]
                        return int(val, 16) if str(val).startswith("0x") else int(val)
    except Exception as e:
        logger.warning(f"seqno fetch failed: {e}")
    return 0


async def _broadcast_boc(boc_b64: str, retries: int = 3) -> dict:
    """Send BOC to toncenter, retry on rate limit."""
    url = f"{TON_API_URL}/sendBocReturnHash"
    for attempt in range(retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json={"boc": boc_b64}, headers=HEADERS,
                ) as r:
                    resp = await r.json(content_type=None)
                    logger.info(f"toncenter response (attempt {attempt+1}): {resp}")
                    if resp.get("ok"):
                        tx_hash = resp["result"].get("hash", "")
                        return {"success": True, "tx_hash": tx_hash, "error": None}
                    if resp.get("code") == 429:
                        wait = 2 ** attempt * 2
                        logger.warning(f"Rate limited, waiting {wait}s...")
                        await asyncio.sleep(wait)
                        continue
                    return {"success": False, "tx_hash": None, "error": resp.get("error", str(resp))}
        except Exception as e:
            logger.error(f"Broadcast attempt {attempt+1} failed: {e}")
            await asyncio.sleep(2)
    return {"success": False, "tx_hash": None, "error": "Max retries exceeded"}


# ── Main send function ────────────────────────────────────────────────────────

async def send_ton(to_address: str, amount_ton: float, memo: str) -> dict:
    try:
        import nacl.signing
        from pytoniq_core import begin_cell, Address

        mnemonic_words = ADMIN_TON_MNEMONIC.split()
        priv_key    = _mnemonic_to_privkey(mnemonic_words)
        seqno       = await _get_seqno(ADMIN_TON_WALLET)
        amount_nano = int(amount_ton * 1_000_000_000)
        expire_at   = int(time.time()) + 60

        logger.info(f"seqno={seqno}, amount_nano={amount_nano}, to={to_address}")

        dest        = Address(to_address)
        wallet_addr = Address(ADMIN_TON_WALLET)

        # Comment cell
        comment_cell = (
            begin_cell()
            .store_uint(0, 32)
            .store_snake_string(memo)
            .end_cell()
        )

        # Internal message
        int_msg_cell = (
            begin_cell()
            .store_uint(0x10, 6)
            .store_address(dest)
            .store_coins(amount_nano)
            .store_uint(0, 1 + 4 + 4 + 64 + 32)
            .store_uint(0, 1)
            .store_uint(1, 1)
            .store_ref(comment_cell)
            .end_cell()
        )

        # Wallet body (what gets signed)
        body_cell = (
            begin_cell()
            .store_uint(WALLET_ID, 32)
            .store_uint(expire_at, 32)
            .store_uint(seqno, 32)
            .store_uint(0, 8)   # op
            .store_uint(3, 8)   # send mode
            .store_ref(int_msg_cell)
            .end_cell()
        )

        # Sign the body hash
        signing_key = nacl.signing.SigningKey(priv_key)
        signature   = signing_key.sign(body_cell.hash).signature

        # Signed message = signature + body bits
        signed_cell = (
            begin_cell()
            .store_bytes(signature)
            .store_slice(body_cell.begin_parse())
            .end_cell()
        )

        # External message wrapper
        ext_cell = (
            begin_cell()
            .store_uint(0b10, 2)
            .store_uint(0b00, 2)
            .store_address(wallet_addr)
            .store_coins(0)
            .store_uint(0, 1)
            .store_uint(1, 1)
            .store_ref(signed_cell)
            .end_cell()
        )

        boc_b64 = base64.b64encode(ext_cell.to_boc()).decode()
        return await _broadcast_boc(boc_b64)

    except Exception as e:
        logger.error(f"send_ton error: {e}", exc_info=True)
        return {"success": False, "tx_hash": None, "error": str(e)}


async def validate_ton_address(address: str) -> bool:
    try:
        url = f"{TON_API_URL}/detectAddress"
        async with aiohttp.ClientSession() as s:
            async with s.get(url, params={"address": address}, headers=HEADERS) as r:
                data = await r.json(content_type=None)
                return data.get("ok", False)
    except Exception:
        return False
