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

# Volume configuration
VOLUME_PATH = "/data"  # Must match fly.toml mount point
AUDIO_DIR = Path(VOLUME_PATH) / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

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

async def list_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List user's audio files"""
    user = update.effective_user
    async with await psycopg.AsyncConnection.connect(DATABASE_URL, row_factory=dict_row) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, file_name, position FROM audio_files "
                "WHERE user_id = %s ORDER BY position",
                (user.id,)
            )
            files = await cur.fetchall()
    
    if not files:
        await update.message.reply_text("You have no audio files yet.")
        return
    
    response = "🎧 Your audio files:\n"
    for file in files:
        response += f"{file['position']}. {file['file_name']}\n"
    
    await update.message.reply_text(response)

async def move_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Change audio file position"""
    user = update.effective_user
    if not context.args or len(context.args) != 2:
        await update.message.reply_text("Usage: /move <current_position> <new_position>")
        return

    try:
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
