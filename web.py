"""
FastAPI admin dashboard — view stats, users, orders, deposits.
Run with: uvicorn web:app --host 0.0.0.0 --port 8000
"""

import hashlib, secrets
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Request, Form, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse

import database as db
from ton import get_wallet_balance
from config import SECRET_KEY, ADMIN_TON_WALLET, TON_SEND_AMOUNT, PRICE_PER_ADDRESS_USD

app = FastAPI(title="TON Ad Bot Admin")

admin_sessions: set[str] = set()
ADMIN_PASSWORD_HASH = hashlib.sha256(b"admin1234").hexdigest()  # change this!

def hash_pw(pw): return hashlib.sha256(pw.encode()).hexdigest()
def make_token(): return secrets.token_hex(24)
def is_admin(session): return session in admin_sessions if session else False


def page(title, body):
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — TON Ad Bot</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',sans-serif;background:#0f1117;color:#e8eaf6;min-height:100vh}}
nav{{background:#1a1d2e;padding:14px 32px;display:flex;align-items:center;gap:24px;border-bottom:1px solid #2a2d3e}}
nav a{{color:#7c8cf8;text-decoration:none;font-weight:600}}
nav a:hover{{color:#a5b4fc}}
.brand{{font-size:20px;font-weight:700;color:#fff;margin-right:auto}}
.container{{max-width:1000px;margin:40px auto;padding:0 24px}}
h1{{font-size:26px;margin-bottom:24px;color:#fff}}
h2{{font-size:18px;margin-bottom:14px;color:#c7d2fe}}
.card{{background:#1a1d2e;border:1px solid #2a2d3e;border-radius:12px;padding:24px;margin-bottom:20px}}
label{{display:block;margin-bottom:6px;color:#94a3b8;font-size:14px}}
input{{width:100%;padding:10px 14px;border-radius:8px;border:1px solid #374151;background:#0f1117;color:#e8eaf6;font-size:15px;margin-bottom:16px}}
.btn{{display:inline-block;padding:10px 22px;border-radius:8px;border:none;cursor:pointer;font-size:15px;font-weight:600}}
.btn-primary{{background:#7c8cf8;color:#fff}}
.btn-sm{{padding:5px 12px;font-size:13px}}
table{{width:100%;border-collapse:collapse}}
th,td{{padding:10px 14px;text-align:left;border-bottom:1px solid #2a2d3e;font-size:13px}}
th{{color:#94a3b8;font-weight:600}}
.badge{{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:600}}
.badge-pending{{background:#713f12;color:#fde68a}}
.badge-processing{{background:#1e3a5f;color:#93c5fd}}
.badge-completed{{background:#166534;color:#bbf7d0}}
.badge-failed{{background:#450a0a;color:#fca5a5}}
.badge-confirmed{{background:#166534;color:#bbf7d0}}
.badge-expired{{background:#374151;color:#9ca3af}}
.stat-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin-bottom:24px}}
.stat{{background:#1a1d2e;border:1px solid #2a2d3e;border-radius:10px;padding:18px;text-align:center}}
.stat .val{{font-size:28px;font-weight:700;color:#7c8cf8}}
.stat .lbl{{font-size:12px;color:#64748b;margin-top:4px}}
.alert-error{{background:#450a0a;border:1px solid #7f1d1d;color:#fca5a5;padding:12px 18px;border-radius:8px;margin-bottom:16px}}
</style></head>
<body>
<nav>
  <span class="brand">💎 TON Ad Bot</span>
  <a href="/admin">Dashboard</a>
  <a href="/admin/orders">Orders</a>
  <a href="/admin/deposits">Deposits</a>
  <a href="/admin/users">Users</a>
  <a href="/admin/logout">Logout</a>
</nav>
<div class="container"><h1>{title}</h1>{body}</div>
</body></html>"""


def badge(status):
    return f'<span class="badge badge-{status}">{status}</span>'


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.get("/admin/login", response_class=HTMLResponse)
async def login_get(error: str = ""):
    err = f'<div class="alert-error">{error}</div>' if error else ""
    body = f"""{err}<div class="card"><h2>Admin Login</h2>
    <form method="post" action="/admin/login">
      <label>Password</label><input name="password" type="password" required>
      <button class="btn btn-primary">Login</button>
    </form></div>"""
    return page("Login", body)


@app.post("/admin/login")
async def login_post(password: str = Form(...)):
    if hash_pw(password) != ADMIN_PASSWORD_HASH:
        return RedirectResponse("/admin/login?error=Wrong+password", status_code=303)
    token = make_token()
    admin_sessions.add(token)
    resp = RedirectResponse("/admin", status_code=303)
    resp.set_cookie("session", token, httponly=True, max_age=3600 * 8)
    return resp


@app.get("/admin/logout")
async def logout(session: Optional[str] = Cookie(default=None)):
    admin_sessions.discard(session)
    resp = RedirectResponse("/admin/login", status_code=303)
    resp.delete_cookie("session")
    return resp


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.get("/admin", response_class=HTMLResponse)
async def dashboard(session: Optional[str] = Cookie(default=None)):
    if not is_admin(session):
        return RedirectResponse("/admin/login", status_code=303)

    stats   = db.get_admin_stats()
    balance = await get_wallet_balance(ADMIN_TON_WALLET)

    items = [
        ("Users",            stats["total_users"]),
        ("Confirmed Deposits", stats["total_deposits"]),
        ("Total Orders",     stats["total_orders"]),
        ("Pending Orders",   stats["pending_orders"]),
        ("TXs Sent",         stats["total_sent"]),
        ("Pending Deposits", stats["pending_deposits"]),
        ("Wallet Balance",   f"{balance:.4f} TON"),
    ]
    stats_html = "".join(
        f'<div class="stat"><div class="val">{v}</div><div class="lbl">{l}</div></div>'
        for l, v in items
    )
    body = f'<div class="stat-grid">{stats_html}</div>'
    return page("Dashboard", body)


# ── Orders ────────────────────────────────────────────────────────────────────

@app.get("/admin/orders", response_class=HTMLResponse)
async def admin_orders(session: Optional[str] = Cookie(default=None)):
    if not is_admin(session):
        return RedirectResponse("/admin/login", status_code=303)

    conn = db.get_conn()
    orders = conn.execute(
        "SELECT * FROM orders ORDER BY created_at DESC LIMIT 100"
    ).fetchall()
    conn.close()

    rows = "".join(f"""<tr>
        <td>#{o['id']}</td>
        <td>@{o['username'] or 'N/A'}</td>
        <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{o['memo_text']}</td>
        <td>{o['total_addresses']}</td>
        <td>${o['total_cost_usd']}</td>
        <td>{badge(o['status'])}</td>
        <td>{datetime.fromtimestamp(o['created_at']).strftime('%m-%d %H:%M')}</td>
        <td><a href="/admin/orders/{o['id']}" class="btn btn-primary btn-sm">View</a></td>
    </tr>""" for o in orders)

    body = f"""<div class="card"><h2>All Orders</h2>
    <table><tr><th>#</th><th>User</th><th>Memo</th><th>Addrs</th><th>Cost</th><th>Status</th><th>Date</th><th></th></tr>
    {rows or '<tr><td colspan="8" style="color:#64748b">No orders yet.</td></tr>'}
    </table></div>"""
    return page("Orders", body)


@app.get("/admin/orders/{order_id}", response_class=HTMLResponse)
async def admin_order_detail(order_id: int, session: Optional[str] = Cookie(default=None)):
    if not is_admin(session):
        return RedirectResponse("/admin/login", status_code=303)

    order   = db.get_order(order_id)
    targets = db.get_order_targets_all(order_id)

    if not order:
        return page("Not Found", "<p>Order not found.</p>")

    rows = "".join(f"""<tr>
        <td style="font-family:monospace;font-size:12px">{t['address']}</td>
        <td>{badge(t['status'])}</td>
        <td style="font-family:monospace;font-size:11px">
          {"<a href='https://tonscan.org/tx/"+t['tx_hash']+"' target='_blank'>"+t['tx_hash'][:16]+"...</a>" if t['tx_hash'] else 'N/A'}
        </td>
    </tr>""" for t in targets)

    sent   = sum(1 for t in targets if t["status"] == "sent")
    failed = sum(1 for t in targets if t["status"] == "failed")

    body = f"""<div class="card">
      <h2>Order #{order['id']} — @{order['username']} — {badge(order['status'])}</h2>
      <p style="margin:12px 0;color:#94a3b8">📝 {order['memo_text']}</p>
      <p style="color:#94a3b8">✅ Sent: {sent} &nbsp; ❌ Failed: {failed} &nbsp; 💵 ${order['total_cost_usd']}</p>
    </div>
    <div class="card"><h2>Targets</h2>
    <table><tr><th>Address</th><th>Status</th><th>TX Hash</th></tr>
    {rows}</table></div>"""
    return page(f"Order #{order_id}", body)


# ── Deposits ──────────────────────────────────────────────────────────────────

@app.get("/admin/deposits", response_class=HTMLResponse)
async def admin_deposits(session: Optional[str] = Cookie(default=None)):
    if not is_admin(session):
        return RedirectResponse("/admin/login", status_code=303)

    conn = db.get_conn()
    deps = conn.execute(
        "SELECT d.*, u.username FROM deposits d LEFT JOIN users u ON d.telegram_id=u.telegram_id ORDER BY d.created_at DESC LIMIT 100"
    ).fetchall()
    conn.close()

    rows = "".join(f"""<tr>
        <td>{d['id']}</td>
        <td>@{d['username'] or d['telegram_id']}</td>
        <td>{d['amount_crypto']} {d['currency']}</td>
        <td>${d['amount_usd']:.4f}</td>
        <td>{badge(d['status'])}</td>
        <td style="font-family:monospace;font-size:11px">{d['invoice_id'] or 'N/A'}</td>
        <td>{datetime.fromtimestamp(d['created_at']).strftime('%m-%d %H:%M')}</td>
    </tr>""" for d in deps)

    body = f"""<div class="card"><h2>Deposits</h2>
    <table><tr><th>#</th><th>User</th><th>Amount</th><th>USD</th><th>Status</th><th>Invoice</th><th>Date</th></tr>
    {rows or '<tr><td colspan="7" style="color:#64748b">No deposits yet.</td></tr>'}
    </table></div>"""
    return page("Deposits", body)


# ── Users ─────────────────────────────────────────────────────────────────────

@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users(session: Optional[str] = Cookie(default=None)):
    if not is_admin(session):
        return RedirectResponse("/admin/login", status_code=303)

    conn = db.get_conn()
    users = conn.execute("SELECT * FROM users ORDER BY registered_at DESC").fetchall()
    conn.close()

    rows = "".join(f"""<tr>
        <td>{u['telegram_id']}</td>
        <td>@{u['username'] or 'N/A'}</td>
        <td><strong>${u['balance_usd']:.4f}</strong></td>
        <td>{datetime.fromtimestamp(u['registered_at']).strftime('%Y-%m-%d')}</td>
    </tr>""" for u in users)

    body = f"""<div class="card"><h2>Users</h2>
    <table><tr><th>Telegram ID</th><th>Username</th><th>Balance</th><th>Joined</th></tr>
    {rows or '<tr><td colspan="4" style="color:#64748b">No users yet.</td></tr>'}
    </table></div>"""
    return page("Users", body)