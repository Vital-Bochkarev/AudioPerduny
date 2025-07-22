import os
import logging
import asyncio
from pathlib import Path
from uuid import uuid4
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
<<<<<<< HEAD
=======
    CallbackQueryHandler,
>>>>>>> db89903 (after deepseek touch)
    filters,
    ContextTypes,
)
from aiohttp import web
import psycopg
from psycopg.rows import dict_row

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
TOKEN = os.getenv("TELEGRAM_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
AUTHORIZED_USERS = [int(u) for u in os.getenv("AUTHORIZED_USERS", "").split(",") if u]
PORT = int(os.getenv("PORT", 8080))
FLY_APP_NAME = os.getenv("FLY_APP_NAME")

<<<<<<< HEAD
# Volume configuration
VOLUME_PATH = "/data"  # Must match fly.toml mount point
AUDIO_DIR = Path(VOLUME_PATH) / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
=======
# New: Authorized users list
AUTHORIZED_USERS_STR = os.getenv("AUTHORIZED_USERS")
AUTHORIZED_USERS = (
    [int(uid.strip()) for uid in AUTHORIZED_USERS_STR.split(",") if uid.strip()]
    if AUTHORIZED_USERS_STR
    else []
)
>>>>>>> db89903 (after deepseek touch)

# Database setup
async def init_db():
    """Initialize database connection and tables"""
    conn = await psycopg.AsyncConnection.connect(DATABASE_URL)
    async with conn.cursor() as cur:
        await cur.execute("""
            CREATE TABLE IF NOT EXISTS audio_files (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                file_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                position INT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_audio_files_user ON audio_files(user_id);
        """)
        await conn.commit()
    return conn

# ======================
# STORAGE FUNCTIONS
# ======================

async def save_audio_to_volume(file_data: bytes, user_id: int, file_name: str) -> str:
    """Save audio file to volume and return path"""
    user_dir = AUDIO_DIR / str(user_id)
    user_dir.mkdir(exist_ok=True)
    
    file_path = user_dir / f"{uuid4()}_{file_name}"
    file_path.write_bytes(file_data)
    
    return str(file_path.relative_to(AUDIO_DIR))

async def get_audio_url(file_path: str) -> str:
    """Generate URL for audio file (Fly.io specific)"""
    return f"https://{FLY_APP_NAME}.fly.dev/audio/{file_path}"

# ======================
# TELEGRAM HANDLERS
# ======================

<<<<<<< HEAD
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message"""
    user = update.effective_user
    if AUTHORIZED_USERS and user.id not in AUTHORIZED_USERS:
        await update.message.reply_text("You're not authorized to use this bot.")
        return

    await update.message.reply_text(
        "🎤 Audio Manager Bot (Fly Volume)\n\n"
        "Available commands:\n"
        "/add - Upload new audio\n"
        "/list - Show your audio files\n"
        "/move - Reorder audio files\n"
        "/help - Show this message"
    )

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process incoming audio files"""
    user = update.effective_user
    if AUTHORIZED_USERS and user.id not in AUTHORIZED_USERS:
        return

    audio_file = await update.message.audio.get_file()
    file_data = await audio_file.download_as_bytearray()
    
=======
def save_audio_metadata():
    """Saves audio metadata to the JSON file on the persistent volume."""
    global cached_audios_data
>>>>>>> db89903 (after deepseek touch)
    try:
        rel_path = await save_audio_to_volume(file_data, user.id, audio_file.file_name)
        
        async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO audio_files (user_id, file_name, file_path, position) "
                    "VALUES (%s, %s, %s, COALESCE((SELECT MAX(position)+1 FROM audio_files WHERE user_id = %s), 1))",
                    (user.id, audio_file.file_name, rel_path, user.id)
                )
                await conn.commit()
        
        await update.message.reply_text(f"✅ Audio saved: {audio_file.file_name}")
    except Exception as e:
        logger.error(f"Error saving audio: {e}")
        await update.message.reply_text("❌ Failed to save audio")

<<<<<<< HEAD
async def list_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List user's audio files"""
    user = update.effective_user
    async with await psycopg.AsyncConnection.connect(DATABASE_URL, row_factory=dict_row) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, file_name, position FROM audio_files "
                "WHERE user_id = %s ORDER BY position",
                (user.id,)
=======

# --- Telegram Bot Handlers ---


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message when the /start command is issued, with authorization check."""
    user_id = update.effective_user.id
    if AUTHORIZED_USERS and user_id not in AUTHORIZED_USERS:
        await update.message.reply_text(
            "Приветствую. Чтобы воспользоваться ботом, в любом чате набери @Perduny_bot и выбери голосовое для отправки.\n"
            "Отправь в этот чат /voices, чтобы увидеть все доступные голосовые.\n"
            "Добавление и удаление голосовых доступно только администратору."
        )
        logger.info(f"Unauthorized user {user_id} started the bot.")
    else:
        await update.message.reply_text(
            "🎤 Привет! Я помогу тебе управлять голосовыми сообщениями.\n\n"
            "Доступные команды:\n"
            "/add - Добавить новое аудио\n"
            "/list - Показать список всех сохраненных аудио\n"
            "/delete <ID> - Удалить аудио по ID\n"
            "/move <ID> <позиция> - Изменить порядок аудио\n"
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
        if item.get("file_id") == audio_id_to_delete:
            found_and_deleted = True
            logger.info(
                f"Match found! Deleting audio: {item.get('name')} by {item.get('author')}"
>>>>>>> db89903 (after deepseek touch)
            )
            files = await cur.fetchall()
    
    if not files:
        await update.message.reply_text("You have no audio files yet.")
        return
    
    response = "🎧 Your audio files:\n"
    for file in files:
        response += f"{file['position']}. {file['file_name']}\n"
    
    await update.message.reply_text(response)

<<<<<<< HEAD
async def move_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Change audio file position"""
    user = update.effective_user
    if not context.args or len(context.args) != 2:
        await update.message.reply_text("Usage: /move <current_position> <new_position>")
=======
    cached_audios_data = new_cached_audios_data

    if found_and_deleted:
        save_audio_metadata()
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


async def move_audio_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Moves a saved audio file to a new position (admin-only)."""
    global cached_audios_data
    user_id = update.effective_user.id
    if AUTHORIZED_USERS and user_id not in AUTHORIZED_USERS:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        logger.warning(f"Unauthorized attempt to move audio by user: {user_id}")
>>>>>>> db89903 (after deepseek touch)
        return

    try:
<<<<<<< HEAD
        old_pos = int(context.args[0])
        new_pos = int(context.args[1])
        
        async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
            async with conn.cursor() as cur:
                # Get the ID of the file at old position
                await cur.execute(
                    "SELECT id FROM audio_files "
                    "WHERE user_id = %s AND position = %s",
                    (user.id, old_pos)
                )
                file_id = await cur.fetchone()
                
                if not file_id:
                    await update.message.reply_text("No file at that position")
                    return
                
                # Shift positions
                if old_pos < new_pos:
                    await cur.execute(
                        "UPDATE audio_files SET position = position - 1 "
                        "WHERE user_id = %s AND position > %s AND position <= %s",
                        (user.id, old_pos, new_pos)
                    )
                else:
                    await cur.execute(
                        "UPDATE audio_files SET position = position + 1 "
                        "WHERE user_id = %s AND position >= %s AND position < %s",
                        (user.id, new_pos, old_pos)
                    )
                
                # Update the moved file
                await cur.execute(
                    "UPDATE audio_files SET position = %s "
                    "WHERE id = %s",
                    (new_pos, file_id[0])
                )
                
                await conn.commit()
        
        await update.message.reply_text(f"✅ Moved from position {old_pos} to {new_pos}")
    except Exception as e:
        logger.error(f"Error moving audio: {e}")
        await update.message.reply_text("❌ Failed to move audio")

# ======================
# WEB SERVER SETUP
# ======================

async def serve_audio(request):
    """Serve audio files from volume"""
    file_path = AUDIO_DIR / request.match_info['path']
    if not file_path.exists():
        return web.Response(status=404)
    
    return web.FileResponse(file_path)

async def handle_webhook(request):
    """Process Telegram webhook updates"""
    app = request.app
    data = await request.json()
    update = Update.de_json(data, app['bot'].bot)
    await app['bot'].process_update(update)
    return web.Response()

async def start_bot(app):
    """Initialize bot and webhook"""
    application = app['bot']
    await application.initialize()
    await application.bot.set_webhook(
        url=f"https://{FLY_APP_NAME}.fly.dev/webhook",
        drop_pending_updates=True
    )
    await application.start()

async def cleanup_bot(app):
    """Cleanup on shutdown"""
    await app['bot'].shutdown()

def main():
    """Configure and start the application"""
    # Initialize database
    asyncio.run(init_db())
    
    # Create Telegram application
    application = Application.builder().token(TOKEN).build()
    
    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("list", list_audio))
    application.add_handler(CommandHandler("move", move_audio))
    application.add_handler(MessageHandler(filters.AUDIO, handle_audio))
    
    # Create web application
    app = web.Application()
    app['bot'] = application
    
    # Add routes
    app.router.add_post("/webhook", handle_webhook)
    app.router.add_get("/healthz", lambda r: web.Response(text="OK"))
    app.router.add_get("/audio/{path:.+}", serve_audio)
    
    # Setup startup/shutdown
    app.on_startup.append(start_bot)
    app.on_shutdown.append(cleanup_bot)
    
    # Start server
    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
=======
        new_position = int(context.args[1])
    except ValueError:
        await update.message.reply_text(
            "Неверный формат новой позиции. Позиция должна быть числом."
        )
        return

    if not cached_audios_data:
        await update.message.reply_text("Список аудио пуст. Нечего перемещать.")
        return

    audio_to_move = None
    original_index = -1
    for i, item in enumerate(cached_audios_data):
        if item.get("file_id") == audio_id_to_move:
            audio_to_move = item
            original_index = i
            break

    if audio_to_move is None:
        await update.message.reply_text(f"Аудио с ID `{audio_id_to_move}` не найдено.")
        logger.warning(
            f"Attempted to move non-existent audio with ID {audio_id_to_move} by user {user_id}."
        )
        return

    target_index = new_position - 1
    if not (0 <= target_index <= len(cached_audios_data) - 1):
        await update.message.reply_text(
            f"Неверная позиция. Пожалуйста, укажите позицию от 1 до {len(cached_audios_data)}."
        )
        return

    cached_audios_data.pop(original_index)
    cached_audios_data.insert(target_index, audio_to_move)

    save_audio_metadata()
    await update.message.reply_text(
        f"Аудио '{audio_to_move.get('name')}' перемещено на позицию {new_position}."
    )
    logger.info(
        f"Audio '{audio_to_move.get('name')}' (ID: {audio_id_to_move}) moved from {original_index} to {target_index} by user {user_id}."
    )


# [Rest of the file remains exactly the same...]
>>>>>>> db89903 (after deepseek touch)
