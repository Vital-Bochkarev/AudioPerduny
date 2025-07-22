import os
import json
from telegram import Update, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

AUDIO_INDEX_FILE = "audio_index.json"
AUDIO_DIR = "audio_messages"

if not os.path.exists(AUDIO_DIR):
    os.makedirs(AUDIO_DIR)

def load_audio_index():
    if os.path.exists(AUDIO_INDEX_FILE):
        with open(AUDIO_INDEX_FILE, "r") as f:
            return json.load(f)
    return []

def save_audio_index(index):
    with open(AUDIO_INDEX_FILE, "w") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

audio_index = load_audio_index()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Отправь мне голосовое сообщение или используй /search <текст> для поиска. Используй /move <название> <новая позиция> для перемещения записи.")

async def save_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    voice = update.message.voice
    if not voice:
        await update.message.reply_text("Это не голосовое сообщение.")
        return

    file_id = voice.file_id
    file = await context.bot.get_file(file_id)
    file_name = f"{file_id}.ogg"
    file_path = os.path.join(AUDIO_DIR, file_name)
    await file.download_to_drive(file_path)

    title = update.message.caption or f"Аудио от {update.message.from_user.first_name}"

    audio_index.append({"file": file_name, "title": title})
    save_audio_index(audio_index)

    await update.message.reply_text(f"Сохранено как: {title}")

async def search_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Введите текст для поиска: /search <текст>")
        return

    results = [item for item in audio_index if query.lower() in item["title"].lower()]

    if not results:
        await update.message.reply_text("Ничего не найдено.")
        return

    for item in results:
        audio_path = os.path.join(AUDIO_DIR, item["file"])
        if os.path.exists(audio_path):
            await update.message.reply_audio(audio=InputFile(audio_path), caption=item["title"])

async def move_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /move <название> <новая_позиция>")
        return

    title = " ".join(context.args[:-1])
    try:
        new_pos = int(context.args[-1])
    except ValueError:
        await update.message.reply_text("Позиция должна быть числом.")
        return

    for i, item in enumerate(audio_index):
        if item["title"].lower() == title.lower():
            moved_item = audio_index.pop(i)
            new_pos = max(0, min(new_pos, len(audio_index)))
            audio_index.insert(new_pos, moved_item)
            save_audio_index(audio_index)
            await update.message.reply_text(f"Запись '{title}' перемещена на позицию {new_pos}.")
            return

    await update.message.reply_text("Запись с таким названием не найдена.")

if __name__ == '__main__':
    import os
    from dotenv import load_dotenv
    load_dotenv()

    TOKEN = os.getenv("TELEGRAM_TOKEN")
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("search", search_audio))
    application.add_handler(CommandHandler("move", move_audio))
    application.add_handler(MessageHandler(filters.VOICE, save_voice))

    application.run_polling()
