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

# Firebase imports
from firebase_admin import credentials, initialize_app
from firebase_admin import firestore
import json # Import json for parsing firebase_config_str

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

# Global Firebase variables
db = None
app_id = None
# We'll use a consistent 'bot_data_user_id' for the Firestore path
# This ID will represent the bot's identity within Firestore for its public data.
bot_data_user_id = None

# --- Firebase Initialization ---
async def initialize_firebase(context: ContextTypes.DEFAULT_TYPE):
    global db, app_id, bot_data_user_id

    if db is None:
        try:
            # Get app_id from environment (provided by Canvas)
            app_id = os.getenv('__app_id')
            if not app_id:
                app_id = 'default-perduny-bot-app' # Fallback for local testing

            # Firebase config from environment (provided by Canvas)
            firebase_config_str = os.getenv('__firebase_config')
            if firebase_config_str:
                firebase_config = json.loads(firebase_config_str)
                cred = credentials.Certificate(firebase_config)
                initialize_app(cred)
                db = firestore.client()
                logger.info("Firebase initialized successfully.")
            else:
                logger.warning("FIREBASE_CONFIG environment variable not found. Firestore will not be available.")
                db = None # Ensure db remains None if config is missing
                return

            # For the Firestore path, we need a consistent user ID for the bot's data.
            # We'll use a UUID stored in bot_data, which persists across minor restarts
            # if the bot_data is saved/loaded, but more importantly, it's consistent
            # for this specific bot instance's public data.
            # For this context, the __initial_auth_token is for authenticating the bot process itself.
            # The 'user_id' in the Firestore path will be a fixed identifier for this bot's collection.
            bot_data_user_id = context.bot_data.setdefault('firestore_bot_id', str(uuid4()))
            logger.info(f"Using Firestore bot ID: {bot_data_user_id}")

        except Exception as e:
            logger.error(f"Error initializing Firebase: {e}")
            db = None # Ensure db is None if initialization fails

# --- Telegram Bot Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message when the /start command is issued."""
    # Attempt to initialize Firebase if it's not already
    if db is None:
        await update.message.reply_text("Бот запускается, пожалуйста, подождите, пока инициализируется база данных...")
        await initialize_firebase(context) # Pass context for bot_data access
        if db is None:
            await update.message.reply_text("Не удалось инициализировать базу данных. Функции сохранения/поиска будут недоступны.")
            return

    response_text = "🎤 Привет! Перешли мне голосовое сообщение или аудио файл, и я помогу тебе поделиться ими!"
    # Display the bot's Firestore ID for debugging purposes
    if bot_data_user_id:
        response_text += f"\n\nID бота для базы данных: `{bot_data_user_id}`"
    await update.message.reply_text(response_text)

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles incoming voice messages and audio files."""
    if db is None:
        await update.message.reply_text("База данных не инициализирована. Пожалуйста, подождите или попробуйте /start снова.")
        return

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
    if db is None:
        await update.message.reply_text("База данных не инициализирована. Пожалуйста, подождите или попробуйте /start снова.")
        return

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
            try:
                # Store the audio details in Firestore public collection
                # Path: /artifacts/{appId}/public/data/cached_audios/{file_id}
                doc_ref = db.collection(f'artifacts/{app_id}/public/data/cached_audios').document(file_id)
                await doc_ref.set({
                    'name': audio_name,
                    'author': author_name,
                    'file_id': file_id,
                    'type': file_type,
                    'telegram_user_id': user.id, # Store the actual Telegram user ID for reference
                    'timestamp': firestore.SERVER_TIMESTAMP # Add a timestamp
                })
                logger.info(f"Saved {file_type} '{audio_name}' by '{author_name}' (ID: {file_id}) to Firestore for user {user.id}.")
                await update.message.reply_text(
                    f"Сохранил твое голосовое как '{audio_name}' от '{author_name}'! "
                    "Можешь теперь пересылать его в чате, указав имя бота через @"
                )
            except Exception as e:
                logger.error(f"Error saving audio to Firestore for user {user.id}: {e}")
                await update.message.reply_text("Произошла ошибка при сохранении аудио. Пожалуйста, попробуй еще раз.")
        else:
            logger.warning(f"User {user.id} provided author '{author_name}' but missing other audio details.")
            await update.message.reply_text("Что-то пошло не так, повтори с начала")
    
    else:
        logger.info(f"Received general text from {user.id}: '{update.message.text}'")

async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles inline queries to suggest cached voice/audio messages."""
    if db is None:
        logger.warning("Firestore not initialized for inline query.")
        await update.inline_query.answer([], cache_time=0) # Return empty results
        return

    query = update.inline_query.query.lower() # Convert query to lowercase for case-insensitive search
    results = []

    try:
        # Retrieve cached audios from Firestore public collection
        docs = db.collection(f'artifacts/{app_id}/public/data/cached_audios').stream()
        
        cached_audios = []
        for doc in docs:
            audio_data = doc.to_dict()
            if audio_data:
                cached_audios.append(audio_data)

        # Filter audios based on the query (match name or author)
        filtered_audios = [
            item for item in cached_audios
            if query in item.get('name', '').lower() or query in item.get('author', '').lower() or not query
        ]

        for item in filtered_audios:
            audio_name = item.get('name', 'Unknown Name')
            author_name = item.get('author', 'Unknown Author')
            
            # Combine name and author into the title as 'description' is not supported
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

    except Exception as e:
        logger.error(f"Error fetching audios from Firestore: {e}")
        # Optionally, inform the user about the error in inline query results
        # This is more complex for inline queries, usually you'd just return empty or log.

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
    
    # Initialize Firebase at startup
    # Pass application.bot_data as context for initialize_firebase to store bot_data_user_id
    await initialize_firebase(application.bot_data)

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
