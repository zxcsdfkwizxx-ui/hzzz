import os
import sqlite3
import logging

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

TOKEN = os.getenv("BOT_TOKEN", "").strip()

ADMIN_ID = 6394152529
CHANNEL_ID = -1003727294346
DB_NAME = "posts.db"

logging.basicConfig(level=logging.INFO)

user_states = {}
admin_states = {}


def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                text TEXT,
                photo TEXT,
                status TEXT DEFAULT 'pending'
            )
        """)


def save_post(user_id, username, text, photo):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.execute("""
            INSERT INTO posts (user_id, username, text, photo)
            VALUES (?, ?, ?, ?)
        """, (user_id, username, text, photo))
        return cursor.lastrowid


def get_post(post_id):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    post = conn.execute(
        "SELECT * FROM posts WHERE id = ?", (post_id,)
    ).fetchone()
    conn.close()
    return post


def update_status(post_id, status):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            "UPDATE posts SET status = ? WHERE id = ?",
            (status, post_id)
        )


def main_keyboard():
    return ReplyKeyboardMarkup(
        [["📝 Написати нову сутність"]],
        resize_keyboard=True
    )


def moderation_keyboard(post_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Прийняти", callback_data=f"accept:{post_id}")],
        [InlineKeyboardButton("❌ Відхилити", callback_data=f"reject:{post_id}")],
        [InlineKeyboardButton("✏️ Відкорегувати", callback_data=f"edit:{post_id}")]
    ])


async def send_long_text(bot, chat_id, text):
    if not text:
        return
    for i in range(0, len(text), 4000):
        await bot.send_message(chat_id, text[i:i + 4000])


async def publish_post(bot, text, photo):
    if photo:
        if text and len(text) <= 1024:
            await bot.send_photo(CHANNEL_ID, photo, caption=text)
        else:
            await bot.send_photo(CHANNEL_ID, photo)
            await send_long_text(bot, CHANNEL_ID, text)
    else:
        await send_long_text(bot, CHANNEL_ID, text)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if user.id == ADMIN_ID:
        await update.message.reply_text(
            "👋 Вітаю, адміністраторе!\n\n"
            "Тут ти отримуватимеш пости на модерацію."
        )
    else:
        await update.message.reply_text(
            "👋 Вітаємо у боті «Сутність Калуша»!\n\n"
            "Тут ти можеш запропонувати пост для нашого каналу.",
            reply_markup=main_keyboard()
        )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_states.pop(user_id, None)

    if user_id == ADMIN_ID:
        admin_states.pop(ADMIN_ID, None)

    await update.message.reply_text(
        "❌ Дію скасовано.",
        reply_markup=main_keyboard()
    )


async def handle_private_message(update, context):
    message = update.message
    user = update.effective_user
    user_id = user.id

    if user_id == ADMIN_ID:
        await handle_admin_message(update, context)
        return

    if message.text == "📝 Написати нову сутність":
        user_states[user_id] = "waiting_post"
        await message.reply_text(
            "📝 Надішліть фото та текст для посту.\n"
            "Можна надіслати тільки текст або тільки фото.\n"
            "Для скасування напишіть /cancel."
        )
        return

    if user_states.get(user_id) != "waiting_post":
        await message.reply_text(
            "Щоб запропонувати пост, натисніть кнопку нижче.",
            reply_markup=main_keyboard()
        )
        return

    text = message.text or message.caption or ""
    photo = message.photo[-1].file_id if message.photo else None

    if not text.strip() and not photo:
        await message.reply_text("⚠️ Надішліть текст або фото.")
        return

    username = f"@{user.username}" if user.username else user.full_name

    post_id = save_post(user_id, username, text, photo)
    user_states.pop(user_id, None)

    await message.reply_text(
        "✅ Дякуємо! Твій пост відправлено на модерацію.",
        reply_markup=main_keyboard()
    )

    if photo:
        await context.bot.send_photo(ADMIN_ID, photo)

    admin_text = (
        f"📩 НОВИЙ ПОСТ НА МОДЕРАЦІЮ\n\n"
        f"🆔 Заявка: #{post_id}\n"
        f"👤 Автор: {username}\n"
        f"🆔 ID автора: {user_id}\n\n"
        f"📝 Текст:\n{text or 'Без тексту'}"
    )

    await context.bot.send_message(
        ADMIN_ID,
        admin_text[:4000],
        reply_markup=moderation_keyboard(post_id)
    )


async def admin_callback(update, context):
    query = update.callback_query

    if query.from_user.id != ADMIN_ID:
        await query.answer("У тебе немає доступу!", show_alert=True)
        return

    await query.answer()

    action, post_id = query.data.split(":")
    post_id = int(post_id)
    post = get_post(post_id)

    if not post or post["status"] != "pending":
        await query.message.reply_text("⚠️ Заявку вже опрацьовано або не знайдено.")
        return

    if action == "accept":
        try:
            await publish_post(context.bot, post["text"], post["photo"])
        except Exception:
            logging.exception("Помилка публікації")
            await query.message.reply_text("❌ Не вдалося опублікувати пост.")
            return

        update_status(post_id, "accepted")

        try:
            await context.bot.send_message(
                post["user_id"],
                "✅ Твій пост прийнято та опубліковано!"
            )
        except Exception:
            pass

        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(f"✅ Пост #{post_id} опубліковано!")

    elif action == "reject":
        admin_states[ADMIN_ID] = {
            "action": "reject",
            "post_id": post_id
        }
        await query.message.reply_text(
            "❌ Напиши причину відхилення.\nДля скасування /cancel."
        )

    elif action == "edit":
        admin_states[ADMIN_ID] = {
            "action": "edit",
            "post_id": post_id
        }
        await query.message.reply_text(
            "✏️ Надішли відредагований текст або фото.\n"
            "Після отримання пост буде опубліковано."
        )


async def handle_admin_message(update, context):
    message = update.message
    state = admin_states.get(ADMIN_ID)

    if not state:
        return

    post_id = state["post_id"]
    post = get_post(post_id)

    if not post or post["status"] != "pending":
        admin_states.pop(ADMIN_ID, None)
        await message.reply_text("⚠️ Заявку вже опрацьовано.")
        return

    if state["action"] == "reject":
        if not message.text or not message.text.strip():
            await message.reply_text("Напиши причину текстом.")
            return

        try:
            await context.bot.send_message(
                post["user_id"],
                f"❌ Твій пост відхилено.\n\nПричина: {message.text}"
            )
        except Exception:
            await message.reply_text("Не вдалося повідомити автора.")
            return

        update_status(post_id, "rejected")
        admin_states.pop(ADMIN_ID, None)
        await message.reply_text("✅ Причину відхилення надіслано.")

    elif state["action"] == "edit":
        text = message.text or message.caption or ""
        photo = message.photo[-1].file_id if message.photo else None

        if not text.strip() and not photo:
            await message.reply_text("Надішли текст або фото.")
            return

        try:
            await publish_post(context.bot, text, photo)
        except Exception:
            logging.exception("Помилка публікації")
            await message.reply_text("❌ Помилка публікації.")
            return

        update_status(post_id, "edited")
        admin_states.pop(ADMIN_ID, None)

        try:
            await context.bot.send_message(
                post["user_id"],
                "✏️ Твій пост відредаговано та опубліковано!"
            )
        except Exception:
            pass

        await message.reply_text("✅ Відредагований пост опубліковано!")


def main():
    if not TOKEN:
        raise ValueError(
            "Не задано BOT_TOKEN у Railway Variables!"
        )

    init_db()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))

    app.add_handler(CallbackQueryHandler(admin_callback))

    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & ~filters.COMMAND,
            handle_private_message
        )
    )

    print("СУТНІСТЬ КАЛУША — БОТ ЗАПУЩЕНИЙ!")

    app.run_polling()


if __name__ == "__main__":
    main()
