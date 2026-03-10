# ═══════════════════════════════════════════════════════════════
#  config.py  —  edit this file directly, no .env needed
# ═══════════════════════════════════════════════════════════════

# ── Telegram ──────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = "8694299888:AAGLt4aTK8jbRisFAgklNZ58VECGY_GliWQ"

# Your numeric Telegram user ID (get it from @userinfobot)
ADMIN_TELEGRAM_ID = 1899208318

# Private channel ID where all TX logs are sent (e.g. -1001234567890)
# Add the bot as admin to this channel first
LOG_CHANNEL_ID = -1003751370172

# ── TON Wallet ────────────────────────────────────────────────
# The fixed admin wallet that funds all promo sends
ADMIN_TON_WALLET   = "UQBZ5C6cOo1LNWucXJWfzq8biUpLwJ8sBBALLB_cQn-T6VJ8"
ADMIN_TON_MNEMONIC = "cash matrix behind engage hover shoulder include dove process bachelor body cousin lemon around kitten utility trend sunset arm swift host purity animal dose"

# ── TON HTTP API (free key at https://toncenter.com) ──────────
TON_API_URL = "https://toncenter.com/api/v2"
TON_API_KEY = ""   # leave empty to use public rate-limited endpoint

# ── Pricing ───────────────────────────────────────────────────
PRICE_PER_ADDRESS_USD = 0.05   # charged to user per target address
TON_SEND_AMOUNT       = 0.001  # TON sent to each target address

# ── Database ──────────────────────────────────────────────────
DB_PATH = "ton_ad_bot.db"

# ── Web UI (admin dashboard) ──────────────────────────────────
WEB_HOST   = "0.0.0.0"
WEB_PORT   = 8000
SECRET_KEY = "mYb0t$ecr3tK3y#2024!xQpLzR9vTnWk"

# ── OxaPay — automated crypto deposits ───────────────────────
# Sign up at https://oxapay.com → Merchant → API Keys
OXAPAY_MERCHANT_KEY = "P5JRXH-BGKQTO-TID5OG-OATXBQ"

# Currencies users can deposit

OXAPAY_CURRENCIES = ["TON", "BTC", "ETH", "USDT", "USDC", "LTC"]
