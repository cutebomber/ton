import hashlib, secrets
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, Request, Form, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
import database as db
from ton import get_wallet_balance
from config import SECRET_KEY, ADMIN_TON_WALLET, TON_SEND_AMOUNT, PRICE_PER_ADDRESS_USD, TELEGRAM_BOT_TOKEN

app = FastAPI(title="TON Ad Bot Admin")
admin_sessions: set[str] = set()
ADMIN_PASSWORD_HASH = hashlib.sha256(b"admin1234").hexdigest()

def hash_pw(pw): return hashlib.sha256(pw.encode()).hexdigest()
def make_token(): return secrets.token_hex(24)
def is_admin(s): return s in admin_sessions if s else False

CSS = """
:root{--bg:#0a0b0f;--card:#111318;--border:#1e2029;--accent:#6c63ff;--accent2:#4ecdc4;--text:#e8eaed;--muted:#6b7280;--success:#22c55e;--danger:#ef4444;--warn:#f59e0b}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;display:flex}
.sidebar{width:220px;background:var(--card);border-right:1px solid var(--border);padding:24px 0;position:fixed;height:100vh;display:flex;flex-direction:column;z-index:100}
.sidebar-logo{padding:0 20px 24px;border-bottom:1px solid var(--border);margin-bottom:16px}
.sidebar-logo .name{font-size:18px;font-weight:700;background:linear-gradient(135deg,var(--accent),var(--accent2));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.sidebar-logo .sub{font-size:11px;color:var(--muted);margin-top:2px}
.nav-item{display:flex;align-items:center;gap:10px;padding:10px 20px;color:var(--muted);text-decoration:none;font-size:14px;font-weight:500;transition:.15s;border-left:3px solid transparent}
.nav-item:hover,.nav-item.active{color:var(--text);background:rgba(108,99,255,.08);border-left-color:var(--accent)}
.nav-item .icon{width:18px;text-align:center}
.main{margin-left:220px;flex:1;padding:32px;max-width:1200px}
h1{font-size:24px;font-weight:700;margin-bottom:8px}
.page-sub{color:var(--muted);font-size:14px;margin-bottom:28px}
.stat-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:16px;margin-bottom:28px}
.stat{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:20px;position:relative;overflow:hidden}
.stat::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:linear-gradient(90deg,var(--accent),var(--accent2))}
.stat .val{font-size:28px;font-weight:700;margin-bottom:4px}
.stat .lbl{font-size:12px;color:var(--muted);font-weight:500}
.stat .icon{position:absolute;right:16px;top:50%;transform:translateY(-50%);font-size:28px;opacity:.15}
.card{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:24px;margin-bottom:20px}
.card-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:18px}
.card-title{font-size:15px;font-weight:600}
table{width:100%;border-collapse:collapse}
th{padding:10px 14px;text-align:left;font-size:12px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid var(--border)}
td{padding:11px 14px;font-size:13px;border-bottom:1px solid rgba(255,255,255,.04)}
tr:last-child td{border-bottom:none}
tr:hover td{background:rgba(255,255,255,.02)}
.badge{display:inline-flex;align-items:center;gap:4px;padding:3px 10px;border-radius:999px;font-size:11px;font-weight:600}
.badge-pending{background:rgba(245,158,11,.15);color:var(--warn)}
.badge-processing{background:rgba(108,99,255,.15);color:#a5b4fc}
.badge-completed{background:rgba(34,197,94,.15);color:var(--success)}
.badge-failed{background:rgba(239,68,68,.15);color:var(--danger)}
.badge-confirmed{background:rgba(34,197,94,.15);color:var(--success)}
.badge-expired{background:rgba(107,114,128,.15);color:var(--muted)}
.btn{display:inline-flex;align-items:center;gap:6px;padding:8px 18px;border-radius:8px;border:none;cursor:pointer;font-size:13px;font-weight:600;transition:.15s;text-decoration:none}
.btn-primary{background:var(--accent);color:#fff}
.btn-primary:hover{background:#5a52d5}
.btn-success{background:rgba(34,197,94,.2);color:var(--success);border:1px solid rgba(34,197,94,.3)}
.btn-success:hover{background:rgba(34,197,94,.3)}
.btn-sm{padding:5px 12px;font-size:12px}
.btn-danger{background:rgba(239,68,68,.15);color:var(--danger);border:1px solid rgba(239,68,68,.2)}
input,select{background:rgba(255,255,255,.05);border:1px solid var(--border);border-radius:8px;color:var(--text);padding:9px 13px;font-size:13px;outline:none;transition:.15s}
input:focus,select:focus{border-color:var(--accent);background:rgba(108,99,255,.05)}
.form-row{display:flex;gap:8px;align-items:center}
.alert{padding:12px 18px;border-radius:10px;margin-bottom:20px;font-size:14px}
.alert-error{background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.2);color:#fca5a5}
.wallet-box{background:rgba(108,99,255,.08);border:1px solid rgba(108,99,255,.2);border-radius:10px;padding:14px 18px;font-family:monospace;font-size:13px;color:#a5b4fc;word-break:break-all}
.chart-wrap{height:200px;position:relative}
.empty{text-align:center;padding:40px;color:var(--muted);font-size:14px}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
.tag{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;background:rgba(255,255,255,.06);color:var(--muted)}
"""

def shell(title, body, active="dashboard"):
    nav = [
        ("dashboard", "📊", "Dashboard", "/admin"),
        ("orders",    "📦", "Orders",    "/admin/orders"),
        ("deposits",  "💳", "Deposits",  "/admin/deposits"),
        ("users",     "👥", "Users",     "/admin/users"),
    ]
    nav_html = "".join(
        f'<a href="{href}" class="nav-item {"active" if active==k else ""}"><span class="icon">{ic}</span>{label}</a>'
        for k, ic, label, href in nav
    )
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — TON Bot Admin</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>{CSS}</style></head>
<body>
<nav class="sidebar">
  <div class="sidebar-logo">
    <div class="name">💎 TON Bot</div>
    <div class="sub">Admin Dashboard</div>
  </div>
  {nav_html}
  <div style="margin-top:auto;padding:16px 20px;border-top:1px solid var(--border)">
    <a href="/admin/logout" class="nav-item" style="padding:8px 0;border:none">🚪 Logout</a>
  </div>
</nav>
<main class="main">
  <h1>{title}</h1>
  {body}
</main>
</body></html>"""

def badge(status):
    dot = {"pending":"🟡","processing":"🔵","completed":"🟢","failed":"🔴","confirmed":"🟢","expired":"⚫"}.get(status,"⚪")
    return f'<span class="badge badge-{status}">{dot} {status}</span>'

def fmt_dt(ts):
    if not ts: return "—"
    return datetime.fromtimestamp(ts).strftime("%b %d, %H:%M")


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.get("/admin/login", response_class=HTMLResponse)
async def login_get(error: str = ""):
    err = f'<div class="alert alert-error">❌ {error}</div>' if error else ""
    body = f"""{err}
    <div style="max-width:380px;margin:60px auto">
    <div class="card">
      <div class="card-header"><span class="card-title">🔐 Admin Login</span></div>
      <form method="post" action="/admin/login">
        <div style="margin-bottom:14px"><input name="password" type="password" placeholder="Password" style="width:100%" required></div>
        <button class="btn btn-primary" style="width:100%">Sign In →</button>
      </form>
    </div></div>"""
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
    <style>{CSS} body{{display:block;background:var(--bg)}}</style></head>
    <body style="min-height:100vh;display:flex;align-items:center;justify-content:center">
    <div style="width:100%;max-width:400px;padding:20px">{body}</div></body></html>"""


@app.post("/admin/login")
async def login_post(password: str = Form(...)):
    if hash_pw(password) != ADMIN_PASSWORD_HASH:
        return RedirectResponse("/admin/login?error=Wrong+password", status_code=303)
    token = make_token()
    admin_sessions.add(token)
    resp = RedirectResponse("/admin", status_code=303)
    resp.set_cookie("session", token, httponly=True, max_age=3600*8)
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
    if not is_admin(session): return RedirectResponse("/admin/login", status_code=303)

    stats   = db.get_admin_stats()
    balance = await get_wallet_balance(ADMIN_TON_WALLET)

    # Chart data — orders per day last 7 days
    conn = db.get_conn()
    daily_orders = conn.execute("""
        SELECT date(created_at,'unixepoch') as d, COUNT(*) as n
        FROM orders GROUP BY d ORDER BY d DESC LIMIT 7
    """).fetchall()
    daily_deps = conn.execute("""
        SELECT date(created_at,'unixepoch') as d, COUNT(*) as n
        FROM deposits WHERE status='confirmed' GROUP BY d ORDER BY d DESC LIMIT 7
    """).fetchall()
    conn.close()

    order_labels = [r["d"] for r in reversed(daily_orders)]
    order_vals   = [r["n"] for r in reversed(daily_orders)]
    dep_labels   = [r["d"] for r in reversed(daily_deps)]
    dep_vals     = [r["n"] for r in reversed(daily_deps)]

    stat_items = [
        ("Total Users",     stats["total_users"],     "👥"),
        ("Total Orders",    stats["total_orders"],    "📦"),
        ("Pending Orders",  stats["pending_orders"],  "⏳"),
        ("TXs Sent",        stats["total_sent"],      "✅"),
        ("Deposits",        stats["total_deposits"],  "💳"),
        ("Wallet Balance",  f"{balance:.4f} TON",     "💎"),
    ]
    stats_html = "".join(
        f'<div class="stat"><div class="val">{v}</div><div class="lbl">{l}</div><div class="icon">{ic}</div></div>'
        for l, v, ic in stat_items
    )

    body = f"""
    <p class="page-sub">Live overview of your TON Promo Bot</p>
    <div class="stat-grid">{stats_html}</div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
      <div class="card">
        <div class="card-header"><span class="card-title">📦 Orders (7d)</span></div>
        <div class="chart-wrap"><canvas id="ordersChart"></canvas></div>
      </div>
      <div class="card">
        <div class="card-header"><span class="card-title">💳 Deposits (7d)</span></div>
        <div class="chart-wrap"><canvas id="depsChart"></canvas></div>
      </div>
    </div>

    <div class="card" style="margin-top:16px">
      <div class="card-header"><span class="card-title">💎 Admin Wallet</span></div>
      <div class="wallet-box">{ADMIN_TON_WALLET}</div>
      <div style="margin-top:10px;color:var(--muted);font-size:13px">Balance: <strong style="color:var(--text)">{balance:.6f} TON</strong></div>
    </div>

    <script>
    const chartOpts = (labels, data, color) => ({{
      type:'line',
      data:{{labels,datasets:[{{data,borderColor:color,backgroundColor:color+'22',fill:true,tension:.4,pointRadius:4,pointBackgroundColor:color}}]}},
      options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{display:false}}}},scales:{{x:{{grid:{{color:'#1e2029'}},ticks:{{color:'#6b7280',font:{{size:11}}}}}},y:{{grid:{{color:'#1e2029'}},ticks:{{color:'#6b7280',font:{{size:11}},stepSize:1}}}}}}}}
    }});
    new Chart(document.getElementById('ordersChart'), chartOpts({order_labels}, {order_vals}, '#6c63ff'));
    new Chart(document.getElementById('depsChart'),   chartOpts({dep_labels},   {dep_vals},   '#4ecdc4'));
    </script>"""
    return shell("Dashboard", body, "dashboard")


# ── Orders ────────────────────────────────────────────────────────────────────

@app.get("/admin/orders", response_class=HTMLResponse)
async def admin_orders(session: Optional[str] = Cookie(default=None), status: str = ""):
    if not is_admin(session): return RedirectResponse("/admin/login", status_code=303)

    conn = db.get_conn()
    if status:
        orders = conn.execute("SELECT * FROM orders WHERE status=? ORDER BY created_at DESC LIMIT 100", (status,)).fetchall()
    else:
        orders = conn.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT 100").fetchall()
    conn.close()

    filter_btns = "".join(
        f'<a href="/admin/orders{"?status="+s if s else ""}" class="btn btn-sm {"btn-primary" if status==s else ""}" style="{"" if status==s else "background:rgba(255,255,255,.05);color:var(--muted)"}">{s.capitalize() if s else "All"}</a> '
        for s in ["", "pending", "processing", "completed", "failed"]
    )

    rows = "".join(f"""<tr>
        <td><strong>#{o['id']}</strong></td>
        <td>@{o['username'] or '—'}</td>
        <td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--muted)">{o['memo_text']}</td>
        <td><span class="tag">{o['total_addresses']}</span></td>
        <td><strong>${o['total_cost_usd']}</strong></td>
        <td>{badge(o['status'])}</td>
        <td style="color:var(--muted)">{fmt_dt(o['created_at'])}</td>
        <td><a href="/admin/orders/{o['id']}" class="btn btn-sm btn-primary">View →</a></td>
    </tr>""" for o in orders)

    body = f"""
    <p class="page-sub">All promo orders and their delivery status</p>
    <div class="card">
      <div class="card-header">
        <span class="card-title">Orders</span>
        <div style="display:flex;gap:6px">{filter_btns}</div>
      </div>
      <table><tr><th>#</th><th>User</th><th>Memo</th><th>Addrs</th><th>Cost</th><th>Status</th><th>Date</th><th></th></tr>
      {rows or '<tr><td colspan="8" class="empty">No orders found.</td></tr>'}
      </table>
    </div>"""
    return shell("Orders", body, "orders")


@app.get("/admin/orders/{order_id}", response_class=HTMLResponse)
async def admin_order_detail(order_id: int, session: Optional[str] = Cookie(default=None)):
    if not is_admin(session): return RedirectResponse("/admin/login", status_code=303)

    order   = db.get_order(order_id)
    targets = db.get_order_targets_all(order_id)
    if not order: return shell("Not Found", "<p>Order not found.</p>", "orders")

    sent   = sum(1 for t in targets if t["status"] == "sent")
    failed = sum(1 for t in targets if t["status"] == "failed")
    total  = len(targets)
    pct    = round(sent/total*100) if total else 0

    rows = "".join(f"""<tr>
        <td style="font-family:monospace;font-size:12px">{t['address']}</td>
        <td>{badge(t['status'])}</td>
        <td style="font-family:monospace;font-size:11px">
          {"<a href='https://tonscan.org/tx/"+t['tx_hash']+"' target='_blank'>"+t['tx_hash'][:16]+"...</a>" if t['tx_hash'] else '<span style="color:var(--muted)">—</span>'}
        </td>
    </tr>""" for t in targets)

    body = f"""
    <p class="page-sub">Order #{order_id} details and transaction log</p>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-bottom:20px">
      <div class="stat"><div class="val">{sent}</div><div class="lbl">Sent</div><div class="icon">✅</div></div>
      <div class="stat"><div class="val">{failed}</div><div class="lbl">Failed</div><div class="icon">❌</div></div>
      <div class="stat"><div class="val">{pct}%</div><div class="lbl">Success Rate</div><div class="icon">📊</div></div>
    </div>
    <div class="card">
      <div class="card-header">
        <span class="card-title">Order Info</span>
        {badge(order['status'])}
      </div>
      <table>
        <tr><td style="color:var(--muted);width:140px">User</td><td>@{order['username'] or '—'}</td></tr>
        <tr><td style="color:var(--muted)">Memo</td><td>{order['memo_text']}</td></tr>
        <tr><td style="color:var(--muted)">Addresses</td><td>{order['total_addresses']}</td></tr>
        <tr><td style="color:var(--muted)">Cost</td><td>${order['total_cost_usd']}</td></tr>
        <tr><td style="color:var(--muted)">Created</td><td>{fmt_dt(order['created_at'])}</td></tr>
      </table>
    </div>
    <div class="card">
      <div class="card-header"><span class="card-title">Targets</span></div>
      <table><tr><th>Address</th><th>Status</th><th>TX Hash</th></tr>{rows}</table>
    </div>"""
    return shell(f"Order #{order_id}", body, "orders")


# ── Deposits ──────────────────────────────────────────────────────────────────

@app.get("/admin/deposits", response_class=HTMLResponse)
async def admin_deposits(session: Optional[str] = Cookie(default=None)):
    if not is_admin(session): return RedirectResponse("/admin/login", status_code=303)

    conn = db.get_conn()
    deps = conn.execute("""
        SELECT d.*, u.username FROM deposits d
        LEFT JOIN users u ON d.telegram_id=u.telegram_id
        ORDER BY d.created_at DESC LIMIT 100
    """).fetchall()
    conn.close()

    rows = "".join(f"""<tr>
        <td><strong>#{d['id']}</strong></td>
        <td>@{d['username'] or d['telegram_id']}</td>
        <td><strong>{d['amount_crypto']}</strong> <span class="tag">{d['currency']}</span></td>
        <td><strong>${d['amount_usd']:.4f}</strong></td>
        <td>{badge(d['status'])}</td>
        <td style="font-family:monospace;font-size:11px;color:var(--muted)">{(d['invoice_id'] or '—')[:20]}</td>
        <td style="color:var(--muted)">{fmt_dt(d['created_at'])}</td>
    </tr>""" for d in deps)

    body = f"""
    <p class="page-sub">All crypto deposits via OxaPay</p>
    <div class="card">
      <div class="card-header"><span class="card-title">Deposits</span></div>
      <table><tr><th>#</th><th>User</th><th>Amount</th><th>USD</th><th>Status</th><th>Invoice</th><th>Date</th></tr>
      {rows or '<tr><td colspan="7" class="empty">No deposits yet.</td></tr>'}
      </table>
    </div>"""
    return shell("Deposits", body, "deposits")


# ── Users ─────────────────────────────────────────────────────────────────────

@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users(session: Optional[str] = Cookie(default=None), q: str = ""):
    if not is_admin(session): return RedirectResponse("/admin/login", status_code=303)

    conn = db.get_conn()
    if q:
        users = conn.execute(
            "SELECT * FROM users WHERE username LIKE ? OR telegram_id LIKE ? ORDER BY balance_usd DESC",
            (f"%{q}%", f"%{q}%")
        ).fetchall()
    else:
        users = conn.execute("SELECT * FROM users ORDER BY balance_usd DESC").fetchall()
    conn.close()

    rows = "".join(f"""<tr>
        <td style="font-family:monospace;font-size:12px;color:var(--muted)">{u['telegram_id']}</td>
        <td><strong>@{u['username'] or '—'}</strong></td>
        <td><strong style="color:var(--success)">${u['balance_usd']:.4f}</strong></td>
        <td style="color:var(--muted)">{fmt_dt(u['registered_at'])}</td>
        <td>
          <form method="post" action="/admin/users/{u['telegram_id']}/add_balance" style="display:flex;gap:6px">
            <input name="amount" type="number" step="0.01" min="0.01" placeholder="USD" style="width:80px;padding:6px 10px">
            <button class="btn btn-success btn-sm">+ Add</button>
          </form>
        </td>
    </tr>""" for u in users)

    body = f"""
    <p class="page-sub">All registered users and their balances</p>
    <div class="card">
      <div class="card-header">
        <span class="card-title">Users <span class="tag">{len(users)}</span></span>
        <form method="get" style="display:flex;gap:8px">
          <input name="q" value="{q}" placeholder="Search username or ID..." style="width:220px">
          <button class="btn btn-primary btn-sm">Search</button>
        </form>
      </div>
      <table><tr><th>Telegram ID</th><th>Username</th><th>Balance</th><th>Joined</th><th>Add Balance</th></tr>
      {rows or '<tr><td colspan="5" class="empty">No users found.</td></tr>'}
      </table>
    </div>"""
    return shell("Users", body, "users")


@app.post("/admin/users/{telegram_id}/add_balance")
async def admin_add_balance(
    telegram_id: int,
    amount: float = Form(...),
    session: Optional[str] = Cookie(default=None),
):
    if not is_admin(session): return RedirectResponse("/admin/login", status_code=303)
    if amount > 0:
        db.update_user_balance(telegram_id, amount)
        try:
            import aiohttp as _aio
            msg = (
                f"💰 *Balance Added by Admin*\n\n"
                f"✅ `${amount:.2f} USD` has been credited to your account\\.\n"
                f"💰 Use 🚀 *New Promo* to launch a campaign\\!"
            )
            async with _aio.ClientSession() as s:
                await s.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={"chat_id": telegram_id, "text": msg, "parse_mode": "MarkdownV2"},
                )
        except Exception as e:
            print(f"Notify error: {e}")
    return RedirectResponse("/admin/users", status_code=303)
