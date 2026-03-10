"""
Telegram bot — premium UI with rich formatting and live order tracking.
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

# ── Conversation states ───────────────────────────────────────────────────────
(DEP_CURRENCY, DEP_AMOUNT, PROMO_MEMO, PROMO_ADDRESSES, PROMO_CONFIRM) = range(5)

MENU_FILTER = "^(💎 Deposit|🚀 New Promo|📊 My Orders|❓ Help)$"

MAIN_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("💎 Deposit"),    KeyboardButton("🚀 New Promo")],
        [KeyboardButton("📊 My Orders"),  KeyboardButton("❓ Help")],
    ],
    resize_keyboard=True,
    input_field_placeholder="Select an action...",
)

# Currency display info
CURRENCY_INFO = {
    "TON":  ("💎", "Toncoin"),
    "BTC":  ("₿",  "Bitcoin"),
    "ETH":  ("⟠",  "Ethereum"),
    "USDT": ("💵", "Tether"),
    "USDC": ("💵", "USD Coin"),
    "LTC":  ("Ł",  "Litecoin"),
}

SEP  = "─" * 28
SEP2 = "═" * 28


# ── /start ────────────────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.upsert_user(user.id, user.username or user.first_name)
    balance = db.get_user_balance(user.id)
    rate    = await get_ton_usd_rate()
    ton_eq  = round(balance / rate, 4) if rate > 0 else 0

    orders  = db.get_user_orders(user.id)
    total_orders = len(orders)
    done_orders  = sum(1 for o in orders if o["status"] == "completed")

    await update.message.reply_markdown(
        f"💎 *TON Promo Bot*\n"
        f"`{SEP2}`\n\n"
        f"👋 Welcome back, *{user.first_name}*!\n\n"
        f"💰 *Balance*\n"
        f"  `${balance:.4f} USD`  ≈  `{ton_eq} TON`\n\n"
        f"📦 *Your Stats*\n"
        f"  Orders: `{total_orders}`  •  Completed: `{done_orders}`\n\n"
        f"`{SEP}`\n"
        f"_Use the menu below to get started_",
        reply_markup=MAIN_MENU,
    )


# ── /balance ──────────────────────────────────────────────────────────────────

async def balance_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid     = update.effective_user.id
    bal     = db.get_user_balance(uid)
    rate    = await get_ton_usd_rate()
    ton_eq  = round(bal / rate, 4) if rate > 0 else 0

    # Last 3 deposits
    deposits = db.get_user_deposits(uid)[:3]
    dep_lines = ""
    if deposits:
        dep_lines = "\n\n💳 *Recent Deposits*\n"
        for d in deposits:
            status_e = "✅" if d["status"] == "confirmed" else "⏳" if d["status"] == "pending" else "❌"
            dep_lines += f"  {status_e} `{d['amount_crypto']} {d['currency']}` → `${d['amount_usd']:.4f}`\n"

    await update.message.reply_markdown(
        f"💰 *Your Balance*\n"
        f"`{SEP2}`\n\n"
        f"  💵 USD:  `${bal:.4f}`\n"
        f"  💎 TON:  `{ton_eq} TON`\n\n"
        f"  📈 Rate:  `1 TON = ${rate:.4f}`"
        f"{dep_lines}\n\n"
        f"`{SEP}`\n"
        f"_Tap 💎 Deposit to top up_",
        reply_markup=MAIN_MENU,
    )


# ── /help ─────────────────────────────────────────────────────────────────────

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_markdown(
        f"❓ *Help & Info*\n"
        f"`{SEP2}`\n\n"
        f"🚀 *How it works*\n"
        f"  1\\. Deposit crypto to your balance\n"
        f"  2\\. Submit a promo order with a memo\n"
        f"  3\\. We send `{TON_SEND_AMOUNT} TON` to every address\n\n"
        f"💵 *Pricing*\n"
        f"  `${PRICE_PER_ADDRESS_USD}` per address\n\n"
        f"📋 *Commands*\n"
        f"  /start — Home screen\n"
        f"  /balance — Check balance\n"
        f"  /deposit — Top up\n"
        f"  /promo — New promo order\n"
        f"  /orders — Order history\n\n"
        f"`{SEP}`\n"
        f"_Powered by TON blockchain_ 💎",
        reply_markup=MAIN_MENU,
    )


# ── /deposit ──────────────────────────────────────────────────────────────────

async def deposit_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db.upsert_user(update.effective_user.id, update.effective_user.username or update.effective_user.first_name)

    buttons = []
    for c in OXAPAY_CURRENCIES:
        emoji, name = CURRENCY_INFO.get(c, ("💰", c))
        buttons.append([InlineKeyboardButton(f"{emoji} {name} ({c})", callback_data=f"dep_{c}")])

    await update.message.reply_markdown(
        f"💎 *Deposit Crypto*\n"
        f"`{SEP2}`\n\n"
        f"Select your preferred currency:\n\n"
        f"_Payments processed securely via OxaPay_",
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
        f"{emoji} *Deposit {name}*\n"
        f"`{SEP2}`\n\n"
        f"How much *{currency}* do you want to deposit?\n\n"
        f"Reply with an amount \\(e\\.g\\. `10`\\):",
        parse_mode="MarkdownV2",
    )
    return DEP_AMOUNT


async def dep_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid positive number:")
        return DEP_AMOUNT

    currency = ctx.user_data.get("dep_currency", "TON")
    uid      = update.effective_user.id
    emoji, name = CURRENCY_INFO.get(currency, ("💰", currency))

    wait_msg = await update.message.reply_markdown(f"⏳ *Creating invoice...*")

    try:
        invoice = await create_invoice(
            amount=amount,
            currency=currency,
            order_id=str(uid),
            description=f"TON Promo Bot — {amount} {currency}",
            lifetime=60,
        )
    except Exception as e:
        logger.error(f"OxaPay error: {e}")
        await wait_msg.edit_text(f"❌ Failed to create invoice:\n`{e}`", parse_mode="Markdown")
        return ConversationHandler.END

    db.create_deposit(uid, currency, amount, invoice_id=str(invoice.get("track_id")))
    pay_link = invoice["payment_url"]

    await wait_msg.edit_text(
        f"✅ *Invoice Created!*\n"
        f"`{SEP2}`\n\n"
        f"{emoji} Amount:  `{amount} {currency}`\n"
        f"⏱ Expires:  `60 minutes`\n"
        f"🔒 Secured by OxaPay\n\n"
        f"👇 *Tap below to pay*",
        parse_mode="Markdown",
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

    await update.message.reply_markdown(
        f"🚀 *New Promo Order*\n"
        f"`{SEP2}`\n\n"
        f"💵 Cost:  `${PRICE_PER_ADDRESS_USD}` per address\n"
        f"💎 Sends:  `{TON_SEND_AMOUNT} TON` per address\n"
        f"💰 Balance:  `${balance:.4f} USD`\n\n"
        f"`{SEP}`\n"
        f"*Step 1 of 3* — Enter your *memo text*\n"
        f"_This message will be attached to every TON transaction\\._\n"
        f"_Max 500 characters_",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Cancel", callback_data="promo_cancel")
        ]]),
    )
    return PROMO_MEMO


async def promo_memo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    memo = update.message.text.strip()
    if len(memo) > 500:
        await update.message.reply_markdown(
            f"❌ *Too long!* `{len(memo)}/500` chars\\. Please shorten it:",
        )
        return PROMO_MEMO

    ctx.user_data["promo_memo"] = memo
    preview = memo[:60] + ("..." if len(memo) > 60 else "")

    await update.message.reply_markdown(
        f"✅ *Memo saved!*\n"
        f"`{SEP2}`\n\n"
        f"📝 `{preview}`\n\n"
        f"`{SEP}`\n"
        f"*Step 2 of 3* — Send your *wallet address list*\n"
        f"_One TON address per line_\n\n"
        f"Example:\n"
        f"`UQAbc...xyz`\n"
        f"`EQDef...uvw`",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Cancel", callback_data="promo_cancel")
        ]]),
    )
    return PROMO_ADDRESSES


async def promo_addresses(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    import re
    lines = [l.strip() for l in update.message.text.strip().splitlines() if l.strip()]

    if not lines:
        await update.message.reply_text("❌ No addresses found. Send one per line:")
        return PROMO_ADDRESSES

    # Validate — accept UQ/EQ prefix OR raw 0:hex format
    def is_valid(addr):
        if addr.startswith(("UQ", "EQ")) and len(addr) >= 40:
            return True
        if re.match(r"^-?\d+:[0-9a-fA-F]{64}$", addr):
            return True
        return False

    invalid = [l for l in lines if not is_valid(l)]
    if invalid:
        sample = "\n".join(f"`{a}`" for a in invalid[:5])
        await update.message.reply_markdown(
            f"❌ *{len(invalid)} invalid address(es)* detected:\n\n"
            f"{sample}"
            f"{'\\n_...and more_' if len(invalid) > 5 else ''}\n\n"
            f"_Make sure each address is on its own line_\n"
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
    balance_str = f"✅ `${balance:.4f}`" if can_afford else f"❌ `${balance:.4f}` _(need `${total_cost - balance:.4f}` more)_"
    memo_prev   = ctx.user_data['promo_memo'][:50] + ("..." if len(ctx.user_data['promo_memo']) > 50 else "")

    kb = [[InlineKeyboardButton("✅ Confirm & Send 🚀", callback_data="promo_confirm"),
           InlineKeyboardButton("❌ Cancel", callback_data="promo_cancel")]] if can_afford else \
         [[InlineKeyboardButton("💎 Deposit First", callback_data="promo_deposit"),
           InlineKeyboardButton("❌ Cancel", callback_data="promo_cancel")]]

    await update.message.reply_markdown(
        f"📋 *Order Summary*\n"
        f"`{SEP2}`\n\n"
        f"📝 Memo:       _{memo_prev}_\n"
        f"📍 Addresses:  `{count}`\n"
        f"💎 TON total:  `{ton_total} TON`\n"
        f"💵 Cost:       `${total_cost} USD`\n"
        f"📈 Rate:       `1 TON = ${rate:.4f}`\n\n"
        f"💰 Balance:    {balance_str}\n\n"
        f"`{SEP}`\n"
        f"*Step 3 of 3* — Confirm to start sending",
        reply_markup=InlineKeyboardMarkup(kb),
    )
    return PROMO_CONFIRM


async def promo_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "promo_cancel":
        ctx.user_data.clear()
        await query.edit_message_text("❌ Order cancelled.")
        return ConversationHandler.END

    if query.data == "promo_deposit":
        ctx.user_data.clear()
        await query.edit_message_text(
            "💎 Tap the Deposit button in the menu to top up, then start a new promo."
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
            "❌ Insufficient balance. Tap 💎 Deposit to top up."
        )
        return ConversationHandler.END

    db.update_user_balance(uid, -cost)
    order_id = db.create_order(uid, username, memo, addresses, cost)
    ctx.user_data.clear()

    await query.edit_message_text(
        f"🚀 *Order #{order_id} Submitted!*\n"
        f"`{SEP2}`\n\n"
        f"📍 Addresses:  `{len(addresses)}`\n"
        f"💵 Charged:    `${cost} USD`\n"
        f"⚡ Status:     `Processing...`\n\n"
        f"`{SEP}`\n"
        f"_Sending starts immediately\\._\n"
        f"_You'll be notified when complete\\._\n\n"
        f"Track with 📊 *My Orders*",
        parse_mode="MarkdownV2",
    )
    return ConversationHandler.END


# ── /orders ───────────────────────────────────────────────────────────────────

async def _show_orders(message, telegram_id: int):
    orders = db.get_user_orders(telegram_id)
    if not orders:
        await message.reply_markdown(
            f"📊 *My Orders*\n"
            f"`{SEP2}`\n\n"
            f"_No orders yet._\n\n"
            f"Tap 🚀 *New Promo* to create your first order\\!",
        )
        return

    STATUS_EMOJI = {
        "pending":    "⏳",
        "processing": "⚡",
        "completed":  "✅",
        "failed":     "❌",
    }

    lines = [f"📊 *My Orders*\n`{SEP2}`\n"]
    for o in orders:
        e   = STATUS_EMOJI.get(o["status"], "❓")
        ts  = datetime.fromtimestamp(o["created_at"]).strftime("%b %d, %H:%M")
        lines.append(
            f"{e} *Order \\#{o['id']}*\n"
            f"   📍 `{o['total_addresses']}` addrs  •  💵 `${o['total_cost_usd']}`\n"
            f"   📝 _{o['memo_text'][:40]}{'...' if len(o['memo_text']) > 40 else ''}_\n"
            f"   🕐 `{ts}`  •  `{o['status']}`\n"
        )

    await message.reply_text(
        "\n".join(lines),
        parse_mode="MarkdownV2",
        reply_markup=MAIN_MENU,
    )


async def orders_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _show_orders(update.message, update.effective_user.id)


# ── Cancel / menu fallback ────────────────────────────────────────────────────

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    text = update.message.text if update.message else ""
    if text == "💎 Deposit":    return await deposit_start(update, ctx)
    if text == "🚀 New Promo":  return await promo_start(update, ctx)
    if text == "📊 My Orders":  return await orders_cmd(update, ctx)
    if text == "❓ Help":        return await help_cmd(update, ctx)
    await update.message.reply_text("❌ Cancelled.", reply_markup=MAIN_MENU)
    return ConversationHandler.END


async def menu_button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "💎 Deposit":    return await deposit_start(update, ctx)
    if text == "🚀 New Promo":  return await promo_start(update, ctx)
    if text == "📊 My Orders":  return await orders_cmd(update, ctx)
    if text == "❓ Help":        return await help_cmd(update, ctx)


# ── Notifications (called by scheduler) ──────────────────────────────────────

async def notify_order_complete(bot, telegram_id: int, order_id: int, sent: int, failed: int):
    try:
        total = sent + failed
        rate  = round(sent / total * 100) if total else 0
        await bot.send_message(
            telegram_id,
            f"{'✅' if failed == 0 else '⚠️'} *Order #{order_id} Complete*\n"
            f"`{SEP2}`\n\n"
            f"✅ Sent:    `{sent}`\n"
            f"❌ Failed:  `{failed}`\n"
            f"📊 Rate:    `{rate}%`\n\n"
            f"_Check 📊 My Orders for details_",
            parse_mode="Markdown",
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
            f"✅ *Deposit Confirmed!*\n"
            f"`{SEP2}`\n\n"
            f"{emoji} `{amount_crypto} {currency}`\n"
            f"💵 Credited:  `${amount_usd:.4f} USD`\n"
            f"💰 Balance:   `${new_balance:.4f} USD`\n\n"
            f"_Ready to launch a promo? Tap 🚀 New Promo_",
            parse_mode="Markdown",
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
