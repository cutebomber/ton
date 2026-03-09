"""
Telegram bot — user facing.

Commands:
  /start       — register + main menu
  /balance     — show USD balance
  /deposit     — top up via OxaPay
  /promo       — submit a new promo order
  /orders      — view recent orders
  /help        — show commands
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
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
(
    DEP_CURRENCY, DEP_AMOUNT,
    PROMO_MEMO, PROMO_ADDRESSES, PROMO_CONFIRM,
) = range(5)


# ── /start ────────────────────────────────────────────────────────────────────

MAIN_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("💳 Deposit"),   KeyboardButton("📢 New Promo")],
        [KeyboardButton("📋 My Orders"), KeyboardButton("❓ Help")],
    ],
    resize_keyboard=True,
    input_field_placeholder="Choose an option...",
)


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.upsert_user(user.id, user.username or user.first_name)
    balance = db.get_user_balance(user.id)

    await update.message.reply_markdown(
        f"👋 Welcome, *{user.first_name}*!\n\n"
        f"💰 Balance: *${balance:.4f} USD*\n\n"
        f"Use the menu buttons below.",
        reply_markup=MAIN_MENU,
    )





# ── /balance ──────────────────────────────────────────────────────────────────

async def balance(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    bal  = db.get_user_balance(update.effective_user.id)
    rate = await get_ton_usd_rate()
    await update.message.reply_markdown(
        f"💰 *Your Balance*\n\n"
        f"${bal:.4f} USD\n"
        f"_TON/USD rate: ${rate:.4f}_",
        reply_markup=MAIN_MENU,
    )


async def menu_button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Route persistent menu button presses to the correct handler."""
    text = update.message.text
    if text == "💳 Deposit":
        return await deposit_start(update, ctx)
    elif text == "📢 New Promo":
        return await promo_start(update, ctx)
    elif text == "📋 My Orders":
        return await orders_cmd(update, ctx)
    elif text == "❓ Help":
        return await help_cmd(update, ctx)


# ── /help ─────────────────────────────────────────────────────────────────────

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_markdown(
        "*Commands*\n\n"
        "/start — Main menu\n"
        "/balance — Check your USD balance\n"
        "/deposit — Deposit crypto to top up balance\n"
        "/promo — Submit a new promo send\n"
        "/orders — View your recent orders\n"
        "/help — This message\n\n"
        f"💡 Cost: *${PRICE_PER_ADDRESS_USD} per address*\n"
        f"📤 Each address receives *{TON_SEND_AMOUNT} TON* with your memo."
    )


# ── /deposit ──────────────────────────────────────────────────────────────────

async def deposit_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.upsert_user(user.id, user.username or user.first_name)

    buttons = [[InlineKeyboardButton(c, callback_data=f"dep_{c}")] for c in OXAPAY_CURRENCIES]
    await update.message.reply_text(
        "Select the currency you want to deposit:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return DEP_CURRENCY


async def dep_currency(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["dep_currency"] = query.data.replace("dep_", "")
    await query.edit_message_text(
        f"💰 How much *{ctx.user_data['dep_currency']}* do you want to deposit?\n\n"
        f"Reply with a number (e.g. `10`):",
        parse_mode="Markdown",
    )
    return DEP_AMOUNT


async def dep_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Enter a valid positive number:")
        return DEP_AMOUNT

    currency = ctx.user_data.get("dep_currency", "TON")
    uid      = update.effective_user.id

    await update.message.reply_text("⏳ Creating invoice...")

    try:
        invoice = await create_invoice(
            amount=amount,
            currency=currency,
            order_id=str(uid),
            description=f"TON Ad Bot deposit — {amount} {currency}",
            lifetime=60,
        )
    except Exception as e:
        logger.error(f"OxaPay error: {e}")
        await update.message.reply_text("❌ Failed to create invoice. Try again later.")
        return ConversationHandler.END

    db.create_deposit(uid, currency, amount, invoice_id=str(invoice.get("track_id")))

    pay_link = invoice["pay_link"]
    await update.message.reply_markdown(
        f"✅ *Invoice Created*\n\n"
        f"Amount: *{amount} {currency}*\n"
        f"Expires in: 1 hour\n\n"
        f"👉 [Pay via OxaPay]({pay_link})\n\n"
        f"Your USD balance will be credited automatically once confirmed.",
        disable_web_page_preview=True,
    )
    return ConversationHandler.END


# ── /promo ────────────────────────────────────────────────────────────────────

async def promo_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db.upsert_user(update.effective_user.id, update.effective_user.username or update.effective_user.first_name)
    await update.message.reply_markdown(
        f"📢 *New Promo Order*\n\n"
        f"Cost: *${PRICE_PER_ADDRESS_USD} per address*\n"
        f"Each address receives: *{TON_SEND_AMOUNT} TON* with your memo\n\n"
        f"Step 1/3 — Enter your *promo memo text* (max 500 chars):\n"
        f"_This text is attached to every TON transaction._"
    )
    return PROMO_MEMO


async def promo_memo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    memo = update.message.text.strip()
    if len(memo) > 500:
        await update.message.reply_text("❌ Memo too long (max 500 chars). Try again:")
        return PROMO_MEMO

    ctx.user_data["promo_memo"] = memo
    await update.message.reply_markdown(
        f"✅ Memo saved.\n\n"
        f"Step 2/3 — Send the *list of TON wallet addresses*\n"
        f"_(one address per line)_"
    )
    return PROMO_ADDRESSES


async def promo_addresses(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lines = [l.strip() for l in update.message.text.strip().splitlines() if l.strip()]

    if not lines:
        await update.message.reply_text("❌ No addresses found. Send one address per line:")
        return PROMO_ADDRESSES

    # Basic TON address validation (UQ.../EQ... format, ~48 chars)
    invalid = [l for l in lines if not (l.startswith(("UQ", "EQ")) and len(l) >= 40)]
    if invalid:
        await update.message.reply_markdown(
            f"❌ *{len(invalid)} invalid address(es)* found:\n"
            + "\n".join(f"`{a}`" for a in invalid[:5])
            + ("\n_...and more_" if len(invalid) > 5 else "")
            + "\n\nFix and resend:"
        )
        return PROMO_ADDRESSES

    uid        = update.effective_user.id
    count      = len(lines)
    total_cost = round(count * PRICE_PER_ADDRESS_USD, 4)
    balance    = db.get_user_balance(uid)
    rate       = await get_ton_usd_rate()

    ctx.user_data["promo_addresses"] = lines
    ctx.user_data["promo_cost"]      = total_cost

    # Show confirmation
    can_afford = balance >= total_cost
    afford_str = f"✅ Sufficient" if can_afford else f"❌ Insufficient (need ${total_cost - balance:.4f} more)"

    kb = [
        [InlineKeyboardButton("✅ Confirm & Send", callback_data="promo_confirm")],
        [InlineKeyboardButton("❌ Cancel",          callback_data="promo_cancel")],
    ] if can_afford else [
        [InlineKeyboardButton("💳 Deposit First",  callback_data="promo_deposit")],
        [InlineKeyboardButton("❌ Cancel",          callback_data="promo_cancel")],
    ]

    await update.message.reply_markdown(
        f"📋 *Order Summary*\n\n"
        f"📝 Memo: _{ctx.user_data['promo_memo'][:80]}{'...' if len(ctx.user_data['promo_memo']) > 80 else ''}_\n"
        f"📍 Addresses: *{count}*\n"
        f"💵 Cost: *${total_cost} USD*\n"
        f"💰 Your balance: *${balance:.4f} USD* — {afford_str}\n"
        f"📤 Sending: *{TON_SEND_AMOUNT} TON* per address\n"
        f"📈 TON rate: *${rate:.4f}*",
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
        await query.edit_message_text("Use /deposit to top up your balance, then /promo again.")
        return ConversationHandler.END

    uid       = query.from_user.id
    username  = query.from_user.username or query.from_user.first_name
    memo      = ctx.user_data.get("promo_memo", "")
    addresses = ctx.user_data.get("promo_addresses", [])
    cost      = ctx.user_data.get("promo_cost", 0)
    balance   = db.get_user_balance(uid)

    if balance < cost:
        await query.edit_message_text("❌ Insufficient balance. Use /deposit to top up.")
        return ConversationHandler.END

    # Deduct balance and create order
    db.update_user_balance(uid, -cost)
    order_id = db.create_order(uid, username, memo, addresses, cost)

    ctx.user_data.clear()

    await query.edit_message_markdown(
        f"✅ *Order #{order_id} submitted!*\n\n"
        f"📍 {len(addresses)} addresses\n"
        f"💵 ${cost} USD charged\n\n"
        f"Sending starts immediately. Use /orders to track progress."
    )
    return ConversationHandler.END


# ── /orders ───────────────────────────────────────────────────────────────────

async def _show_orders(message, telegram_id: int):
    orders = db.get_user_orders(telegram_id)
    if not orders:
        await message.reply_text("You have no orders yet. Use /promo to create one.")
        return

    lines = ["*Your Recent Orders:*\n"]
    for o in orders:
        emoji = {"pending": "⏳", "processing": "🔄", "completed": "✅", "failed": "❌"}.get(o["status"], "❓")
        lines.append(
            f"{emoji} *Order #{o['id']}* — {o['total_addresses']} addrs — "
            f"${o['total_cost_usd']} — {o['status']}"
        )
    await message.reply_markdown("\n".join(lines))


async def orders_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _show_orders(update.message, update.effective_user.id)


# ── Cancel ────────────────────────────────────────────────────────────────────

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


# ── Notify helpers (called by scheduler) ─────────────────────────────────────

async def notify_order_complete(bot, telegram_id: int, order_id: int, sent: int, failed: int):
    try:
        await bot.send_message(
            telegram_id,
            f"✅ *Order #{order_id} Complete!*\n\n"
            f"📤 Sent: {sent}\n"
            f"❌ Failed: {failed}",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.warning(f"Could not notify user {telegram_id}: {e}")


async def notify_deposit_confirmed(bot, telegram_id: int, amount_crypto: float,
                                   currency: str, amount_usd: float):
    try:
        await bot.send_message(
            telegram_id,
            f"✅ *Deposit Confirmed!*\n\n"
            f"💰 {amount_crypto} {currency} (≈ ${amount_usd:.4f} USD) credited to your balance.\n\n"
            f"Use /promo to start a new promo send.",
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
            MessageHandler(filters.Regex("^💳 Deposit$"), deposit_start),
        ],
        states={
            DEP_CURRENCY: [CallbackQueryHandler(dep_currency, pattern="^dep_")],
            DEP_AMOUNT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, dep_amount)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    promo_conv = ConversationHandler(
        entry_points=[
            CommandHandler("promo", promo_start),
            MessageHandler(filters.Regex("^📢 New Promo$"), promo_start),
        ],
        states={
            PROMO_MEMO:      [MessageHandler(filters.TEXT & ~filters.COMMAND, promo_memo)],
            PROMO_ADDRESSES: [MessageHandler(filters.TEXT & ~filters.COMMAND, promo_addresses)],
            PROMO_CONFIRM:   [CallbackQueryHandler(promo_confirm, pattern="^promo_")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start",   start))
    app.add_handler(CommandHandler("help",    help_cmd))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("orders",  orders_cmd))
    app.add_handler(deposit_conv)
    app.add_handler(promo_conv)
    # Must be last — catches menu button text that isn't caught by conversations
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex("^(💳 Deposit|📢 New Promo|📋 My Orders|❓ Help)$"),
        menu_button_handler,
    ))

    return app


if __name__ == "__main__":
    build_app().run_polling()
