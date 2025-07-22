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
    CallbackQueryHandler,  # New: for handling button presses
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
AUDIO_STORAGE = "audio_messages"  # This is the mounted persistent volume path
TOKEN = os.getenv("BOT_TOKEN")
HEALTH_CHECK_PORT = 8080
AUDIO_METADATA_FILE = os.path.join(AUDIO_STORAGE, "audio_metadata.json")
AUDIOS_PER_PAGE = 10  # Number of audios to display per page

# New: Authorized users list
# Get AUTHORIZED_USERS from environment variable, split by comma, and convert to integers.
# If not set, default to an empty list (no one authorized by default).
# Example: AUTHORIZED_USERS="123456789,987654321"
AUTHORIZED_USERS_STR = os.getenv("AUTHORIZED_USERS")
AUTHORIZED_USERS = (
    [int(uid.strip()) for uid in AUTHORIZED_USERS_STR.split(",") if uid.strip()]
    if AUTHORIZED_USERS_STR
    else []
)

# Global variable to hold cached audio data
cached_audios_data = []

# --- Persistence Functions (File-based) ---


def load_audio_metadata():
    """Loads audio metadata from the JSON file on the persistent volume."""
    global cached_audios_data
    if os.path.exists(AUDIO_METADATA_FILE):
        try:
            with open(AUDIO_METADATA_FILE, "r", encoding="utf-8") as f:
                cached_audios_data = json.load(f)
            logger.info(
                f"Loaded {len(cached_audios_data)} audio entries from {AUDIO_METADATA_FILE}"
            )
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON from {AUDIO_METADATA_FILE}: {e}")
            cached_audios_data = []  # Reset if file is corrupt
        except Exception as e:
            logger.error(f"Error loading audio metadata: {e}")
            cached_audios_data = []
    else:
        logger.info("Audio metadata file not found. Starting with empty data.")
        cached_audios_data = []


def save_audio_metadata():
    """Saves audio metadata to the JSON file on the persistent volume."""
    try:
        with open(AUDIO_METADATA_FILE, "w", encoding="utf-8") as f:
            json.dump(cached_audios_data, f, ensure_ascii=False, indent=4)
        logger.info(
            f"Saved {len(cached_audios_data)} audio entries to {AUDIO_METADATA_FILE}"
        )
    except Exception as e:
        logger.error(f"Error saving audio metadata: {e}")


# --- Telegram Bot Handlers ---


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message when the /start command is issued, with authorization check."""
    user_id = update.effective_user.id
    if AUTHORIZED_USERS and user_id not in AUTHORIZED_USERS:
        # Message for unauthorized users
        await update.message.reply_text(
            "Приветствую. Чтобы воспользоваться ботом, в любом чате набери @Perduny_bot и выбери голосовое для отправки. Этот чат доступен только администратору для добавления и удаления голосовых."
        )
        logger.info(f"Unauthorized user {user_id} started the bot.")
    else:
        # Existing welcome message for authorized users
        await update.message.reply_text(
            "🎤 Привет! Перешли мне голосовое сообщение или аудио файл, и я помогу тебе поделиться ими!"
        )
        logger.info(f"Authorized user {user_id} started the bot.")


async def list_audios_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Lists all saved audio files (admin-only)."""
    global cached_audios_data

    user_id = update.effective_user.id
    if AUTHORIZED_USERS and user_id not in AUTHORIZED_USERS:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        logger.warning(f"Unauthorized attempt to list audios by user: {user_id}")
        return

    if not cached_audios_data:
        await update.message.reply_text("Пока нет сохраненных аудио.")
        return

    message_text = "Сохраненные аудио:\n\n"
    for i, item in enumerate(cached_audios_data):
        # Using the file_id as the unique identifier for deletion
        message_text += (
            f"{i+1}. ID: `{item.get('file_id', 'N/A')}`\n"
            f"   Автор: {item.get('author', 'Неизвестный автор')}\n"
            f"   Название: {item.get('name', 'Без названия')}\n\n"
        )

    await update.message.reply_text(message_text, parse_mode="Markdown")


async def delete_audio_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Deletes a saved audio file by its file_id (admin-only)."""
    global cached_audios_data

    # Authorization check for delete command
    user_id = update.effective_user.id
    if AUTHORIZED_USERS and user_id not in AUTHORIZED_USERS:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        logger.warning(f"Unauthorized attempt to delete audio by user: {user_id}")
        return

    if not context.args:
        await update.message.reply_text(
            "Пожалуйста, укажите ID аудио для удаления. Используйте /list, чтобы получить список ID."
        )
        return

    audio_id_to_delete = context.args[0].strip()
    logger.info(
        f"Attempting to delete audio with ID: '{audio_id_to_delete}' by user: {user_id}"
    )

    original_count = len(cached_audios_data)

    new_cached_audios_data = []
    found_and_deleted = False
    for item in cached_audios_data:
        current_file_id = item.get("file_id")
        logger.info(
            f"Comparing '{audio_id_to_delete}' with existing ID: '{current_file_id}'"
        )
        if current_file_id == audio_id_to_delete:
            found_and_deleted = True
            logger.info(
                f"Match found! Deleting audio: {item.get('name')} by {item.get('author')}"
            )
        else:
            new_cached_audios_data.append(item)

    cached_audios_data = new_cached_audios_data  # Update the global list

    if found_and_deleted:
        save_audio_metadata()  # Save changes to the file
        await update.message.reply_text(
            f"Аудио с ID `{audio_id_to_delete}` успешно удалено."
        )
        logger.info(
            f"Audio with ID {audio_id_to_delete} deleted by user {update.effective_user.id}."
        )
    else:
        await update.message.reply_text(
            f"Аудио с ID `{audio_id_to_delete}` не найдено. Проверьте правильность ID."
        )
        logger.warning(
            f"Attempted to delete non-existent audio with ID {audio_id_to_delete} by user {update.effective_user.id}."
        )


async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles incoming voice messages and audio files."""
    user = update.effective_user

    # Authorization check for adding audio
    if AUTHORIZED_USERS and user.id not in AUTHORIZED_USERS:
        await update.message.reply_text("У вас нет прав для добавления аудио.")
        logger.warning(f"Unauthorized attempt to add audio by user: {user.id}")
        return

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
        await update.message.reply_text(
            "Я могу обрабатывать только голосовые сообщения или .ogg файлы с кодеком opus"
        )
        return

    if file_id:
        context.user_data["pending_audio_file_id"] = file_id
        context.user_data["pending_audio_file_type"] = file_type
        # Change the initial state to awaiting_author_name
        context.user_data["state"] = "awaiting_author_name"
        logger.info(
            f"User {user.id} sent a {file_type} and is now awaiting author name."
        )
        # Change the initial prompt to ask for author
        await update.message.reply_text("Получил голосовое! Теперь введи автора")


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles text input based on the current state of the conversation."""
    user = update.effective_user
    current_state = context.user_data.get("state")

    # Handle author input first
    if current_state == "awaiting_author_name":
        author_name = update.message.text.strip()
        if author_name:
            context.user_data["temp_author_name"] = (
                author_name  # Store author temporarily
            )
            context.user_data["state"] = "awaiting_audio_name"  # Move to next state
            logger.info(
                f"User {user.id} provided author name: '{author_name}'. Now awaiting audio name."
            )
            await update.message.reply_text("Отлично! Теперь введи название для поиска")
        else:
            await update.message.reply_text("Пожалуйста, введи автора.")

    # Handle audio name input second
    elif current_state == "awaiting_audio_name":
        audio_name = update.message.text.strip()
        file_id = context.user_data.pop("pending_audio_file_id", None)
        file_type = context.user_data.pop("pending_audio_file_type", None)
        author_name = context.user_data.pop("temp_author_name", None)  # Retrieve author
        context.user_data.pop("state", None)  # Clear the state

        if audio_name and file_id and file_type and author_name:
            # Store the audio details in the global list
            global cached_audios_data
            cached_audios_data.append(
                {
                    "name": audio_name,
                    "author": author_name,
                    "file_id": file_id,
                    "type": file_type,
                    "telegram_user_id": user.id,  # Store the actual Telegram user ID for reference
                }
            )
            save_audio_metadata()  # Save to file immediately after adding
            logger.info(
                f"Saved {file_type} '{audio_name}' by '{author_name}' (ID: {file_id}) to persistent file for user {user.id}."
            )
            await update.message.reply_text(
                f"Сохранил твое голосовое как '{audio_name}' от '{author_name}'! "
                "Можешь теперь пересылать его в чате, указав имя бота через @"
            )
        else:
            logger.warning(
                f"User {user.id} provided audio name '{audio_name}' but missing other audio details."
            )
            await update.message.reply_text("Что-то пошло не так, повтори с начала")

    else:
        logger.info(f"Received general text from {user.id}: '{update.message.text}'")


async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles inline queries to suggest cached voice/audio messages."""
    query = (
        update.inline_query.query.lower()
    )  # Convert query to lowercase for case-insensitive search
    results = []

    # Use the global cached_audios_data list
    global cached_audios_data

    # Filter audios based on the query (match name or author)
    filtered_audios = [
        item
        for item in cached_audios_data
        if query in item.get("name", "").lower()
        or query in item.get("author", "").lower()
        or not query
    ]

    for item in filtered_audios:
        audio_name = item.get("name", "Unknown Name")
        author_name = item.get("author", "Unknown Author")

        # Combine author and name into the title, separated by " - "
        display_title = f"{author_name} - {audio_name}"

        if item.get("type") == "voice":
            results.append(
                InlineQueryResultCachedVoice(
                    id=str(uuid4()),  # Unique ID for each result
                    voice_file_id=item["file_id"],
                    title=display_title,  # Combined author and name
                )
            )
        elif item.get("type") == "audio":
            results.append(
                InlineQueryResultCachedAudio(
                    id=str(uuid4()),  # Unique ID for each result
                    audio_file_id=item["file_id"],
                    title=display_title,  # Combined author and name
                )
            )

    await update.inline_query.answer(results, cache_time=0)
    logger.info(
        f"Inline query from {update.effective_user.first_name} ({update.effective_user.id}): '{query}' - {len(results)} results."
    )


async def voices_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends the first page of interactive audio list."""
    # Pass update.message.message_id as the message_id to allow editing the initial command message
    await send_paginated_audios(
        update.effective_chat.id, context, page=0, message_id=update.message.message_id
    )


async def send_paginated_audios(
    chat_id: int, context: ContextTypes.DEFAULT_TYPE, page: int, message_id: int = None
) -> None:
    """Sends a page of audio files with pagination buttons."""
    global cached_audios_data

    # Attempt to delete the previous pagination message if provided
    if message_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            logger.info(
                f"Deleted previous pagination message {message_id} in chat {chat_id}."
            )
        except Exception as e:
            logger.warning(
                f"Could not delete previous pagination message {message_id}: {e}"
            )

    if not cached_audios_data:
        await context.bot.send_message(
            chat_id=chat_id, text="Пока нет сохраненных аудио для отображения."
        )
        return

    total_audios = len(cached_audios_data)
    total_pages = (
        total_audios + AUDIOS_PER_PAGE - 1
    ) // AUDIOS_PER_PAGE  # Ceiling division

    # Adjust page number if it's out of bounds after deletion or initial call
    if not (0 <= page < total_pages):
        if total_pages > 0:
            page = max(0, min(page, total_pages - 1))  # Adjust to valid page
        else:
            # If no audios left after adjustment, handle as empty
            await context.bot.send_message(
                chat_id=chat_id, text="Пока нет сохраненных аудио для отображения."
            )
            return

    start_index = page * AUDIOS_PER_PAGE
    end_index = min(start_index + AUDIOS_PER_PAGE, total_audios)

    audios_to_send = cached_audios_data[start_index:end_index]

    # Send the audio files for the current page
    for item in audios_to_send:
        caption = f"Автор: {item.get('author', 'Неизвестный автор')}\nНазвание: {item.get('name', 'Без названия')}"
        try:
            if item.get("type") == "voice":
                await context.bot.send_voice(
                    chat_id=chat_id, voice=item["file_id"], caption=caption
                )
            elif item.get("type") == "audio":
                await context.bot.send_audio(
                    chat_id=chat_id, audio=item["file_id"], caption=caption
                )
        except Exception as e:
            logger.error(f"Error sending audio (ID: {item['file_id']}): {e}")
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"Не удалось отправить аудио '{item.get('name')}'. Возможно, файл недоступен.",
            )
            # Optionally, remove the problematic audio from cached_audios_data and save_audio_metadata() here

    # Create pagination buttons
    keyboard = []
    if page > 0:
        keyboard.append(
            InlineKeyboardButton(
                "⬅️ Предыдущая", callback_data=f"voices_page_{page - 1}"
            )
        )
    if page < total_pages - 1:
        keyboard.append(
            InlineKeyboardButton("Следующая ➡️", callback_data=f"voices_page_{page + 1}")
        )

    reply_markup = InlineKeyboardMarkup([keyboard])

    # Always send a NEW pagination message at the end
    pagination_text = f"Страница {page + 1} из {total_pages}"
    await context.bot.send_message(
        chat_id=chat_id, text=pagination_text, reply_markup=reply_markup
    )


async def pagination_callback_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handles callback queries from pagination buttons."""
    query = update.callback_query
    await query.answer()  # Acknowledge the callback query

    callback_data = query.data
    if callback_data.startswith("voices_page_"):
        try:
            page = int(callback_data.split("_")[2])
            chat_id = query.message.chat.id
            message_id = query.message.message_id  # Get message_id for deleting
            await send_paginated_audios(chat_id, context, page, message_id)
        except ValueError:
            logger.error(f"Invalid pagination callback data: {callback_data}")
            # If editing fails, send a new message to inform the user
            await query.message.reply_text(
                "Произошла ошибка при навигации по страницам."
            )


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
    application.add_handler(CommandHandler("list", list_audios_command))
    application.add_handler(CommandHandler("delete", delete_audio_command))
    application.add_handler(
        CommandHandler("voices", voices_command)
    )  # New: /voices command
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_audio))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input)
    )
    application.add_handler(InlineQueryHandler(inline_query))
    application.add_handler(
        CallbackQueryHandler(pagination_callback_handler, pattern=r"^voices_page_")
    )  # New: Callback handler for pagination

    # Load audio metadata from file at startup
    load_audio_metadata()

    # Start health server using aiohttp
    app = web.Application()
    app.router.add_get("/healthz", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", HEALTH_CHECK_PORT)
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
    # Create storage directory if it doesn't exist (this will be on the mounted volume)
    os.makedirs(AUDIO_STORAGE, exist_ok=True)
    logger.info(f"Ensured '{AUDIO_STORAGE}' directory exists.")

    # Ensure BOT_TOKEN is set
    if not TOKEN:
        logger.error(
            "BOT_TOKEN environment variable is not set. Please set it before running the bot."
        )
        exit(1)

    # Run the main server function
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user (KeyboardInterrupt).")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
