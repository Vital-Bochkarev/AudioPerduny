import os
import logging
import asyncio
import json
from uuid import uuid4
from telegram import (
    Update,
    InlineQueryResultCachedVoice,
    InlineQueryResultCachedAudio,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    InlineQueryHandler,
    ContextTypes,
)
from aiohttp import web

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
AUDIO_STORAGE = "audio_messages"
TOKEN = os.getenv("BOT_TOKEN")
HEALTH_CHECK_PORT = 8080
AUDIO_METADATA_FILE = os.path.join(AUDIO_STORAGE, "audio_metadata.json")
AUDIOS_PER_PAGE = 5

# Authorized users list
AUTHORIZED_USERS_STR = os.getenv("AUTHORIZED_USERS")
AUTHORIZED_USERS = (
    [int(uid.strip()) for uid in AUTHORIZED_USERS_STR.split(",") if uid.strip()]
    if AUTHORIZED_USERS_STR
    else []
)

# Global variable - corrected spelling to be consistent
cached_audio_data = []

# --- Persistence Functions ---

def load_audio_metadata():
    """Load audio metadata from JSON file"""
    global cached_audio_data
    if os.path.exists(AUDIO_METADATA_FILE):
        try:
            with open(AUDIO_METADATA_FILE, "r", encoding="utf-8") as f:
                cached_audio_data = json.load(f)
            logger.info(f"Loaded {len(cached_audio_data)} audio entries")
        except Exception as e:
            logger.error(f"Error loading metadata: {e}")
            cached_audio_data = []
    else:
        logger.info("No metadata file found, starting fresh")
        cached_audio_data = []

def save_audio_metadata():
    """Save audio metadata to JSON file"""
    global cached_audio_data
    try:
        with open(AUDIO_METADATA_FILE, "w", encoding="utf-8") as f:
            json.dump(cached_audio_data, f, ensure_ascii=False, indent=4)
        logger.info(f"Saved {len(cached_audio_data)} audio entries")
    except Exception as e:
        logger.error(f"Error saving metadata: {e}")

# [Rest of your handlers... make sure to update all instances to use cached_audio_data]

async def run_server():
    """Run both Telegram bot and health server"""
    # Create application
    application = Application.builder().token(TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("add", add_audio_command))
    application.add_handler(CommandHandler("list", list_audios_command))
    application.add_handler(CommandHandler("delete", delete_audio_command))
    application.add_handler(CommandHandler("move", move_audio_command))
    application.add_handler(CommandHandler("voices", voices_command))
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_audio))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))
    application.add_handler(InlineQueryHandler(inline_query))
    application.add_handler(CallbackQueryHandler(pagination_callback_handler, pattern=r"^voices_page_"))

    # Load data at startup
    load_audio_metadata()

    # Start health server
    app = web.Application()
    app.router.add_get("/healthz", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", HEALTH_CHECK_PORT)
    await site.start()
    logger.info(f"Health server started on port {HEALTH_CHECK_PORT}")

    # Start bot
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    logger.info("Bot started polling")

    # Keep running
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    os.makedirs(AUDIO_STORAGE, exist_ok=True)
    
    if not TOKEN:
        logger.error("BOT_TOKEN environment variable not set!")
        exit(1)

    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
