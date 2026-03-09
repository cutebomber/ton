"""
TON sender using toncenter v2 REST API + nacl signing.
No external wallet libraries needed beyond: pip install pynacl

Uses WalletV4R2 contract manually — works reliably on Windows.
"""

import aiohttp
import logging
import base64
import time
import struct

from config import TON_API_URL, TON_API_KEY, ADMIN_TON_WALLET, ADMIN_TON_MNEMONIC

logger = logging.getLogger(__name__)

HEADERS = {"Content-Type": "application/json"}
if TON_API_KEY:
    HEADERS["X-API-Key"] = TON_API_KEY

WALLET_ID = 698983191  # standard WalletV4R2 mainnet subwallet id


# ── Balance & seqno ───────────────────────────────────────────────────────────

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


# ── TON Cell builder (minimal, no deps) ──────────────────────────────────────

class BitString:
    def __init__(self, capacity=1023):
        self.bits = []

    def write_bit(self, b):
        self.bits.append(int(bool(b)))

    def write_uint(self, val, length):
        for i in range(length - 1, -1, -1):
            self.write_bit((val >> i) & 1)

    def write_bytes(self, data: bytes):
        for byte in data:
            self.write_uint(byte, 8)

    def to_bytes(self):
        bits = self.bits[:]
        # pad to byte boundary
        while len(bits) % 8 != 0:
            bits.append(0)
        return bytes(
            int("".join(str(b) for b in bits[i:i+8]), 2)
            for i in range(0, len(bits), 8)
        ), len(self.bits)


class Cell:
    def __init__(self):
        self.bs = BitString()
        self.refs = []

    def write_bit(self, b):       self.bs.write_bit(b)
    def write_uint(self, v, l):   self.bs.write_uint(v, l)
    def write_bytes(self, d):     self.bs.write_bytes(d)
    def add_ref(self, cell):      self.refs.append(cell)

    def write_coins(self, nano: int):
        # Coins = VarUInteger 16
        if nano == 0:
            self.write_uint(0, 4)
        else:
            byte_len = (nano.bit_length() + 7) // 8
            self.write_uint(byte_len, 4)
            self.write_bytes(nano.to_bytes(byte_len, "big"))

    def write_address(self, addr_str: str):
        """Write MsgAddressInt (std addr) from friendly or raw address."""
        raw = _addr_to_raw(addr_str)
        wc, addr_bytes = raw
        self.write_uint(0b10, 2)   # addr_std tag
        self.write_bit(0)          # no anycast
        self.write_uint(wc & 0xFF, 8)
        self.write_bytes(addr_bytes)

    def _hash(self):
        import hashlib
        data, bit_len = self.bs.to_bytes()
        # Build descriptor bytes
        d1 = (len(self.refs)) | (0 << 3)  # refs count, not exotic
        d2 = (bit_len // 8) + (1 if bit_len % 8 else 0)
        padding = (8 - bit_len % 8) % 8
        b = bytes([d1, d2]) + data
        for ref in self.refs:
            b += ref._hash()
        return hashlib.sha256(b).digest()

    def to_boc(self) -> bytes:
        """Serialize to BOC (bag of cells) bytes."""
        # Collect all cells
        cells = []
        self._collect(cells)
        idx = {id(c): i for i, c in enumerate(cells)}

        # Serialize each cell
        cell_bytes_list = []
        for c in cells:
            data, bit_len = c.bs.to_bytes()
            d1 = len(c.refs) | (0 << 3)
            full_bytes = bit_len // 8
            has_incomplete = bit_len % 8 != 0
            d2 = full_bytes * 2 + (1 if has_incomplete else 0)
            cell_data = bytes([d1, d2]) + data
            for ref in c.refs:
                cell_data += idx[id(ref)].to_bytes(1, "big")
            cell_bytes_list.append(cell_data)

        # BOC header
        magic = bytes.fromhex("b5ee9c72")
        total = len(cells)
        payload = b"".join(cell_bytes_list)

        # size_bytes = 1, off_bytes = 1
        header = (
            magic
            + bytes([0x01])           # flags
            + bytes([1])              # size_bytes
            + bytes([1])              # off_bytes
            + total.to_bytes(1, "big")
            + b"\x01"                 # roots count
            + b"\x00"                 # absent
            + len(payload).to_bytes(1, "big")
            + b"\x00"                 # root idx
        )
        return header + payload

    def _collect(self, result):
        for ref in self.refs:
            ref._collect(result)
        if self not in result:
            result.append(self)


def _addr_to_raw(addr: str):
    """Convert friendly TON address (UQ.../EQ...) to (workchain, 32 bytes)."""
    import base64
    # Remove prefix and decode base64url
    addr = addr.strip()
    padded = addr + "=" * (-len(addr) % 4)
    raw = base64.urlsafe_b64decode(padded)
    # raw: 1 byte flags, 1 byte workchain, 32 bytes addr, 2 bytes crc
    wc = struct.unpack("b", bytes([raw[1]]))[0]
    addr_bytes = raw[2:34]
    return wc, addr_bytes


# ── Send TON ──────────────────────────────────────────────────────────────────

async def send_ton(to_address: str, amount_ton: float, memo: str) -> dict:
    try:
        import nacl.signing
        import nacl.encoding
        import hashlib

        mnemonic_words = ADMIN_TON_MNEMONIC.split()
        priv_key = _mnemonic_to_privkey(mnemonic_words)
        seqno    = await _get_seqno(ADMIN_TON_WALLET)
        amount_nano = int(amount_ton * 1_000_000_000)
        expire_at   = int(time.time()) + 60

        # ── Comment cell ──────────────────────────────────────────────────────
        comment = Cell()
        comment.write_uint(0, 32)
        comment.write_bytes(memo.encode("utf-8"))

        # ── Internal message ───────────────────────────────────────────────────
        int_msg = Cell()
        int_msg.write_uint(0x10, 6)       # no-bounce flag
        int_msg.write_address(to_address)
        int_msg.write_coins(amount_nano)
        int_msg.write_uint(0, 107)        # ihr_disabled, bounce, etc.
        int_msg.write_bit(0)              # no state_init
        int_msg.write_bit(1)              # body as ref
        int_msg.add_ref(comment)

        # ── Wallet V4R2 body ───────────────────────────────────────────────────
        body = Cell()
        body.write_uint(WALLET_ID, 32)
        body.write_uint(expire_at, 32)
        body.write_uint(seqno, 32)
        body.write_uint(0, 8)             # op = 0 (simple transfer)
        body.write_uint(3, 8)             # send mode 3
        body.add_ref(int_msg)

        # ── Sign body hash ────────────────────────────────────────────────────
        body_hash = body._hash()
        signing_key = nacl.signing.SigningKey(priv_key)
        signed      = signing_key.sign(body_hash)
        signature   = signed.signature   # 64 bytes

        # ── Signed message ────────────────────────────────────────────────────
        signed_msg = Cell()
        signed_msg.write_bytes(signature)
        # Copy body bits
        for bit in body.bs.bits:
            signed_msg.write_bit(bit)
        for ref in body.refs:
            signed_msg.add_ref(ref)

        # ── External message ──────────────────────────────────────────────────
        ext = Cell()
        ext.write_uint(0b10, 2)           # ext_in_msg_info
        ext.write_uint(0b00, 2)           # src = addr_none
        ext.write_address(ADMIN_TON_WALLET)
        ext.write_coins(0)                # import_fee = 0
        ext.write_bit(0)                  # no state_init
        ext.write_bit(1)                  # body as ref
        ext.add_ref(signed_msg)

        boc_b64 = base64.b64encode(ext.to_boc()).decode()

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


def _mnemonic_to_privkey(words: list) -> bytes:
    """Derive ed25519 private key from TON 24-word mnemonic."""
    import hmac as _hmac
    import hashlib

    password = b""
    entropy  = " ".join(words).encode("utf-8")

    # PBKDF2 with HMAC-SHA512
    seed = hashlib.pbkdf2_hmac(
        "sha512",
        entropy,
        b"TON default seed",
        iterations=100000,
        dklen=64,
    )
    # Use first 32 bytes as ed25519 seed
    return seed[:32]


async def validate_ton_address(address: str) -> bool:
    try:
        url = f"{TON_API_URL}/detectAddress"
        async with aiohttp.ClientSession() as s:
            async with s.get(url, params={"address": address}, headers=HEADERS) as r:
                data = await r.json(content_type=None)
                return data.get("ok", False)
    except Exception:
        return False
