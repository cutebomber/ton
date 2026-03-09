"""
TON transaction sender using pytoniq-core + toncenter v2 API.

pytoniq-core handles wallet building/signing.
toncenter broadcasts the BOC and returns the tx hash.

Install: pip install pytoniq-core
"""

import aiohttp
import logging
from config import TON_API_URL, TON_API_KEY, ADMIN_TON_WALLET, ADMIN_TON_MNEMONIC

logger = logging.getLogger(__name__)

HEADERS = {"X-API-Key": TON_API_KEY, "Content-Type": "application/json"} if TON_API_KEY else {"Content-Type": "application/json"}


async def get_wallet_balance(address: str) -> float:
    """Return wallet balance in TON."""
    try:
        url = f"{TON_API_URL}/getAddressBalance"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params={"address": address}, headers=HEADERS) as r:
                data = await r.json(content_type=None)
                if data.get("ok"):
                    return int(data["result"]) / 1e9
    except Exception as e:
        logger.error(f"Balance check failed: {e}")
    return 0.0


async def _get_seqno(address: str) -> int:
    """Get current seqno for the wallet."""
    try:
        url = f"{TON_API_URL}/runGetMethod"
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json={"address": address, "method": "seqno", "stack": []},
                headers=HEADERS,
            ) as r:
                data = await r.json(content_type=None)
                if data.get("ok"):
                    stack = data["result"].get("stack", [])
                    if stack:
                        # stack item is ["num", "0x0"] or ["num", "1"]
                        val = stack[0][1]
                        return int(val, 16) if str(val).startswith("0x") else int(val)
    except Exception as e:
        logger.warning(f"seqno fetch failed: {e}")
    return 0


async def send_ton(to_address: str, amount_ton: float, memo: str) -> dict:
    """
    Sign and broadcast a TON transfer with a text memo.
    Returns {"success": bool, "tx_hash": str|None, "error": str|None}
    """
    try:
        from pytoniq_core import WalletMessage
        from pytoniq_core.crypto.keys import mnemonic_to_private_key
        from pytoniq_core.boc import Cell, begin_cell
        from pytoniq_core.tlb.custom.wallet import WalletV4R2
        import base64

        mnemonic_words = ADMIN_TON_MNEMONIC.split()

        # Derive keys
        _, priv_key = mnemonic_to_private_key(mnemonic_words)

        # Build wallet
        wallet = WalletV4R2.from_private_key(priv_key, workchain=0)

        seqno = await _get_seqno(ADMIN_TON_WALLET)

        # Build comment cell
        comment_cell = (
            begin_cell()
            .store_uint(0, 32)
            .store_string(memo)
            .end_cell()
        )

        # Amount in nanotons
        amount_nano = int(amount_ton * 1e9)

        # Build and sign transfer
        boc = wallet.create_transfer(
            destination=to_address,
            amount=amount_nano,
            seqno=seqno,
            payload=comment_cell,
        )

        boc_b64 = base64.b64encode(boc).decode()

        # Broadcast
        url = f"{TON_API_URL}/sendBocReturnHash"
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json={"boc": boc_b64},
                headers=HEADERS,
            ) as r:
                resp = await r.json(content_type=None)
                if resp.get("ok"):
                    tx_hash = resp["result"].get("hash", "")
                    return {"success": True, "tx_hash": tx_hash, "error": None}
                else:
                    error = resp.get("error") or str(resp)
                    return {"success": False, "tx_hash": None, "error": error}

    except ImportError:
        # Fallback to tonsdk if pytoniq-core not installed
        return await _send_ton_tonsdk(to_address, amount_ton, memo)
    except Exception as e:
        logger.error(f"send_ton error: {e}", exc_info=True)
        return {"success": False, "tx_hash": None, "error": str(e)}


async def _send_ton_tonsdk(to_address: str, amount_ton: float, memo: str) -> dict:
    """Fallback using tonsdk."""
    try:
        from tonsdk.contract.wallet import Wallets, WalletVersionEnum
        from tonsdk.utils import to_nano, bytes_to_b64str
        import base64

        mnemonic_words = ADMIN_TON_MNEMONIC.split()

        _mnemonics, _pub_k, _priv_k, wallet = Wallets.from_mnemonics(
            mnemonic_words, WalletVersionEnum.v4r2, workchain=0
        )

        seqno = await _get_seqno(ADMIN_TON_WALLET)

        transfer = wallet.create_transfer_message(
            to_addr=to_address,
            amount=to_nano(amount_ton, "ton"),
            seqno=seqno,
            payload=memo,
        )

        boc = bytes_to_b64str(transfer["message"].to_boc(False))

        url = f"{TON_API_URL}/sendBocReturnHash"
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json={"boc": boc},
                headers=HEADERS,
            ) as r:
                resp = await r.json(content_type=None)
                if resp.get("ok"):
                    tx_hash = resp["result"].get("hash", "")
                    return {"success": True, "tx_hash": tx_hash, "error": None}
                else:
                    return {"success": False, "tx_hash": None, "error": resp.get("error", str(resp))}

    except Exception as e:
        logger.error(f"tonsdk fallback error: {e}", exc_info=True)
        return {"success": False, "tx_hash": None, "error": str(e)}


async def validate_ton_address(address: str) -> bool:
    """Check if a TON address is valid."""
    try:
        url = f"{TON_API_URL}/detectAddress"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params={"address": address}, headers=HEADERS) as r:
                data = await r.json(content_type=None)
                return data.get("ok", False)
    except Exception:
        return False
