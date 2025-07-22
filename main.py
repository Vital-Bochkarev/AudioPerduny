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
AUDIOS_PER_PAGE = 5  # Changed from 10 to 5 audios per page

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
            "Приветствую. Чтобы воспользоваться ботом, в любом чате набери @Perduny_bot и выбери голосовое для отправки.\n"
            "Отправь в этот чат /voices, чтобы увидеть все доступные голосовые.\n"
            "Добавление и удаление голосовых доступно только администратору."
        )
        logger.info(f"Unauthorized user {user_id} started the bot.")
    else:
        # Existing welcome message for authorized users, now with command suggestions
        await update.message.reply_text(
            "🎤 Привет! Я помогу тебе управлять голосовыми сообщениями.\n\n"
            "Доступные команды:\n"
            "/add - Добавить новое аудио\n"
            "/list - Показать список всех сохраненных аудио\n"
            "/delete <ID> - Удалить аудио по ID\n"
            "/move <ID> <позиция> - Изменить порядок аудио\n"
            "/edit <ID> - Изменить автора и название аудио\n"
            "/voices - Просмотреть интерактивный список всех аудио"
        )
        logger.info(f"Authorized user {user_id} started the bot.")


async def add_audio_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Initiates the audio adding process for authorized users."""
    user = update.effective_user
    if AUTHORIZED_USERS and user.id not in AUTHORIZED_USERS:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        logger.warning(f"Unauthorized attempt to use /add by user: {user.id}")
        return

    context.user_data["state"] = "awaiting_audio_for_add"
    await update.message.reply_text(
        "Пожалуйста, отправь мне голосовое сообщение или аудио файл, которое ты хочешь добавить."
    )
    logger.info(f"User {user.id} initiated /add command.")


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
            f"Attempted to delete non-existent audio with ID {audio_id_to_delete} by user {user_id}."
        )


async def move_audio_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Moves a saved audio file to a new position (admin-only)."""
    global cached_audios_data

    user_id = update.effective_user.id
    if AUTHORIZED_USERS and user_id not in AUTHORIZED_USERS:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        logger.warning(f"Unauthorized attempt to move audio by user: {user_id}")
        return

    if len(context.args) != 2:
        await update.message.reply_text(
            "Использование: /move <ID_аудио> <новая_позиция>\n"
            "Пример: /move AwACAgQAAxk... 3"
        )
        return

    audio_id_to_move = context.args[0].strip()
    try:
        new_position = int(context.args[1])
    except ValueError:
        await update.message.reply_text(
            "Неверный формат новой позиции. Позиция должна быть числом."
        )
        return

    if not cached_audios_data:
        await update.message.reply_text("Список аудио пуст. Нечего перемещать.")
        return

    # Find the audio to move
    audio_to_move = None
    original_index = -1
    for i, item in enumerate(cached_audios_data):
        if item.get("file_id") == audio_id_to_move:  # Corrected variable name
            audio_to_move = item  # Corrected variable name
            original_index = i  # Store original index
            break

    if audio_to_move is None:  # Corrected variable name
        await update.message.reply_text(
            f"Аудио с ID `{audio_id_to_move}` не найдено."
        )  # Corrected variable name
        logger.warning(
            f"Attempted to move non-existent audio with ID {audio_id_to_move} by user {user_id}."
        )  # Corrected variable name
        return

    # Adjust new_position to be 0-indexed and within bounds
    # User provides 1-indexed position, convert to 0-indexed
    target_index = new_position - 1

    # Ensure target_index is within valid range [0, len(list)]
    # len(list) is a valid index for inserting at the very end
    if not (
        0 <= target_index <= len(cached_audios_data) - 1
    ):  # Allow inserting at the end
        await update.message.reply_text(
            f"Неверная позиция. Пожалуйста, укажите позицию от 1 до {len(cached_audios_data)}."
        )
        return

    # Remove the audio from its original position
    cached_audios_data.pop(original_index)

    # Insert the audio at the new position
    cached_audios_data.insert(target_index, audio_to_move)

    save_audio_metadata()  # Save changes to the file
    await update.message.reply_text(
        f"Аудио '{audio_to_move.get('name')}' перемещено на позицию {new_position}."
    )
    logger.info(
        f"Audio '{audio_to_move.get('name')}' (ID: {audio_id_to_move}) moved from {original_index} to {target_index} by user {user_id}."
    )


async def edit_audio_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Initiates the audio editing process for authorized users."""
    user = update.effective_user
    if AUTHORIZED_USERS and user.id not in AUTHORIZED_USERS:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        logger.warning(f"Unauthorized attempt to use /edit by user: {user.id}")
        return

    if not context.args:
        await update.message.reply_text(
            "Пожалуйста, укажите ID аудио для редактирования. Используйте /list, чтобы получить список ID."
        )
        return

    audio_id_to_edit = context.args[0].strip()

    # Find the audio to edit
    found_audio = None
    for item in cached_audios_data:
        if item.get("file_id") == audio_id_to_edit:
            found_audio = item
            break

    if found_audio is None:
        await update.message.reply_text(f"Аудио с ID `{audio_id_to_edit}` не найдено.")
        logger.warning(
            f"Attempted to edit non-existent audio with ID {audio_id_to_edit} by user {user.id}."
        )
        return

    context.user_data["state"] = "awaiting_new_author"
    context.user_data["editing_audio_id"] = audio_id_to_edit
    await update.message.reply_text(
        f"Найдено аудио '{found_audio.get('name')}' от '{found_audio.get('author')}'.\n"
        f"Введите нового автора для этого аудио:"
    )
    logger.info(
        f"User {user.id} initiated /edit command for audio ID: {audio_id_to_edit}"
    )


async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles incoming voice messages and audio files."""
    user = update.effective_user

    # Authorization check for adding audio
    if AUTHORIZED_USERS and user.id not in AUTHORIZED_USERS:
        await update.message.reply_text("У вас нет прав для добавления аудио.")
        logger.warning(f"Unauthorized attempt to add audio by user: {user.id}")
        return

    # New: Check if the user is in the 'awaiting_audio_for_add' state
    if context.user_data.get("state") != "awaiting_audio_for_add":
        await update.message.reply_text(
            "Пожалуйста, используйте команду /add, чтобы добавить новое аудио."
        )
        logger.info(f"User {user.id} sent audio without /add command.")
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

    # Handle author input for adding new audio
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

    # Handle audio name input for adding new audio
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

    # Handle new author input for editing existing audio
    elif current_state == "awaiting_new_author":
        new_author = update.message.text.strip()
        if new_author:
            context.user_data["temp_new_author"] = new_author
            context.user_data["state"] = "awaiting_new_name"
            await update.message.reply_text("Теперь введите новое название для аудио:")
            logger.info(
                f"User {user.id} provided new author: '{new_author}' for editing audio."
            )
        else:
            await update.message.reply_text("Пожалуйста, введите нового автора.")

    # Handle new name input for editing existing audio
    elif current_state == "awaiting_new_name":
        new_name = update.message.text.strip()
        audio_id_to_edit = context.user_data.pop("editing_audio_id", None)
        new_author = context.user_data.pop("temp_new_author", None)
        context.user_data.pop("state", None)  # Clear the state

        if new_name and audio_id_to_edit and new_author:
            global cached_audios_data
            found_and_updated = False
            for item in cached_audios_data:
                if item.get("file_id") == audio_id_to_edit:
                    item["author"] = new_author
                    item["name"] = new_name
                    found_and_updated = True
                    break

            if found_and_updated:
                save_audio_metadata()
                await update.message.reply_text(
                    f"Аудио с ID `{audio_id_to_edit}` успешно обновлено:\n"
                    f"Новый Автор: {new_author}\n"
                    f"Новое Название: {new_name}"
                )
                logger.info(
                    f"Audio ID {audio_id_to_edit} updated by user {user.id} to Author: '{new_author}', Name: '{new_name}'."
                )
            else:
                await update.message.reply_text(
                    "Произошла ошибка: аудио не найдено для обновления."
                )
                logger.warning(
                    f"Attempted to update non-existent audio ID {audio_id_to_edit} by user {user.id}."
                )
        else:
            logger.warning(
                f"User {user.id} provided new name '{new_name}' but missing other editing details."
            )
            await update.message.reply_text(
                "Что-то пошло не так при обновлении аудио. Попробуйте начать /edit заново."
            )

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
        update.effective_chat.id,
        context,
        page=0,
        command_message_id=update.message.message_id,
    )


async def send_paginated_audios(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    page: int,
    command_message_id: int = None,
) -> None:
    """Sends a page of audio files with pagination buttons."""
    # The 'global cached_audios_data' line was removed from here as it's not needed for reading.
    # The SyntaxError you observed indicates it might still be present in your deployed code.
    # Please ensure this line is completely removed from your main.py file.

    # Delete the command message if it was passed
    if command_message_id:
        try:
            await context.bot.delete_message(
                chat_id=chat_id, message_id=command_message_id
            )
            logger.info(
                f"Deleted initial command message {command_message_id} in chat {chat_id}."
            )
        except Exception as e:
            logger.warning(
                f"Could not delete initial command message {command_message_id}: {e}"
            )

    # Delete previous audio messages and pagination message for this chat
    if (
        "last_pagination_message_id" in context.chat_data
        and context.chat_data["last_pagination_message_id"]
    ):
        last_pagination_message_id = context.chat_data.pop("last_pagination_message_id")
        try:
            await context.bot.delete_message(
                chat_id=chat_id, message_id=last_pagination_message_id
            )
            logger.info(
                f"Deleted previous pagination message {last_pagination_message_id} in chat {chat_id}."
            )
        except Exception as e:
            logger.warning(
                f"Could not delete previous pagination message {last_pagination_message_id}: {e}"
            )

    if (
        "last_audio_message_ids" in context.chat_data
        and context.chat_data["last_audio_message_ids"]
    ):
        for msg_id in context.chat_data.pop("last_audio_message_ids"):
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
                logger.info(
                    f"Deleted previous audio message {msg_id} in chat {chat_id}."
                )
            except Exception as e:
                logger.warning(f"Could not delete previous audio message {msg_id}: {e}")

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

    current_audio_message_ids = []

    # Send the audio files for the current page
    for item in audios_to_send:
        # First, send a text message with Author and Name
        text_message = f"Автор: {item.get('author', 'Неизвестный автор')}\nНазвание: {item.get('name', 'Без названия')}"
        text_msg = await context.bot.send_message(chat_id=chat_id, text=text_message)
        current_audio_message_ids.append(text_msg.message_id)

        # Then, send the audio file without any description/caption
        try:
            if item.get("type") == "voice":
                audio_msg = await context.bot.send_voice(
                    chat_id=chat_id, voice=item["file_id"]
                )  # No caption here
            elif item.get("type") == "audio":
                audio_msg = await context.bot.send_audio(
                    chat_id=chat_id, audio=item["file_id"]
                )  # No caption here
            current_audio_message_ids.append(audio_msg.message_id)
        except Exception as e:
            logger.error(f"Error sending audio (ID: {item['file_id']}): {e}")
            error_msg = await context.bot.send_message(
                chat_id=chat_id,
                text=f"Не удалось отправить аудио '{item.get('name')}'. Возможно, файл недоступен.",
            )
            current_audio_message_ids.append(error_msg.message_id)
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
    new_pagination_message = await context.bot.send_message(
        chat_id=chat_id, text=pagination_text, reply_markup=reply_markup
    )

    # Store the message IDs for the current page in chat_data
    context.chat_data["last_pagination_message_id"] = new_pagination_message.message_id
    context.chat_data["last_audio_message_ids"] = current_audio_message_ids


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
            # The message_id of the button's message is the old pagination message
            old_pagination_message_id = query.message.message_id
            await send_paginated_audios(
                chat_id, context, page, command_message_id=None
            )  # Pass None as command_message_id
        except ValueError:
            logger.error(f"Invalid pagination callback data: {callback_data}")
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
    application.add_handler(CommandHandler("add", add_audio_command))
    application.add_handler(CommandHandler("list", list_audios_command))
    application.add_handler(CommandHandler("delete", delete_audio_command))
    application.add_handler(CommandHandler("move", move_audio_command))
    application.add_handler(CommandHandler("edit", edit_audio_command))
    application.add_handler(CommandHandler("voices", voices_command))
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_audio))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input)
    )
    application.add_handler(InlineQueryHandler(inline_query))
    application.add_handler(
        CallbackQueryHandler(pagination_callback_handler, pattern=r"^voices_page_")
    )

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
