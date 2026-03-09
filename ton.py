"""
TON sender using pytoniq_core cell builder + nacl signing + toncenter v2 API.

pip install pytoniq-core pynacl
"""

import aiohttp
import logging
import base64
import time

from config import TON_API_URL, TON_API_KEY, ADMIN_TON_WALLET, ADMIN_TON_MNEMONIC

logger = logging.getLogger(__name__)

HEADERS = {"Content-Type": "application/json"}
if TON_API_KEY:
    HEADERS["X-API-Key"] = TON_API_KEY

WALLET_ID = 698983191  # WalletV4R2 mainnet subwallet id


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


def _mnemonic_to_privkey(words: list) -> bytes:
    """Derive ed25519 private key from TON 24-word mnemonic via PBKDF2."""
    import hashlib
    entropy = " ".join(words).encode("utf-8")
    seed = hashlib.pbkdf2_hmac(
        "sha512", entropy, b"TON default seed", iterations=100000, dklen=64
    )
    return seed[:32]


async def send_ton(to_address: str, amount_ton: float, memo: str) -> dict:
    try:
        import nacl.signing
        from pytoniq_core import begin_cell, Address

        mnemonic_words = ADMIN_TON_MNEMONIC.split()
        priv_key  = _mnemonic_to_privkey(mnemonic_words)
        seqno     = await _get_seqno(ADMIN_TON_WALLET)
        amount_nano = int(amount_ton * 1_000_000_000)
        expire_at   = int(time.time()) + 60

        dest = Address(to_address)

        # ── Comment cell ──────────────────────────────────────────────────────
        comment_cell = (
            begin_cell()
            .store_uint(0, 32)
            .store_snake_string(memo)
            .end_cell()
        )

        # ── Internal message ──────────────────────────────────────────────────
        int_msg_cell = (
            begin_cell()
            .store_uint(0x10, 6)           # no-bounce
            .store_address(dest)
            .store_coins(amount_nano)
            .store_uint(0, 1 + 4 + 4 + 64 + 32)
            .store_uint(0, 1)              # no state_init
            .store_uint(1, 1)              # body as ref
            .store_ref(comment_cell)
            .end_cell()
        )

        # ── Wallet V4R2 body (to sign) ────────────────────────────────────────
        body_cell = (
            begin_cell()
            .store_uint(WALLET_ID, 32)
            .store_uint(expire_at, 32)
            .store_uint(seqno, 32)
            .store_uint(0, 8)              # op = simple send
            .store_uint(3, 8)              # send mode 3
            .store_ref(int_msg_cell)
            .end_cell()
        )

        # ── Sign ──────────────────────────────────────────────────────────────
        signing_key = nacl.signing.SigningKey(priv_key)
        signature   = signing_key.sign(body_cell.hash).signature  # 64 bytes

        # ── Final signed message ──────────────────────────────────────────────
        signed_cell = (
            begin_cell()
            .store_bytes(signature)
            .store_slice(body_cell.begin_parse())
            .end_cell()
        )

        # ── External message ──────────────────────────────────────────────────
        wallet_addr = Address(ADMIN_TON_WALLET)
        ext_cell = (
            begin_cell()
            .store_uint(0b10, 2)           # ext_in_msg_info
            .store_uint(0b00, 2)           # src = addr_none
            .store_address(wallet_addr)
            .store_coins(0)                # import fee
            .store_uint(0, 1)              # no state_init
            .store_uint(1, 1)              # body as ref
            .store_ref(signed_cell)
            .end_cell()
        )

        boc_b64 = base64.b64encode(ext_cell.to_boc()).decode()
        logger.info(f"BOC b64 (first 40): {boc_b64[:40]}")

        url = f"{TON_API_URL}/sendBocReturnHash"
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json={"boc": boc_b64}, headers=HEADERS,
            ) as r:
                resp = await r.json(content_type=None)
                logger.info(f"toncenter response: {resp}")
                if resp.get("ok"):
                    tx_hash = resp["result"].get("hash", "")
                    return {"success": True, "tx_hash": tx_hash, "error": None}
                else:
                    return {"success": False, "tx_hash": None, "error": resp.get("error", str(resp))}

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
