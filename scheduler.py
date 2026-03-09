"""
Scheduler — two background loops:

1. poll_payments_loop — checks pending OxaPay invoices every 10s,
                        confirms them and credits user USD balance

2. orders_loop        — picks up pending orders immediately,
                        sends TON to each address, logs to admin channel
"""

import asyncio
import logging

import database as db
from ton import send_ton, get_wallet_balance
from oxapay import get_invoice
from prices import ton_to_usd, get_ton_usd_rate
from config import (
    ADMIN_TON_WALLET, TON_SEND_AMOUNT,
    LOG_CHANNEL_ID, ADMIN_TELEGRAM_ID,
)

logger = logging.getLogger(__name__)

POLL_INTERVAL  = 10   # seconds between invoice checks
ORDER_INTERVAL = 5    # seconds between order processing ticks

# TON explorer base URL for TX links
TON_EXPLORER = "https://tonscan.org/tx"


# ── Payment polling ───────────────────────────────────────────────────────────

async def poll_payments_loop(bot=None):
    from bot import notify_deposit_confirmed
    logger.info("💳 Payment polling started.")

    while True:
        try:
            pending = db.get_all_pending_deposits()
            for dep in pending:
                if not dep["invoice_id"]:
                    continue
                try:
                    data   = await get_invoice(str(dep["invoice_id"]))
                    status = (data.get("status") or "").lower()
                    logger.info(f"Invoice {dep['invoice_id']} status: {status}")

                    if status == "paid":
                        amount_crypto = float(data.get("payAmount") or dep["amount_crypto"])
                        currency      = data.get("payCurrency") or dep["currency"]
                        # Convert to USD: if TON use live rate, else treat as USD stablecoin
                        if dep["currency"] in ("USDT", "USDC"):
                            amount_usd = float(data.get("amount") or dep["amount_crypto"])
                        else:
                            amount_usd = await ton_to_usd(amount_crypto)

                        db.confirm_deposit_by_invoice(dep["invoice_id"], amount_usd)
                        db.update_user_balance(dep["telegram_id"], amount_usd)

                        logger.info(
                            f"✅ Deposit confirmed — user {dep['telegram_id']} "
                            f"+${amount_usd:.4f} USD ({amount_crypto} {currency})"
                        )

                        if bot:
                            await notify_deposit_confirmed(
                                bot, dep["telegram_id"],
                                amount_crypto, currency, amount_usd
                            )

                    elif status in ("expired", "failed"):
                        db.reject_deposit(dep["id"])
                        logger.info(f"🗑️  Invoice {dep['invoice_id']} {status}")

                except Exception as e:
                    logger.warning(f"Invoice check error {dep['invoice_id']}: {e}")

        except Exception as e:
            logger.error(f"Payment poll error: {e}", exc_info=True)

        await asyncio.sleep(POLL_INTERVAL)


# ── Order processing ──────────────────────────────────────────────────────────

async def _log_order_to_channel(bot, order, targets):
    """Send a single summary message to the admin log channel."""
    if not LOG_CHANNEL_ID or not bot:
        return

    sent_targets   = [t for t in targets if t["status"] == "sent"]
    failed_targets = [t for t in targets if t["status"] == "failed"]

    tx_lines = []
    for t in sent_targets:
        if t["tx_hash"]:
            tx_lines.append(f"• `{t['address'][:12]}...` → [{t['tx_hash'][:10]}...]({TON_EXPLORER}/{t['tx_hash']})")
        else:
            tx_lines.append(f"• `{t['address'][:12]}...` → sent")

    for t in failed_targets:
        tx_lines.append(f"• `{t['address'][:12]}...` → ❌ failed")

    tx_block = "\n".join(tx_lines) if tx_lines else "_No transactions_"

    msg = (
        f"📦 *Order #{order['id']}* completed\n"
        f"👤 @{order['username'] or 'unknown'}\n"
        f"📝 Memo: _{order['memo_text'][:80]}_\n"
        f"📍 Addresses: {order['total_addresses']}\n"
        f"✅ Sent: {len(sent_targets)} | ❌ Failed: {len(failed_targets)}\n"
        f"💵 Charged: ${order['total_cost_usd']}\n\n"
        f"*Transactions:*\n{tx_block}"
    )

    try:
        await bot.send_message(
            LOG_CHANNEL_ID,
            msg,
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.warning(f"Could not log to channel: {e}")


async def _process_order(order, bot):
    from bot import notify_order_complete

    order_id = order["id"]
    db.set_order_status(order_id, "processing")

    targets = db.get_order_targets(order_id)
    memo    = order["memo_text"]

    logger.info(f"🚀 Processing order #{order_id} — {len(targets)} addresses")

    for target in targets:
        result = await send_ton(target["address"], TON_SEND_AMOUNT, memo)

        if result["success"]:
            db.update_target(target["id"], result["tx_hash"], "sent")
            logger.info(f"✅ → {target['address'][:12]}... tx={result['tx_hash']}")
        else:
            db.update_target(target["id"], None, "failed")
            logger.warning(f"❌ → {target['address'][:12]}...: {result['error']}")

        await asyncio.sleep(1)  # brief pause between sends

    db.set_order_status(order_id, "completed")

    # Fetch all targets (including status) for the log
    all_targets = db.get_order_targets_all(order_id)
    sent   = sum(1 for t in all_targets if t["status"] == "sent")
    failed = sum(1 for t in all_targets if t["status"] == "failed")

    # Notify user
    if bot:
        await notify_order_complete(bot, order["telegram_id"], order_id, sent, failed)

    # Log summary to admin channel
    await _log_order_to_channel(bot, order, all_targets)

    logger.info(f"✅ Order #{order_id} done — {sent} sent, {failed} failed")


async def orders_loop(bot=None):
    logger.info("📦 Order processing loop started.")
    while True:
        try:
            # Check wallet balance before processing
            balance = await get_wallet_balance(ADMIN_TON_WALLET)
            if balance < 0.05:
                logger.warning(f"⚠️  Wallet low ({balance:.4f} TON) — skipping order processing.")
            else:
                pending = db.get_pending_orders()
                for order in pending:
                    await _process_order(order, bot)

        except Exception as e:
            logger.error(f"Orders loop error: {e}", exc_info=True)

        await asyncio.sleep(ORDER_INTERVAL)


def start_scheduler(bot=None):
    loop = asyncio.get_event_loop()
    loop.create_task(poll_payments_loop(bot))
    loop.create_task(orders_loop(bot))
