"""
main.py — starts everything:
  - Telegram bot (polling)
  - Payment polling loop (OxaPay invoice checks)
  - Order processing loop (sends TON to target addresses)
  - FastAPI admin dashboard

Run: python main.py
"""

import asyncio
import threading
import logging
import uvicorn

from bot import build_app
from scheduler import poll_payments_loop, orders_loop
from web import app as fastapi_app
from config import WEB_HOST, WEB_PORT
import database as db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


def run_webserver():
    uvicorn.run(fastapi_app, host=WEB_HOST, port=WEB_PORT, log_level="warning")


async def run_bot_and_scheduler():
    db.init_db()
    telegram_app = build_app()

    async with telegram_app:
        await telegram_app.initialize()
        await telegram_app.start()

        bot = telegram_app.bot

        asyncio.create_task(poll_payments_loop(bot))
        asyncio.create_task(orders_loop(bot))

        logger.info("🤖 Telegram bot started.")
        logger.info(f"🌐 Admin dashboard: http://localhost:{WEB_PORT}/admin/login")
        logger.info("🔑 Default admin password: admin1234  ← change in web.py!")

        await telegram_app.updater.start_polling(drop_pending_updates=True)
        await asyncio.Event().wait()

        await telegram_app.updater.stop()
        await telegram_app.stop()


if __name__ == "__main__":
    web_thread = threading.Thread(target=run_webserver, daemon=True)
    web_thread.start()
    asyncio.run(run_bot_and_scheduler())