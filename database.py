import sqlite3
from config import DB_PATH


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    # Users
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            username TEXT,
            balance_usd REAL DEFAULT 0.0,
            registered_at INTEGER DEFAULT (strftime('%s','now'))
        )
    """)

    # Deposits via OxaPay
    c.execute("""
        CREATE TABLE IF NOT EXISTS deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            currency TEXT NOT NULL,
            amount_crypto REAL NOT NULL,
            amount_usd REAL DEFAULT 0.0,
            invoice_id TEXT,
            status TEXT DEFAULT 'pending',   -- pending | confirmed | expired
            created_at INTEGER DEFAULT (strftime('%s','now')),
            confirmed_at INTEGER
        )
    """)

    # Promo orders submitted by users
    c.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            username TEXT,
            memo_text TEXT NOT NULL,
            total_addresses INTEGER NOT NULL,
            total_cost_usd REAL NOT NULL,
            status TEXT DEFAULT 'pending',   -- pending | processing | completed | failed
            created_at INTEGER DEFAULT (strftime('%s','now')),
            completed_at INTEGER
        )
    """)

    # Individual target addresses per order
    c.execute("""
        CREATE TABLE IF NOT EXISTS order_targets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            address TEXT NOT NULL,
            tx_hash TEXT,
            status TEXT DEFAULT 'pending',   -- pending | sent | failed
            FOREIGN KEY(order_id) REFERENCES orders(id)
        )
    """)

    conn.commit()
    conn.close()
    print("✅ Database initialised.")


# ── User helpers ──────────────────────────────────────────────────────────────

def upsert_user(telegram_id: int, username: str):
    conn = get_conn()
    conn.execute("""
        INSERT INTO users (telegram_id, username)
        VALUES (?, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET username=excluded.username
    """, (telegram_id, username))
    conn.commit()
    conn.close()


def get_user(telegram_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
    conn.close()
    return row


def get_user_balance(telegram_id: int) -> float:
    conn = get_conn()
    row = conn.execute("SELECT balance_usd FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
    conn.close()
    return row["balance_usd"] if row else 0.0


def update_user_balance(telegram_id: int, delta_usd: float):
    conn = get_conn()
    conn.execute(
        "UPDATE users SET balance_usd=balance_usd+? WHERE telegram_id=?",
        (delta_usd, telegram_id)
    )
    conn.commit()
    conn.close()


# ── Deposit helpers ───────────────────────────────────────────────────────────

def create_deposit(telegram_id: int, currency: str, amount_crypto: float, invoice_id: str = None):
    conn = get_conn()
    conn.execute("""
        INSERT INTO deposits (telegram_id, currency, amount_crypto, invoice_id)
        VALUES (?, ?, ?, ?)
    """, (telegram_id, currency, amount_crypto, invoice_id))
    conn.commit()
    conn.close()


def get_deposit_by_invoice_id(invoice_id: str):
    conn = get_conn()
    row = conn.execute("SELECT * FROM deposits WHERE invoice_id=?", (invoice_id,)).fetchone()
    conn.close()
    return row


def confirm_deposit_by_invoice(invoice_id: str, amount_usd: float):
    conn = get_conn()
    conn.execute("""
        UPDATE deposits
        SET status='confirmed',
            amount_usd=?,
            confirmed_at=strftime('%s','now')
        WHERE invoice_id=?
    """, (amount_usd, invoice_id))
    conn.commit()
    conn.close()


def reject_deposit(deposit_id: int):
    conn = get_conn()
    conn.execute("UPDATE deposits SET status='expired' WHERE id=?", (deposit_id,))
    conn.commit()
    conn.close()


def get_all_pending_deposits():
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM deposits WHERE status='pending' ORDER BY created_at"
    ).fetchall()
    conn.close()
    return rows


def get_user_deposits(telegram_id: int):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM deposits WHERE telegram_id=? ORDER BY created_at DESC LIMIT 10",
        (telegram_id,)
    ).fetchall()
    conn.close()
    return rows


# ── Order helpers ─────────────────────────────────────────────────────────────

def create_order(telegram_id: int, username: str, memo_text: str,
                 addresses: list, total_cost_usd: float) -> int:
    conn = get_conn()
    cur = conn.execute("""
        INSERT INTO orders (telegram_id, username, memo_text, total_addresses, total_cost_usd)
        VALUES (?, ?, ?, ?, ?)
    """, (telegram_id, username, memo_text, len(addresses), total_cost_usd))
    order_id = cur.lastrowid
    conn.executemany(
        "INSERT INTO order_targets (order_id, address) VALUES (?, ?)",
        [(order_id, addr) for addr in addresses]
    )
    conn.commit()
    conn.close()
    return order_id


def get_pending_orders():
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM orders WHERE status='pending' ORDER BY created_at"
    ).fetchall()
    conn.close()
    return rows


def get_order(order_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    conn.close()
    return row


def get_order_targets(order_id: int):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM order_targets WHERE order_id=? AND status='pending'",
        (order_id,)
    ).fetchall()
    conn.close()
    return rows


def set_order_status(order_id: int, status: str):
    conn = get_conn()
    if status == "completed":
        conn.execute(
            "UPDATE orders SET status=?, completed_at=strftime('%s','now') WHERE id=?",
            (status, order_id)
        )
    else:
        conn.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))
    conn.commit()
    conn.close()


def update_target(target_id: int, tx_hash: str, status: str):
    conn = get_conn()
    conn.execute(
        "UPDATE order_targets SET tx_hash=?, status=? WHERE id=?",
        (tx_hash, status, target_id)
    )
    conn.commit()
    conn.close()


def get_order_targets_all(order_id: int):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM order_targets WHERE order_id=?", (order_id,)
    ).fetchall()
    conn.close()
    return rows


def get_user_orders(telegram_id: int):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM orders WHERE telegram_id=? ORDER BY created_at DESC",
        (telegram_id,)
    ).fetchall()
    conn.close()
    return rows


# ── Admin stats ───────────────────────────────────────────────────────────────

def get_admin_stats():
    conn = get_conn()
    stats = {
        "total_users":     conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "total_deposits":  conn.execute("SELECT COUNT(*) FROM deposits WHERE status='confirmed'").fetchone()[0],
        "total_orders":    conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
        "pending_orders":  conn.execute("SELECT COUNT(*) FROM orders WHERE status='pending'").fetchone()[0],
        "total_sent":      conn.execute("SELECT COUNT(*) FROM order_targets WHERE status='sent'").fetchone()[0],
        "pending_deposits":conn.execute("SELECT COUNT(*) FROM deposits WHERE status='pending'").fetchone()[0],
    }
    conn.close()
    return stats
