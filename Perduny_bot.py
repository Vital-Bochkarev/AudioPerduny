import json
import uuid
from pathlib import Path
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InlineQueryResultVoice,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    InlineQueryHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

TOKEN = "7581905632:AAF6EjsfJ3OZ6t179s7vVoP6fkwyrJELPY4"  # Replace with your token
DB_FILE = "voice_db.json"

if Path(DB_FILE).exists():
    with open(DB_FILE, "r") as f:
        voice_db = json.load(f)
else:
    voice_db = []

def save_db():
    with open(DB_FILE, "w") as f:
        json.dump(voice_db, f)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send me a voice message and I'll save it!")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    voice = update.message.voice
    context.user_data["pending_voice"] = {
        "file_id": voice.file_id,
        "file_unique_id": voice.file_unique_id,
    }
    await update.message.reply_text("Voice received! Now send me a caption for it.")

async def handle_caption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "pending_voice" not in context.user_data:
        return
    voice_info = context.user_data.pop("pending_voice")
    caption = update.message.text.strip()
    voice_entry = {
        "id": str(uuid.uuid4()),
        "file_id": voice_info["file_id"],
        "file_unique_id": voice_info["file_unique_id"],
        "caption": caption,
    }
    voice_db.append(voice_entry)
    save_db()
    await update.message.reply_text(f"Saved voice with caption: {caption}")

async def list_audios(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not voice_db:
        await update.message.reply_text("No audios saved yet.")
        return
    buttons = [
        [InlineKeyboardButton(v["caption"] or "No title", callback_data=v["file_id"])]
        for v in voice_db[:30]
    ]
    markup = InlineKeyboardMarkup(buttons)
    await update.message.reply_text("Choose an audio to send:", reply_markup=markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    file_id = query.data
    await query.message.reply_voice(voice=file_id)

async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query.lower()
    results = []
    for v in voice_db:
        if query in (v.get("caption") or "").lower():
            results.append(
                InlineQueryResultVoice(
                    id=v["id"],
                    voice_file_id=v["file_id"],
                    title=v["caption"] or "No title",
                )
            )
    await update.inline_query.answer(results[:10])

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("list", list_audios))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_caption))
    app.add_handler(InlineQueryHandler(inline_query))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.run_polling()

if __name__ == "__main__":
    main()
