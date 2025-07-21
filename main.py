import os
import logging
import asyncio
from uuid import uuid4
from telegram import Update, InlineQueryResultCachedVoice, InlineQueryResultCachedAudio
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    InlineQueryHandler,
    ContextTypes
)
from aiohttp import web

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
AUDIO_STORAGE = 'audio_messages'
TOKEN = os.getenv('BOT_TOKEN')
HEALTH_CHECK_PORT = 8080

# --- Telegram Bot Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message when the /start command is issued."""
    await update.message.reply_text("🎤 Hi! Send me voice messages or audio files, and I can help you share them!")

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles incoming voice messages and audio files."""
    user = update.effective_user
    file_id = None
    file_type = None
    duration = 0

    if update.message.voice:
        file_id = update.message.voice.file_id
        file_type = "voice"
        duration = update.message.voice.duration
        logger.info(f"Received voice message from {user.first_name} ({user.id})")
    elif update.message.audio:
        file_id = update.message.audio.file_id
        file_type = "audio"
        duration = update.message.audio.duration
        logger.info(f"Received audio file from {user.first_name} ({user.id})")
    else:
        # This handler should only trigger for voice/audio, but as a fallback
        await update.message.reply_text("I can only process voice messages or audio files.")
        return

    if file_id:
        # You can store file_id in a database associated with the user for later retrieval
        # For this example, we'll just acknowledge receipt.
        # In a real app, you might save this ID for the inline query handler.
        await update.message.reply_text(
            f"Received your {file_type} message! Its file ID is `{file_id}`. "
            "You can now use me in inline mode to share it (if implemented)."
        )
        # Note: Telegram's cached file IDs are global. You don't need to download
        # and re-upload if you just want to share the cached ID.
        # If you needed to process the file content, you would:
        # new_file = await context.bot.get_file(file_id)
        # file_path = os.path.join(AUDIO_STORAGE, f"{uuid4()}.{file_type}")
        # await new_file.download_to_drive(file_path)
        # logger.info(f"Downloaded {file_type} to {file_path}")

async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles inline queries to suggest cached voice/audio messages."""
    query = update.inline_query.query
    results = []

    # In a real application, you would query a database here
    # to find cached voice/audio messages belonging to the user
    # or public ones. For demonstration, we'll use a placeholder.

    # Example: If you stored file_ids, you could retrieve them.
    # For now, let's just offer a dummy result or filter based on query.
    # This part needs to be connected to your actual storage of cached IDs.

    # Dummy cached voice/audio for demonstration purposes
    # Replace with actual cached file_ids from your storage
    dummy_voice_file_id = "AwACAgIAAxkBAAIGyGZl2gAB0h9iW2e-cQ_b7s19S89zAAJ6NAAC9QoBS1j3eO4-C4QzNAQ" # Replace with a real cached voice ID
    dummy_audio_file_id = "CQACAgIAAxkBAAIGyWZl2gAB0y9iW2e-cQ_b7s19S89zAAJ6NAAC9QoBS1j3eO4-C4QzNAQ" # Replace with a real cached audio ID

    if "voice" in query.lower() or not query:
        results.append(
            InlineQueryResultCachedVoice(
                id=str(uuid4()),
                voice_file_id=dummy_voice_file_id,
                caption="This is a dummy voice message." # Removed 'title'
            )
        )
    if "audio" in query.lower() or not query:
        results.append(
            InlineQueryResultCachedAudio(
                id=str(uuid4()),
                audio_file_id=dummy_audio_file_id,
                caption="This is a dummy audio file." # Removed 'title'
            )
        )

    await update.inline_query.answer(results, cache_time=0)
    logger.info(f"Inline query from {update.effective_user.first_name} ({update.effective_user.id}): '{query}'")


# --- Health Check Server ---

async def health_check(request):
    """Responds to health check requests."""
    logger.info("Health check requested.")
    return web.Response(text="OK")

# --- Application Runner ---

async def run_server():
    """Run both Telegram bot and health server."""
    # Create application
    application = Application.builder().token(TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_audio))
    application.add_handler(InlineQueryHandler(inline_query)) # Add inline query handler
    
    # Start health server using aiohttp
    app = web.Application()
    app.router.add_get('/healthz', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', HEALTH_CHECK_PORT)
    await site.start()
    logger.info(f"Health check server started on port {HEALTH_CHECK_PORT}")
    
    # Start Telegram bot
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    logger.info("Telegram bot started polling.")
    
    # Keep running forever
    # This prevents the main asyncio loop from exiting, keeping both servers alive.
    while True:
        await asyncio.sleep(3600)  # Sleep for an hour, effectively keeping the loop running indefinitely

if __name__ == "__main__":
    # Create storage directory if it doesn't exist
    os.makedirs(AUDIO_STORAGE, exist_ok=True)
    logger.info(f"Ensured '{AUDIO_STORAGE}' directory exists.")
    
    # Ensure BOT_TOKEN is set
    if not TOKEN:
        logger.error("BOT_TOKEN environment variable is not set. Please set it before running the bot.")
        exit(1)

    # Run the main server function
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user (KeyboardInterrupt).")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
