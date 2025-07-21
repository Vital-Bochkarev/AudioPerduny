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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🎤 Hi! Send me voice messages or audio files")

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (keep your existing audio handling code) ...

async def health_check(request):
    return web.Response(text="OK")

async def run_server():
    """Run both Telegram bot and health server"""
    # Create application
    application = Application.builder().token(TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_audio))
    
    # Start health server
    app = web.Application()
    app.router.add_get('/healthz', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', HEALTH_CHECK_PORT)
    await site.start()
    
    # Start Telegram bot
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    # Keep running forever
    while True:
        await asyncio.sleep(3600)  # Sleep forever

if __name__ == "__main__":
    # Create storage directory
    os.makedirs(AUDIO_STORAGE, exist_ok=True)
    
    # Run the server
    asyncio.run(run_server())