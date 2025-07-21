import os
import logging
from uuid import uuid4
from telegram import Update, InlineQueryResultCachedVoice, InlineQueryResultCachedAudio
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    InlineQueryHandler,
    CallbackContext,
    ContextTypes
)

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
AUDIO_STORAGE = 'audio_messages'
TOKEN = os.getenv('BOT_TOKEN')  # From Fly.io secrets

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send welcome message"""
    await update.message.reply_text(
        "🎤 Hi! Send me voice messages or audio files and I'll save them. "
        "You can then share them via inline mode by typing @YourBotName in any chat."
    )

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Process incoming audio/voice messages"""
    if update.message.voice:
        audio = update.message.voice
        is_voice = True
    elif update.message.audio:
        audio = update.message.audio
        is_voice = False
    else:
        return

    # Generate unique filename
    file_id = audio.file_id
    file_extension = 'ogg' if is_voice else audio.file_name.split('.')[-1]
    filename = f"{uuid4().hex}.{file_extension}"
    filepath = os.path.join(AUDIO_STORAGE, filename)

    # Download file
    audio_file = await context.bot.get_file(file_id)
    await audio_file.download_to_drive(filepath)

    # Store metadata
    if 'audios' not in context.bot_data:
        context.bot_data['audios'] = []
    
    context.bot_data['audios'].append({
        'file_id': file_id,
        'filepath': filepath,
        'title': f"Audio {len(context.bot_data['audios']) + 1}",
        'performer': update.message.from_user.first_name,
        'is_voice': is_voice
    })

    await update.message.reply_text("✅ Audio saved! Use inline mode to share it.")

async def inline_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline queries"""
    query = update.inline_query.query.lower()
    results = []

    if 'audios' not in context.bot_data:
        return

    for idx, audio in enumerate(context.bot_data['audios']):
        if query in audio['title'].lower():
            if audio['is_voice']:
                results.append(InlineQueryResultCachedVoice(
                    id=str(idx),
                    voice_file_id=audio['file_id'],
                    title=audio['title']
                ))
            else:
                results.append(InlineQueryResultCachedAudio(
                    id=str(idx),
                    audio_file_id=audio['file_id'],
                    title=audio['title'],
                    performer=audio['performer']
                ))

    await update.inline_query.answer(results, cache_time=0)

async def health_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Endpoint for Fly.io health checks"""
    await update.message.reply_text("🟢 Bot is running")

def main() -> None:
    """Start the bot"""
    # Create storage directory
    os.makedirs(AUDIO_STORAGE, exist_ok=True)

    # Create Application
    application = Application.builder().token(TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_audio))
    application.add_handler(InlineQueryHandler(inline_search))
    application.add_handler(CommandHandler("healthz", health_check))

    # Start polling
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    # This keeps the bot running indefinitely
    main()