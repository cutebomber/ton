"""
Multi-wallet manager — rotation logic for TON sends.
Wallets are stored in DB and rotated round-robin.
"""

import asyncio
import logging
from typing import Optional

import database as db
from config import TON_SEND_AMOUNT

logger = logging.getLogger(__name__)

# Per-wallet locks — prevents seqno conflicts within same wallet
_wallet_locks: dict[int, asyncio.Lock] = {}

def _get_lock(wallet_id: int) -> asyncio.Lock:
    if wallet_id not in _wallet_locks:
        _wallet_locks[wallet_id] = asyncio.Lock()
    return _wallet_locks[wallet_id]


async def get_next_wallet() -> Optional[dict]:
    """
    Returns the next available active wallet with sufficient balance.
    Fetches live balance from chain — does not rely on cached DB value.
    Uses round-robin via last_used_at timestamp.
    """
    import aiohttp
    from ton import _tc_get

    wallets = db.get_active_wallets()
    if not wallets:
        return None

    # Sort by last_used_at ascending (round-robin)
    wallets.sort(key=lambda w: w["last_used_at"] or 0)

    for w in wallets:
        try:
            async with aiohttp.ClientSession() as s:
                data = await _tc_get(s, "getAddressBalance", {"address": w["address"]})
                if data.get("ok"):
                    balance = int(data["result"]) / 1e9
                    db.update_wallet_balance(w["id"], balance)
                    w["balance_ton"] = balance
                    if balance >= TON_SEND_AMOUNT + 0.015:
                        logger.info(f"Selected wallet #{w['id']} ({w['label']}) — {balance:.4f} TON")
                        return w
                    else:
                        logger.warning(f"Wallet #{w['id']} ({w['label']}) low: {balance:.4f} TON — skipping")
        except Exception as e:
            logger.warning(f"Could not check balance for wallet #{w['id']}: {e}")

    logger.warning("No sender wallets with sufficient balance found!")
    return None


async def send_ton_from_wallet(wallet: dict, to_address: str, amount_ton: float, memo: str) -> dict:
    """Send TON from a specific wallet. Uses per-wallet lock."""
    from tonsdk.utils import to_nano, bytes_to_b64str
    import aiohttp
    from ton import _tc_get, _tc_post, HEADERS

    wallet_id = wallet["id"]
    lock      = _get_lock(wallet_id)

    async with lock:
        try:
            words = wallet["mnemonic"].strip().split()

            # Key derivation
            try:
                from pytoniq_core.crypto.keys import mnemonic_to_private_key
                from tonsdk.contract.wallet import WalletV4ContractR2
                pub_key, priv_key = mnemonic_to_private_key(words)
                w       = WalletV4ContractR2(options={"public_key": pub_key, "wc": 0})
                sender  = w.address.to_string(True, True, False)
                derivation = "pytoniq"
            except Exception as e:
                logger.warning(f"pytoniq failed for wallet #{wallet_id}: {e}, trying tonsdk")
                from tonsdk.contract.wallet import Wallets, WalletVersionEnum
                _, pub_key, priv_key, w = Wallets.from_mnemonics(words, WalletVersionEnum.v4r2, workchain=0)
                sender     = w.address.to_string(True, True, False)
                derivation = "tonsdk"

            import nacl.signing
            def sign_func(msg): return bytes(nacl.signing.SigningKey(priv_key).sign(msg).signature)

            async with aiohttp.ClientSession() as session:
                # Check balance
                bal_data = await _tc_get(session, "getAddressBalance", {"address": sender})
                balance  = int(bal_data.get("result", 0)) / 1e9 if bal_data.get("ok") else 0.0

                if balance < amount_ton + 0.015:
                    db.update_wallet_balance(wallet_id, balance)
                    return {"success": False, "tx_hash": None,
                            "error": f"Wallet #{wallet_id} low balance: {balance:.5f} TON"}

                await asyncio.sleep(0.4)

                # Get seqno
                seqno = None
                wi    = await _tc_get(session, "getWalletInformation", {"address": sender})
                try:
                    if wi.get("ok") and wi["result"].get("seqno") is not None:
                        seqno = int(wi["result"]["seqno"])
                except Exception:
                    pass

                if seqno is None:
                    return {"success": False, "tx_hash": None,
                            "error": f"Could not get seqno for wallet #{wallet_id}"}

                await asyncio.sleep(0.4)

                # Build + sign
                if derivation == "pytoniq":
                    transfer = w.create_transfer_message(
                        to_addr=to_address,
                        amount=to_nano(amount_ton, "ton"),
                        seqno=seqno,
                        payload=memo,
                        sign_func=sign_func,
                    )
                else:
                    transfer = w.create_transfer_message(
                        to_addr=to_address,
                        amount=to_nano(amount_ton, "ton"),
                        seqno=seqno,
                        payload=memo,
                    )

                boc    = bytes_to_b64str(transfer["message"].to_boc(False))
                result = await _tc_post(session, "sendBoc", {"boc": boc})
                logger.info(f"Wallet #{wallet_id} sendBoc: {result}")

                if result.get("ok"):
                    tx_hash = ""
                    if isinstance(result.get("result"), dict):
                        tx_hash = result["result"].get("hash", "")

                    # Wait for seqno to increment
                    for _ in range(10):
                        await asyncio.sleep(3)
                        wi2 = await _tc_get(session, "getWalletInformation", {"address": sender})
                        try:
                            if int(wi2["result"].get("seqno") or 0) > seqno:
                                break
                        except Exception:
                            pass

                    # Update wallet usage + balance
                    db.update_wallet_balance(wallet_id, balance - amount_ton - 0.005)
                    db.update_wallet_last_used(wallet_id)

                    return {"success": True, "tx_hash": tx_hash, "error": None}
                else:
                    error = result.get("error") or str(result.get("result", result))
                    return {"success": False, "tx_hash": None, "error": error}

        except Exception as e:
            logger.exception(f"Wallet #{wallet_id} send error")
            return {"success": False, "tx_hash": None, "error": str(e)}
