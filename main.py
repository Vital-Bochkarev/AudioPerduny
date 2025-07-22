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
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
AUDIO_STORAGE = "audio_messages"
TOKEN = os.getenv("BOT_TOKEN")
HEALTH_CHECK_PORT = 8080
AUDIO_METADATA_FILE = os.path.join(AUDIO_STORAGE, "audio_metadata.json")
AUDIOS_PER_PAGE = 5

# Authorized users
AUTHORIZED_USERS_STR = os.getenv("AUTHORIZED_USERS")
AUTHORIZED_USERS = (
    [int(uid.strip()) for uid in AUTHORIZED_USERS_STR.split(",") if uid.strip()]
    if AUTHORIZED_USERS_STR
    else []
)

# Global variable (consistent naming)
cached_audio_data = []

# ======================
# PERSISTENCE FUNCTIONS
# ======================

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

# ======================
# TELEGRAM HANDLERS
# ======================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send welcome message"""
    user_id = update.effective_user.id
    if AUTHORIZED_USERS and user_id not in AUTHORIZED_USERS:
        await update.message.reply_text(
            "Приветствую! Используйте @Perduny_bot в чатах для отправки голосовых."
        )
        return
    
    await update.message.reply_text(
        "🎤 Привет! Я помогу тебе управлять голосовыми сообщениями.\n\n"
        "Доступные команды:\n"
        "/add - Добавить аудио\n"
        "/list - Список аудио\n"
        "/voices - Интерактивный список"
    )

async def add_audio_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Initiate audio adding process"""
    global cached_audio_data
    user = update.effective_user
    if AUTHORIZED_USERS and user.id not in AUTHORIZED_USERS:
        await update.message.reply_text("У вас нет прав для этой команды.")
        return

    context.user_data["state"] = "awaiting_audio"
    await update.message.reply_text("Отправьте голосовое сообщение или аудиофайл")

# [Include all your other handlers here...]

# ======================
# HEALTH CHECK SERVER
# ======================

async def health_check(request):
    return web.Response(text="OK")

async def run_server():
    """Run bot and health server"""
    # Create bot application
    application = Application.builder().token(TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler(\"move\", move_audio))
    application.add_handler(CommandHandler("add", add_audio_command))
    # [Add all other handlers...]

    # Load existing data
    load_audio_metadata()

    # Start health server
    app = web.Application()
    app.router.add_get("/healthz", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", HEALTH_CHECK_PORT)
    await site.start()

    # Start bot
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    logger.info("Bot started successfully!")
    
    # Keep running
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    # Create storage directory if needed
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


# ===============
# /move COMMAND
# ===============
async def move_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if AUTHORIZED_USERS and user_id not in AUTHORIZED_USERS:
        await update.message.reply_text("You are not authorized to use this command.")
        return

    try:
        current_index = int(context.args[0])
        new_index = int(context.args[1])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /move <current_index> <new_index>")
        return

    global cached_audio_data
    total = len(cached_audio_data)

    if not (0 <= current_index < total) or not (0 <= new_index < total):
        await update.message.reply_text(f"Indices must be between 0 and {total - 1}")
        return

    item = cached_audio_data.pop(current_index)
    cached_audio_data.insert(new_index, item)
    save_audio_metadata()

    await update.message.reply_text(
        f"Moved audio from position {current_index} to {new_index}."
    )


