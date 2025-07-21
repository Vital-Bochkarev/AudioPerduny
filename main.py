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
AUDIO_STORAGE = 'audio_messages' # This is for actual audio files, not metadata
TOKEN = os.getenv('BOT_TOKEN')
HEALTH_CHECK_PORT = 8080

# --- Telegram Bot Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message when the /start command is issued."""
    await update.message.reply_text("🎤 Привет! Перешли мне голосовое сообщение или аудио файл, и я помогу тебе поделиться ими!")

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
        await update.message.reply_text("Я могу обрабатывать только голосовые сообщения или .ogg файлы с кодеком opus")
        return

    if file_id:
        context.user_data['pending_audio_file_id'] = file_id
        context.user_data['pending_audio_file_type'] = file_type
        context.user_data['state'] = 'awaiting_audio_name'
        logger.info(f"User {user.id} sent a {file_type} and is now awaiting audio name.")
        await update.message.reply_text("Получил голосовое! Введи название для поиска")

async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles text input based on the current state of the conversation."""
    user = update.effective_user
    current_state = context.user_data.get('state')

    if current_state == 'awaiting_audio_name':
        audio_name = update.message.text.strip()
        if audio_name:
            context.user_data['temp_audio_name'] = audio_name
            context.user_data['state'] = 'awaiting_author_name'
            logger.info(f"User {user.id} provided audio name: '{audio_name}'. Now awaiting author name.")
            await update.message.reply_text("Теперь введи автора")
        else:
            await update.message.reply_text("Введи подходящее название")
    
    elif current_state == 'awaiting_author_name':
        author_name = update.message.text.strip()
        file_id = context.user_data.pop('pending_audio_file_id', None)
        file_type = context.user_data.pop('pending_audio_file_type', None)
        audio_name = context.user_data.pop('temp_audio_name', None)
        context.user_data.pop('state', None) # Clear the state

        if author_name and file_id and file_type and audio_name:
            # Store the audio details globally in bot_data (this is not persistent)
            cached_audios = context.bot_data.setdefault('user_cached_audios', [])
            cached_audios.append({
                'name': audio_name,
                'author': author_name,
                'file_id': file_id,
                'type': file_type,
                'user_id': user.id
            })
            logger.info(f"Saved {file_type} '{audio_name}' by '{author_name}' (ID: {file_id}) for user {user.id}.")
            await update.message.reply_text(
                f"Сохранил твое голосовое как '{audio_name}' от '{author_name}'! "
                "Можешь теперь пересылать его в чате, указав имя бота через @"
            )
        else:
            logger.warning(f"User {user.id} provided author '{author_name}' but missing other audio details.")
            await update.message.reply_text("Что-то пошло не так, повтори с начала")
    
    else:
        logger.info(f"Received general text from {user.id}: '{update.message.text}'")

async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles inline queries to suggest cached voice/audio messages."""
    query = update.inline_query.query.lower() # Convert query to lowercase for case-insensitive search
    results = []

    # Retrieve cached audios from bot_data
    cached_audios = context.bot_data.get('user_cached_audios', [])
    
    # Filter audios based on the query (match name or author)
    filtered_audios = [
        item for item in cached_audios
        if query in item.get('name', '').lower() or query in item.get('author', '').lower() or not query
    ]

    for item in filtered_audios:
        audio_name = item.get('name', 'Unknown Name')
        author_name = item.get('author', 'Unknown Author')
        
        # Combine name and author into the title
        display_title = f"{audio_name} by {author_name}"
        
        if item.get('type') == "voice":
            results.append(
                InlineQueryResultCachedVoice(
                    id=str(uuid4()), # Unique ID for each result
                    voice_file_id=item['file_id'],
                    title=display_title # Combined name and author
                )
            )
        elif item.get('type') == "audio":
            results.append(
                InlineQueryResultCachedAudio(
                    id=str(uuid4()), # Unique ID for each result
                    audio_file_id=item['file_id'],
                    title=display_title # Combined name and author
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
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_audio))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))
    application.add_handler(InlineQueryHandler(inline_query))
    
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
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    # Create storage directory if it doesn't exist (for actual audio files, if implemented)
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
