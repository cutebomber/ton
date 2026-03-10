"""
TON sender — logic ported from working faucet bot.
Uses pytoniq_core for key derivation + tonsdk for transfer building.

pip install tonsdk pytoniq-core pynacl aiohttp
"""

import asyncio
import logging
import aiohttp

from config import TON_API_URL, TON_API_KEY, ADMIN_TON_WALLET, ADMIN_TON_MNEMONIC

logger = logging.getLogger(__name__)

HEADERS = {"Content-Type": "application/json"}
if TON_API_KEY:
    HEADERS["X-API-Key"] = TON_API_KEY

WALLET_VERSION = "v4r2"   # change to "v3r2" if your admin wallet is v3r2

# One tx at a time — prevents seqno conflicts
_tx_lock = asyncio.Lock()


# ── Key derivation + wallet builder ──────────────────────────────────────────

def _build_wallet_and_keys():
    """
    Returns (priv_key, pub_key, wallet, sender_addr, derivation)
    Tries pytoniq_core derivation first (Tonkeeper BIP39),
    falls back to tonsdk native.
    """
    words = ADMIN_TON_MNEMONIC.strip().split()
    if len(words) != 24:
        raise ValueError(f"Expected 24 mnemonic words, got {len(words)}")

    # ── pytoniq_core path (Tonkeeper BIP39) ──────────────────────────────────
    try:
        from pytoniq_core.crypto.keys import mnemonic_to_private_key
        from tonsdk.contract.wallet import WalletV4ContractR2, WalletV3ContractR2

        pub_key, priv_key = mnemonic_to_private_key(words)

        cls    = WalletV4ContractR2 if WALLET_VERSION == "v4r2" else WalletV3ContractR2
        wallet = cls(options={"public_key": pub_key, "wc": 0})
        sender_addr = wallet.address.to_string(True, True, False)

        logger.info(f"pytoniq_core derivation OK — address: {sender_addr}")
        return priv_key, pub_key, wallet, sender_addr, "pytoniq"

    except ImportError:
        logger.warning("pytoniq_core not found — using tonsdk native derivation")
    except Exception as e:
        logger.warning(f"pytoniq_core path failed: {e} — trying tonsdk native")

    # ── tonsdk native fallback ────────────────────────────────────────────────
    from tonsdk.contract.wallet import Wallets, WalletVersionEnum
    version_map = {
        "v3r2": WalletVersionEnum.v3r2,
        "v4r2": WalletVersionEnum.v4r2,
    }
    _, pub_key, priv_key, wallet = Wallets.from_mnemonics(
        words, version_map[WALLET_VERSION], workchain=0
    )
    sender_addr = wallet.address.to_string(True, True, False)
    logger.info(f"tonsdk native derivation — address: {sender_addr}")
    return priv_key, pub_key, wallet, sender_addr, "tonsdk"


def _sign_with_priv_key(priv_key: bytes, msg: bytes) -> bytes:
    import nacl.signing
    return bytes(nacl.signing.SigningKey(priv_key).sign(msg).signature)


# ── Rate-limit-aware toncenter calls ─────────────────────────────────────────

async def _tc_get(session, method, params, retries=6):
    for attempt in range(retries):
        async with session.get(
            f"{TON_API_URL}/{method}", params=params, headers=HEADERS
        ) as r:
            if r.status == 429:
                wait = 2.0 * (attempt + 1)
                logger.warning(f"Rate limited on {method}, waiting {wait}s")
                await asyncio.sleep(wait)
                continue
            return await r.json(content_type=None)
    return {"ok": False, "error": "Rate limit max retries exceeded"}


async def _tc_post(session, method, body, retries=6):
    for attempt in range(retries):
        async with session.post(
            f"{TON_API_URL}/{method}", json=body, headers=HEADERS
        ) as r:
            if r.status == 429:
                wait = 2.0 * (attempt + 1)
                logger.warning(f"Rate limited on {method}, waiting {wait}s")
                await asyncio.sleep(wait)
                continue
            return await r.json(content_type=None)
    return {"ok": False, "error": "Rate limit max retries exceeded"}


# ── Balance check ─────────────────────────────────────────────────────────────

async def get_wallet_balance(address: str) -> float:
    try:
        async with aiohttp.ClientSession() as s:
            data = await _tc_get(s, "getAddressBalance", {"address": address})
            if data.get("ok"):
                return int(data["result"]) / 1e9
    except Exception as e:
        logger.error(f"Balance check failed: {e}")
    return 0.0


# ── Main send function ────────────────────────────────────────────────────────

async def send_ton(to_address: str, amount_ton: float, memo: str) -> dict:
    from tonsdk.utils import to_nano, bytes_to_b64str

    try:
        priv_key, pub_key, wallet, sender_addr, derivation = _build_wallet_and_keys()
    except Exception as e:
        return {"success": False, "tx_hash": None, "error": f"Wallet init failed: {e}"}

    async with _tx_lock:
        try:
            async with aiohttp.ClientSession() as session:

                # 1. Check balance
                bal_data = await _tc_get(session, "getAddressBalance", {"address": sender_addr})
                balance  = int(bal_data.get("result", 0)) / 1e9 if bal_data.get("ok") else 0.0
                logger.info(f"Sender balance: {balance:.5f} TON")

                if balance < amount_ton + 0.015:
                    return {
                        "success": False, "tx_hash": None,
                        "error": f"Insufficient balance: {balance:.5f} TON (need {amount_ton + 0.015:.4f})"
                    }

                await asyncio.sleep(0.4)

                # 2. Get seqno via getWalletInformation (most reliable)
                seqno = None
                wi    = await _tc_get(session, "getWalletInformation", {"address": sender_addr})
                logger.info(f"getWalletInformation: {wi}")
                try:
                    if wi.get("ok") and wi["result"].get("seqno") is not None:
                        seqno = int(wi["result"]["seqno"])
                        logger.info(f"seqno from getWalletInformation: {seqno}")
                except Exception as e:
                    logger.warning(f"seqno parse failed: {e}")

                # Fallback to runGetMethod
                if seqno is None:
                    await asyncio.sleep(0.4)
                    sq = await _tc_get(
                        session, "runGetMethod",
                        {"address": sender_addr, "method": "seqno", "stack": "[]"}
                    )
                    logger.info(f"runGetMethod seqno: {sq}")
                    try:
                        if sq.get("ok") and sq["result"].get("exit_code") == 0:
                            raw   = sq["result"]["stack"][0][1]
                            seqno = int(raw, 16) if raw.startswith("0x") else int(raw)
                    except Exception as e:
                        logger.warning(f"runGetMethod seqno parse failed: {e}")

                if seqno is None:
                    return {"success": False, "tx_hash": None,
                            "error": "Could not fetch seqno — wallet may not be deployed yet"}

                logger.info(f"Final seqno={seqno}, to={to_address}, amount={amount_ton} TON")
                await asyncio.sleep(0.4)

                # 3. Build + sign transfer
                if derivation == "pytoniq":
                    transfer = wallet.create_transfer_message(
                        to_addr=to_address,
                        amount=to_nano(amount_ton, "ton"),
                        seqno=seqno,
                        payload=memo,
                        sign_func=lambda msg: _sign_with_priv_key(priv_key, msg),
                    )
                else:
                    transfer = wallet.create_transfer_message(
                        to_addr=to_address,
                        amount=to_nano(amount_ton, "ton"),
                        seqno=seqno,
                        payload=memo,
                    )

                boc = bytes_to_b64str(transfer["message"].to_boc(False))

                # 4. Broadcast
                result = await _tc_post(session, "sendBoc", {"boc": boc})
                logger.info(f"sendBoc result: {result}")

                if result.get("ok"):
                    # sendBoc doesn't always return hash — that's fine
                    tx_hash = ""
                    if isinstance(result.get("result"), dict):
                        tx_hash = result["result"].get("hash", "")
                    return {"success": True, "tx_hash": tx_hash, "error": None}
                else:
                    error = result.get("error") or str(result.get("result", result))
                    return {"success": False, "tx_hash": None, "error": error}

        except Exception as e:
            logger.exception("send_ton error")
            return {"success": False, "tx_hash": None, "error": str(e)}


async def validate_ton_address(address: str) -> bool:
    try:
        async with aiohttp.ClientSession() as s:
            data = await _tc_get(s, "detectAddress", {"address": address})
            return data.get("ok", False)
    except Exception:
        return False
