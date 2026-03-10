"""
Telegram bot — premium UI with custom Telegram emojis (HTML parse mode).
"""

import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler,
    ContextTypes, filters,
)

import database as db
from oxapay import create_invoice
from prices import get_ton_usd_rate, ton_to_usd
from config import (
    TELEGRAM_BOT_TOKEN, ADMIN_TELEGRAM_ID,
    OXAPAY_CURRENCIES, PRICE_PER_ADDRESS_USD, TON_SEND_AMOUNT,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Custom Telegram Premium Emojis ───────────────────────────────────────────
def ce(emoji_id: str, fallback: str) -> str:
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'

TON      = ce("5424912684078348533", "💎")
ROCKET   = ce("5258332798409783582", "🚀")
CHECK    = ce("6161041134828133385", "✅")
CROSS    = ce("5985346521103604145", "❌")
WALLET   = ce("5424976816530014958", "💰")
FAST     = ce("5935795874251674052", "⚡")
CHART    = ce("5994378914636500516", "📊")
USER     = ce("6161326861822466721", "👤")
ANNOUNCE = ce("6161049750532529553", "📢")
WAVE     = ce("5994750571041525522", "👋")

SEP  = "─" * 28
SEP2 = "═" * 28

# ── Conversation states ───────────────────────────────────────────────────────
(DEP_CURRENCY, DEP_AMOUNT, PROMO_MEMO, PROMO_ADDRESSES, PROMO_CONFIRM) = range(5)

MENU_FILTER = "^(💎 Deposit|🚀 New Promo|📊 My Orders|❓ Help)$"

MAIN_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("💎 Deposit"),   KeyboardButton("🚀 New Promo")],
        [KeyboardButton("📊 My Orders"), KeyboardButton("❓ Help")],
    ],
    resize_keyboard=True,
    input_field_placeholder="Select an action...",
)

CURRENCY_INFO = {
    "TON":  ("💎", "Toncoin"),
    "BTC":  ("₿",  "Bitcoin"),
    "ETH":  ("⟠",  "Ethereum"),
    "USDT": ("💵", "Tether"),
    "USDC": ("💵", "USD Coin"),
    "LTC":  ("Ł",  "Litecoin"),
}


# ── /start ────────────────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.upsert_user(user.id, user.username or user.first_name)
    balance = db.get_user_balance(user.id)
    rate    = await get_ton_usd_rate()
    ton_eq  = round(balance / rate, 4) if rate > 0 else 0

    orders       = db.get_user_orders(user.id)
    total_orders = len(orders)
    done_orders  = sum(1 for o in orders if o["status"] == "completed")

    await update.message.reply_html(
        f"{TON} <b>Tonvertise</b>\n\n"
        f"{WAVE} Welcome back, <b>{user.first_name}</b>!\n\n"
        f"{WALLET} Balance: <code>${balance:.4f} USD</code>\n\n"
        f"<i>Use the menu below to get started</i>",
        reply_markup=MAIN_MENU,
    )


# ── /balance ──────────────────────────────────────────────────────────────────

async def balance_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid    = update.effective_user.id
    bal    = db.get_user_balance(uid)
    rate   = await get_ton_usd_rate()
    ton_eq = round(bal / rate, 4) if rate > 0 else 0

    deposits = db.get_user_deposits(uid)[:3]
    dep_lines = ""
    if deposits:
        dep_lines = f"\n\n{WALLET} <b>Recent Deposits</b>\n"
        for d in deposits:
            se = CHECK if d["status"] == "confirmed" else FAST if d["status"] == "pending" else CROSS
            dep_lines += f"  {se} <code>{d['amount_crypto']} {d['currency']}</code> → <code>${d['amount_usd']:.4f}</code>\n"

    await update.message.reply_html(
        f"{WALLET} <b>Your Balance</b>\n"
        f"<code>{SEP2}</code>\n\n"
        f"  💵 USD:  <code>${bal:.4f}</code>\n"
        f"  {TON} TON:  <code>{ton_eq} TON</code>\n\n"
        f"  📈 Rate:  <code>1 TON = ${rate:.4f}</code>"
        f"{dep_lines}\n\n"
        f"<code>{SEP}</code>\n"
        f"<i>Tap {TON} Deposit to top up</i>",
        reply_markup=MAIN_MENU,
    )


# ── /help ─────────────────────────────────────────────────────────────────────

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(
        f"❓ <b>Help &amp; Info</b>\n"
        f"<code>{SEP2}</code>\n\n"
        f"{ROCKET} <b>How it works</b>\n"
        f"  1. Deposit crypto to your balance\n"
        f"  2. Submit a promo order with a memo\n"
        f"  3. We send <code>{TON_SEND_AMOUNT} TON</code> to every address\n\n"
        f"💵 <b>Pricing</b>\n"
        f"  <code>${PRICE_PER_ADDRESS_USD}</code> per address\n\n"
        f"📋 <b>Commands</b>\n"
        f"  /start — Home screen\n"
        f"  /balance — Check balance\n"
        f"  /deposit — Top up\n"
        f"  /promo — New promo order\n"
        f"  /orders — Order history\n\n"
        f"<code>{SEP}</code>\n"
        f"<i>Powered by TON blockchain</i> {TON}",
        reply_markup=MAIN_MENU,
    )


# ── /deposit ──────────────────────────────────────────────────────────────────

async def deposit_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db.upsert_user(update.effective_user.id, update.effective_user.username or update.effective_user.first_name)

    buttons = []
    for c in OXAPAY_CURRENCIES:
        emoji, name = CURRENCY_INFO.get(c, ("💰", c))
        buttons.append([InlineKeyboardButton(f"{emoji} {name} ({c})", callback_data=f"dep_{c}")])

    await update.message.reply_html(
        f"{TON} <b>Deposit Crypto</b>\n"
        f"<code>{SEP2}</code>\n\n"
        f"Select your preferred currency:\n\n"
        f"<i>Payments processed securely via OxaPay</i>",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return DEP_CURRENCY


async def dep_currency(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    currency = query.data.replace("dep_", "")
    ctx.user_data["dep_currency"] = currency
    emoji, name = CURRENCY_INFO.get(currency, ("💰", currency))

    await query.edit_message_text(
        f"{emoji} <b>Deposit {name}</b>\n"
        f"<code>{SEP2}</code>\n\n"
        f"How much <b>{currency}</b> do you want to deposit?\n\n"
        f"Reply with an amount (e.g. <code>10</code>):",
        parse_mode="HTML",
    )
    return DEP_AMOUNT


async def dep_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_html(f"{CROSS} Please enter a valid positive number:")
        return DEP_AMOUNT

    currency = ctx.user_data.get("dep_currency", "TON")
    uid      = update.effective_user.id
    emoji, name = CURRENCY_INFO.get(currency, ("💰", currency))

    wait_msg = await update.message.reply_html(f"{FAST} <b>Creating invoice...</b>")

    try:
        invoice = await create_invoice(
            amount=amount,
            currency=currency,
            order_id=str(uid),
            description=f"Tonvertise — {amount} {currency}",
            lifetime=60,
        )
    except Exception as e:
        logger.error(f"OxaPay error: {e}")
        await wait_msg.edit_text(
            f"{CROSS} Failed to create invoice:\n<code>{e}</code>",
            parse_mode="HTML",
        )
        return ConversationHandler.END

    db.create_deposit(uid, currency, amount, invoice_id=str(invoice.get("track_id")))
    pay_link = invoice["payment_url"]

    await wait_msg.edit_text(
        f"{CHECK} <b>Invoice Created!</b>\n"
        f"<code>{SEP2}</code>\n\n"
        f"{emoji} Amount:   <code>{amount} {currency}</code>\n"
        f"⏱ Expires:  <code>60 minutes</code>\n"
        f"🔒 Secured by OxaPay\n\n"
        f"👇 <b>Tap below to pay</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(f"💳 Pay {amount} {currency}", url=pay_link)
        ]]),
        disable_web_page_preview=True,
    )
    return ConversationHandler.END


# ── /promo ────────────────────────────────────────────────────────────────────

async def promo_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db.upsert_user(update.effective_user.id, update.effective_user.username or update.effective_user.first_name)
    balance = db.get_user_balance(update.effective_user.id)

    await update.message.reply_html(
        f"{ANNOUNCE} <b>New Promo Order</b>\n"
        f"<code>{SEP2}</code>\n\n"
        f"💵 Cost:     <code>${PRICE_PER_ADDRESS_USD}</code> per address\n"
        f"{TON} Sends:   <code>{TON_SEND_AMOUNT} TON</code> per address\n"
        f"{WALLET} Balance: <code>${balance:.4f} USD</code>\n\n"
        f"<code>{SEP}</code>\n"
        f"<b>Step 1 of 3</b> — Enter your <b>memo text</b>\n"
        f"<i>This message will be attached to every TON transaction.</i>\n"
        f"<i>Max 500 characters</i>",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Cancel", callback_data="promo_cancel")
        ]]),
    )
    return PROMO_MEMO


async def promo_memo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    memo = update.message.text.strip()
    if len(memo) > 500:
        await update.message.reply_html(
            f"{CROSS} <b>Too long!</b> <code>{len(memo)}/500</code> chars. Please shorten it:"
        )
        return PROMO_MEMO

    ctx.user_data["promo_memo"] = memo
    preview = memo[:60] + ("..." if len(memo) > 60 else "")

    await update.message.reply_html(
        f"{CHECK} <b>Memo saved!</b>\n"
        f"<code>{SEP2}</code>\n\n"
        f"📝 <code>{preview}</code>\n\n"
        f"<code>{SEP}</code>\n"
        f"<b>Step 2 of 3</b> — Send your <b>wallet address list</b>\n"
        f"<i>One TON address per line</i>\n\n"
        f"Example:\n"
        f"<code>UQAbc...xyz\nEQDef...uvw</code>",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Cancel", callback_data="promo_cancel")
        ]]),
    )
    return PROMO_ADDRESSES


async def promo_addresses(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    import re
    lines = [l.strip() for l in update.message.text.strip().splitlines() if l.strip()]

    if not lines:
        await update.message.reply_html(f"{CROSS} No addresses found. Send one per line:")
        return PROMO_ADDRESSES

    def is_valid(addr):
        if addr.startswith(("UQ", "EQ")) and len(addr) >= 40:
            return True
        if re.match(r"^-?\d+:[0-9a-fA-F]{64}$", addr):
            return True
        return False

    invalid = [l for l in lines if not is_valid(l)]
    if invalid:
        sample = "\n".join(f"<code>{a}</code>" for a in invalid[:5])
        await update.message.reply_html(
            f"{CROSS} <b>{len(invalid)} invalid address(es)</b> detected:\n\n"
            f"{sample}"
            f"{chr(10) + '<i>...and more</i>' if len(invalid) > 5 else ''}\n\n"
            f"<i>Make sure each address is on its own line</i>\n"
            f"Please fix and resend:"
        )
        return PROMO_ADDRESSES

    uid        = update.effective_user.id
    count      = len(lines)
    total_cost = round(count * PRICE_PER_ADDRESS_USD, 4)
    balance    = db.get_user_balance(uid)
    rate       = await get_ton_usd_rate()
    ton_total  = round(count * TON_SEND_AMOUNT, 4)

    ctx.user_data["promo_addresses"] = lines
    ctx.user_data["promo_cost"]      = total_cost

    can_afford  = balance >= total_cost
    balance_str = (
        f"{CHECK} <code>${balance:.4f}</code>" if can_afford
        else f"{CROSS} <code>${balance:.4f}</code> <i>(need <code>${total_cost - balance:.4f}</code> more)</i>"
    )
    memo_prev = ctx.user_data['promo_memo'][:50] + ("..." if len(ctx.user_data['promo_memo']) > 50 else "")

    kb = [
        [InlineKeyboardButton("✅ Confirm & Send 🚀", callback_data="promo_confirm"),
         InlineKeyboardButton("❌ Cancel", callback_data="promo_cancel")]
    ] if can_afford else [
        [InlineKeyboardButton("💎 Deposit First", callback_data="promo_deposit"),
         InlineKeyboardButton("❌ Cancel", callback_data="promo_cancel")]
    ]

    await update.message.reply_html(
        f"{CHART} <b>Order Summary</b>\n"
        f"<code>{SEP2}</code>\n\n"
        f"📝 Memo:        <i>{memo_prev}</i>\n"
        f"📍 Addresses:   <code>{count}</code>\n"
        f"{TON} TON total: <code>{ton_total} TON</code>\n"
        f"💵 Cost:        <code>${total_cost} USD</code>\n"
        f"📈 Rate:        <code>1 TON = ${rate:.4f}</code>\n\n"
        f"{WALLET} Balance:   {balance_str}\n\n"
        f"<code>{SEP}</code>\n"
        f"<b>Step 3 of 3</b> — Confirm to start sending",
        reply_markup=InlineKeyboardMarkup(kb),
    )
    return PROMO_CONFIRM


async def promo_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "promo_cancel":
        ctx.user_data.clear()
        await query.edit_message_text(f"{CROSS} Order cancelled.", parse_mode="HTML")
        return ConversationHandler.END

    if query.data == "promo_deposit":
        ctx.user_data.clear()
        await query.edit_message_text(
            f"{TON} Tap <b>💎 Deposit</b> in the menu to top up, then start a new promo.",
            parse_mode="HTML",
        )
        return ConversationHandler.END

    uid       = query.from_user.id
    username  = query.from_user.username or query.from_user.first_name
    memo      = ctx.user_data.get("promo_memo", "")
    addresses = ctx.user_data.get("promo_addresses", [])
    cost      = ctx.user_data.get("promo_cost", 0)
    balance   = db.get_user_balance(uid)

    if balance < cost:
        await query.edit_message_text(
            f"{CROSS} Insufficient balance. Tap 💎 Deposit to top up.",
            parse_mode="HTML",
        )
        return ConversationHandler.END

    db.update_user_balance(uid, -cost)
    order_id = db.create_order(uid, username, memo, addresses, cost)
    ctx.user_data.clear()

    await query.edit_message_text(
        f"{ROCKET} <b>Order #{order_id} Submitted!</b>\n"
        f"<code>{SEP2}</code>\n\n"
        f"📍 Addresses:  <code>{len(addresses)}</code>\n"
        f"💵 Charged:    <code>${cost} USD</code>\n"
        f"{FAST} Status:    <code>Processing...</code>\n\n"
        f"<code>{SEP}</code>\n"
        f"<i>Sending starts immediately.</i>\n"
        f"<i>You'll be notified when complete.</i>\n\n"
        f"Track with {CHART} <b>My Orders</b>",
        parse_mode="HTML",
    )
    return ConversationHandler.END


# ── /orders ───────────────────────────────────────────────────────────────────

async def _show_orders(message, telegram_id: int):
    orders = db.get_user_orders(telegram_id)
    if not orders:
        await message.reply_html(
            f"{CHART} <b>My Orders</b>\n"
            f"<code>{SEP2}</code>\n\n"
            f"<i>No orders yet.</i>\n\n"
            f"Tap {ROCKET} <b>New Promo</b> to create your first order!",
            reply_markup=MAIN_MENU,
        )
        return

    STATUS_E = {
        "pending":    "⏳",
        "processing": FAST,
        "completed":  CHECK,
        "failed":     CROSS,
    }

    lines = [f"{CHART} <b>My Orders</b>\n<code>{SEP2}</code>\n"]
    for o in orders:
        e  = STATUS_E.get(o["status"], "❓")
        ts = datetime.fromtimestamp(o["created_at"]).strftime("%b %d, %H:%M")
        lines.append(
            f"{e} <b>Order #{o['id']}</b>\n"
            f"   📍 <code>{o['total_addresses']}</code> addrs  •  💵 <code>${o['total_cost_usd']}</code>\n"
            f"   📝 <i>{o['memo_text'][:40]}{'...' if len(o['memo_text']) > 40 else ''}</i>\n"
            f"   🕐 <code>{ts}</code>  •  <code>{o['status']}</code>\n"
        )

    await message.reply_html(
        "\n".join(lines),
        reply_markup=MAIN_MENU,
    )


async def orders_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _show_orders(update.message, update.effective_user.id)


# ── Cancel / menu fallback ────────────────────────────────────────────────────

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    text = update.message.text if update.message else ""
    if text == "💎 Deposit":   return await deposit_start(update, ctx)
    if text == "🚀 New Promo": return await promo_start(update, ctx)
    if text == "📊 My Orders": return await orders_cmd(update, ctx)
    if text == "❓ Help":       return await help_cmd(update, ctx)
    await update.message.reply_html(f"{CROSS} Cancelled.", reply_markup=MAIN_MENU)
    return ConversationHandler.END


async def menu_button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "💎 Deposit":   return await deposit_start(update, ctx)
    if text == "🚀 New Promo": return await promo_start(update, ctx)
    if text == "📊 My Orders": return await orders_cmd(update, ctx)
    if text == "❓ Help":       return await help_cmd(update, ctx)


# ── Notifications (called by scheduler) ──────────────────────────────────────

async def notify_order_complete(bot, telegram_id: int, order_id: int, sent: int, failed: int):
    try:
        total   = sent + failed
        rate    = round(sent / total * 100) if total else 0
        icon    = CHECK if failed == 0 else "⚠️"
        await bot.send_message(
            telegram_id,
            f"{icon} <b>Order #{order_id} Complete</b>\n"
            f"<code>{SEP2}</code>\n\n"
            f"{CHECK} Sent:    <code>{sent}</code>\n"
            f"{CROSS} Failed:  <code>{failed}</code>\n"
            f"{CHART} Rate:    <code>{rate}%</code>\n\n"
            f"<i>Check {CHART} My Orders for details</i>",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning(f"Could not notify user {telegram_id}: {e}")


async def notify_deposit_confirmed(bot, telegram_id: int, amount_crypto: float,
                                   currency: str, amount_usd: float):
    try:
        emoji, name = CURRENCY_INFO.get(currency, ("💰", currency))
        new_balance = db.get_user_balance(telegram_id)
        await bot.send_message(
            telegram_id,
            f"{CHECK} <b>Deposit Confirmed!</b>\n"
            f"<code>{SEP2}</code>\n\n"
            f"{emoji} <code>{amount_crypto} {currency}</code>\n"
            f"💵 Credited:  <code>${amount_usd:.4f} USD</code>\n"
            f"{WALLET} Balance:  <code>${new_balance:.4f} USD</code>\n\n"
            f"<i>Ready to launch a promo? Tap</i> {ROCKET} <b>New Promo</b>",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning(f"Could not notify user {telegram_id}: {e}")


# ── App builder ───────────────────────────────────────────────────────────────

def build_app():
    db.init_db()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    deposit_conv = ConversationHandler(
        entry_points=[
            CommandHandler("deposit", deposit_start),
            MessageHandler(filters.Regex("^💎 Deposit$"), deposit_start),
        ],
        states={
            DEP_CURRENCY: [CallbackQueryHandler(dep_currency, pattern="^dep_")],
            DEP_AMOUNT:   [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_FILTER), dep_amount)],
        },
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex(MENU_FILTER), cancel)],
    )

    promo_conv = ConversationHandler(
        entry_points=[
            CommandHandler("promo", promo_start),
            MessageHandler(filters.Regex("^🚀 New Promo$"), promo_start),
        ],
        states={
            PROMO_MEMO:      [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_FILTER), promo_memo)],
            PROMO_ADDRESSES: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_FILTER), promo_addresses)],
            PROMO_CONFIRM:   [CallbackQueryHandler(promo_confirm, pattern="^promo_")],
        },
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex(MENU_FILTER), cancel)],
    )

    app.add_handler(CommandHandler("start",   start))
    app.add_handler(CommandHandler("help",    help_cmd))
    app.add_handler(CommandHandler("balance", balance_cmd))
    app.add_handler(CommandHandler("orders",  orders_cmd))
    app.add_handler(deposit_conv)
    app.add_handler(promo_conv)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(MENU_FILTER),
        menu_button_handler,
    ))

    return app


if __name__ == "__main__":
    build_app().run_polling()
