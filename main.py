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
        # Store file_id and file_type in user_data to await the name
        context.user_data['pending_audio_file_id'] = file_id
        context.user_data['pending_audio_file_type'] = file_type
        context.user_data['awaiting_audio_name'] = True
        logger.info(f"User {user.id} sent a {file_type} and is now awaiting a name.")
        await update.message.reply_text(
            f"Received your {file_type} message! What name would you like to give it for future search? "
            "(e.g., 'My funny voice note', 'Meeting minutes audio')"
        )

async def handle_audio_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the text message that is expected to be the name for the audio."""
    user = update.effective_user
    if context.user_data.get('awaiting_audio_name'):
        audio_name = update.message.text.strip()
        file_id = context.user_data.pop('pending_audio_file_id', None)
        file_type = context.user_data.pop('pending_audio_file_type', None)
        context.user_data.pop('awaiting_audio_name', None) # Clear the flag

        if audio_name and file_id and file_type:
            # Store the audio details globally in bot_data
            # Using a list of dictionaries to store multiple cached audios
            cached_audios = context.bot_data.setdefault('user_cached_audios', [])
            cached_audios.append({
                'name': audio_name,
                'file_id': file_id,
                'type': file_type,
                'user_id': user.id # Store user ID if you want to filter by user later
            })
            logger.info(f"Saved {file_type} '{audio_name}' (ID: {file_id}) for user {user.id}.")
            await update.message.reply_text(f"Saved your {file_type} as '{audio_name}'! You can now use it in inline mode.")
        else:
            logger.warning(f"User {user.id} provided name '{audio_name}' but no pending audio found.")
            await update.message.reply_text("Something went wrong. Please send your audio again before naming it.")
    else:
        # If not awaiting a name, this text message might be for something else, or just ignored.
        # For now, we'll just log it.
        logger.info(f"Received unexpected text from {user.id}: '{update.message.text}'")
        # You might want to add a default text handler here if needed.

async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles inline queries to suggest cached voice/audio messages."""
    query = update.inline_query.query.lower() # Convert query to lowercase for case-insensitive search
    results = []

    # Retrieve cached audios from bot_data
    cached_audios = context.bot_data.get('user_cached_audios', [])
    
    # Filter audios based on the query
    filtered_audios = [
        item for item in cached_audios
        if query in item['name'].lower() or not query # Match name or show all if query is empty
    ]

    for item in filtered_audios:
        if item['type'] == "voice":
            results.append(
                InlineQueryResultCachedVoice(
                    id=str(uuid4()), # Unique ID for each result
                    voice_file_id=item['file_id'],
                    title=item['name'] # 'title' is required for InlineQueryResultCachedVoice
                    # Removed 'caption' for no description
                )
            )
        elif item['type'] == "audio":
            results.append(
                InlineQueryResultCachedAudio(
                    id=str(uuid4()), # Unique ID for each result
                    audio_file_id=item['file_id'],
                    title=item['name'] # 'title' is required for InlineQueryResultCachedAudio
                    # Removed 'caption' for no description
                )
            )

    await update.inline_query.answer(results, cache_time=0)
    logger.info(f"Inline query from {update.effective_user.first_name} ({update.effective_user.id}): '{query}' - {len(results)} results.")


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
    # Handler for voice/audio messages - MUST be before the generic text handler
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_audio))
    # Handler for text messages (audio names) - MUST be after command handlers
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_audio_name))
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
