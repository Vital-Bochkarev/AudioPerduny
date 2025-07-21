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
    ConversationHandler,
    CallbackQueryHandler
)

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
AUDIO_STORAGE = 'audio_messages'
TOKEN_FILE = 'bot_token.txt'

# Conversation states
TITLE, CONFIRM = range(2)

def get_bot_token():
    """Read the bot token from bot_token.txt file."""
    try:
        with open(TOKEN_FILE, 'r') as f:
            return f.read().strip()
    except FileNotFoundError:
        logger.error(f"Token file '{TOKEN_FILE}' not found in the current directory.")
        raise
    except Exception as e:
        logger.error(f"Error reading token file: {e}")
        raise

async def start(update: Update, context: CallbackContext) -> None:
    """Send a message when the command /start is issued."""
    await update.message.reply_text(
        'Hi! Send me an audio message and I will save it. '
        'You can then share it via inline mode by typing @YourBotName in any chat.'
    )

async def save_audio(update: Update, context: CallbackContext) -> int:
    """Initiate audio saving process by asking for title."""
    if update.message.audio:
        audio = update.message.audio
        is_voice = False
    elif update.message.voice:
        audio = update.message.voice
        is_voice = True
    else:
        return ConversationHandler.END

    # Store temporary data in user_data
    context.user_data['current_audio'] = {
        'file_id': audio.file_id,
        'is_voice': is_voice,
        'file_name': audio.file_name if not is_voice else 'voice_message.ogg'
    }

    await update.message.reply_text(
        "Please enter a title for this audio (this will be used for inline search):"
    )
    return TITLE

async def get_title(update: Update, context: CallbackContext) -> int:
    """Store the title and confirm with user."""
    title = update.message.text
    context.user_data['current_audio']['title'] = title
    context.user_data['current_audio']['performer'] = update.message.from_user.first_name

    await update.message.reply_text(
        f"Title set to: {title}\n"
        f"Now I'll save this audio. Please wait..."
    )
    
    # Proceed with saving
    return await save_audio_final(update, context)

async def save_audio_final(update: Update, context: CallbackContext) -> int:
    """Final step to save the audio with metadata."""
    audio_data = context.user_data['current_audio']
    
    # Generate unique filename
    file_extension = 'ogg' if audio_data['is_voice'] else audio_data['file_name'].split('.')[-1]
    filename = f"{uuid4().hex}.{file_extension}"
    filepath = os.path.join(AUDIO_STORAGE, filename)

    # Download the file
    audio_file = await context.bot.get_file(audio_data['file_id'])
    await audio_file.download_to_drive(filepath)

    # Store file info in bot data
    if 'audios' not in context.bot_data:
        context.bot_data['audios'] = []
    
    context.bot_data['audios'].append({
        'file_id': audio_data['file_id'],
        'filepath': filepath,
        'title': audio_data['title'],
        'performer': audio_data['performer'],
        'is_voice': audio_data['is_voice']
    })

    await update.message.reply_text(
        f"✅ Audio saved successfully!\n"
        f"Title: {audio_data['title']}\n"
        f"You can now share it via inline mode by typing @{context.bot.username} in any chat."
    )
    
    # Clean up
    del context.user_data['current_audio']
    return ConversationHandler.END

async def cancel(update: Update, context: CallbackContext) -> int:
    """Cancel the conversation."""
    await update.message.reply_text('Audio saving cancelled.')
    if 'current_audio' in context.user_data:
        del context.user_data['current_audio']
    return ConversationHandler.END

async def inline_query(update: Update, context: CallbackContext) -> None:
    """Handle inline queries to share saved audio messages."""
    query = update.inline_query.query.lower()
    results = []

    if 'audios' not in context.bot_data:
        return

    for idx, audio in enumerate(context.bot_data['audios']):
        if query in audio['title'].lower():
            if audio['is_voice']:
                results.append(
                    InlineQueryResultCachedVoice(
                        id=str(idx),
                        voice_file_id=audio['file_id'],
                        title=audio['title']
                    )
                )
            else:
                results.append(
                    InlineQueryResultCachedAudio(
                        id=str(idx),
                        audio_file_id=audio['file_id'],
                        title=audio['title'],
                        performer=audio['performer']
                    )
                )

    try:
        await update.inline_query.answer(results, cache_time=0)
    except Exception as e:
        logger.error(f"Error answering inline query: {e}")

async def error_handler(update: Update, context: CallbackContext) -> None:
    """Log errors."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

def main() -> None:
    """Start the bot."""
    os.makedirs(AUDIO_STORAGE, exist_ok=True)

    try:
        token = get_bot_token()
        
        application = Application.builder().token(token).build()

        # Create conversation handler for audio saving
        conv_handler = ConversationHandler(
            entry_points=[
                MessageHandler(filters.AUDIO | filters.VOICE, save_audio)
            ],
            states={
                TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_title)],
            },
            fallbacks=[CommandHandler('cancel', cancel)]
        )

        # Register handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(conv_handler)
        application.add_handler(InlineQueryHandler(inline_query))
        application.add_error_handler(error_handler)

        # Start the Bot
        application.run_polling()
        logger.info("Bot started successfully")

    except Exception as e:
        logger.error(f"Failed to start bot: {e}")

if __name__ == '__main__':
    main()