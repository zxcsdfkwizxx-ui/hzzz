import os
import asyncio
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

# ==========================================
# НАЛАШТУВАННЯ
# ==========================================

TOKEN = os.getenv("BOT_TOKEN", "").strip()

ADMIN_ID = 6394152529
CHANNEL_ID = -1003727294346

DB_NAME = "posts.db"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

user_states = {}
admin_states = {}


# ==========================================
# БАЗА ДАНИХ
# ==========================================

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
            INSERT INTO posts
            (user_id, username, text, photo)
            VALUES (?, ?, ?, ?)
        """, (user_id, username, text, photo))

        return cursor.lastrowid


def get_post(post_id):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row

    post = conn.execute(
        "SELECT * FROM posts WHERE id = ?",
        (post_id,)
    ).fetchone()

    conn.close()
    return post


def update_status(post_id, status):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            "UPDATE posts SET status = ? WHERE id = ?",
            (status, post_id)
        )


# ==========================================
# КЛАВІАТУРИ
# ==========================================

def main_keyboard():
    return ReplyKeyboardMarkup(
        [["📝 Написати нову сутність"]],
        resize_keyboard=True
    )


def moderation_keyboard(post_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ Прийняти",
                callback_data=f"accept:{post_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "❌ Відхилити",
                callback_data=f"reject:{post_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "✏️ Відкорегувати пост",
                callback_data=f"edit:{post_id}"
            )
        ]
    ])


# ==========================================
# ВІДПРАВКА ДОВГОГО ТЕКСТУ
# ==========================================

async def send_long_text(bot, chat_id, text):
    if not text:
        return

    for i in range(0, len(text), 4000):
        await bot.send_message(
            chat_id=chat_id,
            text=text[i:i + 4000]
        )


# ==========================================
# ПУБЛІКАЦІЯ В КАНАЛ
# ==========================================

async def publish_post(bot, text, photo):

    if photo:

        if text and len(text) <= 1024:
            await bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=photo,
                caption=text
            )

        else:
            await bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=photo
            )

            await send_long_text(
                bot,
                CHANNEL_ID,
                text
            )

    else:
        await send_long_text(
            bot,
            CHANNEL_ID,
            text
        )


# ==========================================
# КОМАНДА START
# ==========================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    if user.id == ADMIN_ID:

        await update.message.reply_text(
            "👋 Вітаю, адміністраторе!\n\n"
            "Ти отримуватимеш тут усі пости "
            "на модерацію.\n\n"
            "Керуй заявками за допомогою кнопок."
        )

    else:

        await update.message.reply_text(
            "👋 Вітаємо у боті «Сутність Калуша»!\n\n"
            "Тут ти можеш запропонувати власний пост "
            "для нашого Telegram-каналу.\n\n"
            "Натисни кнопку нижче 👇",
            reply_markup=main_keyboard()
        )


# ==========================================
# СКАСУВАННЯ ДІЇ
# ==========================================

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    user_states.pop(user_id, None)

    if user_id == ADMIN_ID:
        admin_states.pop(ADMIN_ID, None)

    await update.message.reply_text(
        "❌ Дію скасовано.",
        reply_markup=main_keyboard()
    )


# ==========================================
# ПРИЙМАННЯ ПОСТІВ ВІД ЛЮДЕЙ
# ==========================================

async def handle_private_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = update.message
    user = update.effective_user
    user_id = user.id

    # Адміністратор
    if user_id == ADMIN_ID:
        await handle_admin_message(update, context)
        return

    # Початок створення посту
    if message.text == "📝 Написати нову сутність":

        user_states[user_id] = "waiting_post"

        await message.reply_text(
            "📝 Надішліть фото та текст для посту.\n\n"
            "Можна надіслати:\n"
            "📷 Фото з підписом\n"
            "📝 Лише текст\n"
            "📷 Лише фото\n\n"
            "Для скасування напишіть /cancel"
        )

        return

    # Перевірка стану
    if user_states.get(user_id) != "waiting_post":

        await message.reply_text(
            "Щоб запропонувати пост, натисніть "
            "«📝 Написати нову сутність»."
        )

        return

    text = message.text or message.caption or ""

    photo = None

    if message.photo:
        photo = message.photo[-1].file_id

    if not text.strip() and not photo:

        await message.reply_text(
            "⚠️ Надішліть текст або фото для посту."
        )

        return

    username = (
        f"@{user.username}"
        if user.username
        else user.full_name
    )

    post_id = save_post(
        user_id,
        username,
        text,
        photo
    )

    user_states.pop(user_id, None)

    # Підтвердження автору
    await message.reply_text(
        "✅ Дякуємо за пост!\n\n"
        "Очікуйте на підтвердження адміністрації.",
        reply_markup=main_keyboard()
    )

    # Повідомлення адміністратору
    if photo:
        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=photo
        )

    admin_text = (
        f"📩 НОВИЙ ПОСТ НА МОДЕРАЦІЮ\n\n"
        f"🆔 Заявка: #{post_id}\n"
        f"👤 Автор: {username}\n"
        f"🆔 ID автора: {user_id}\n\n"
        f"📝 Текст:\n{text or 'Без тексту'}"
    )

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=admin_text[:4000],
        reply_markup=moderation_keyboard(post_id)
    )

    if len(admin_text) > 4000:
        await send_long_text(
            context.bot,
            ADMIN_ID,
            admin_text[4000:]
        )


# ==========================================
# КНОПКИ МОДЕРАЦІЇ
# ==========================================

async def admin_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    if query.from_user.id != ADMIN_ID:

        await query.answer(
            "У тебе немає доступу!",
            show_alert=True
        )

        return

    await query.answer()

    action, post_id = query.data.split(":")
    post_id = int(post_id)

    post = get_post(post_id)

    if not post:
        await query.message.reply_text(
            "❌ Пост не знайдено."
        )
        return

    if post["status"] != "pending":

        await query.message.reply_text(
            "⚠️ Ця заявка вже опрацьована."
        )

        return

    # ======================================
    # ПРИЙНЯТИ
    # ======================================

    if action == "accept":

        try:

            await publish_post(
                context.bot,
                post["text"],
                post["photo"]
            )

        except Exception as error:

            logging.exception("Помилка публікації")

            await query.message.reply_text(
                f"❌ Помилка публікації:\n{error}"
            )

            return

        update_status(post_id, "accepted")

        try:

            await context.bot.send_message(
                chat_id=post["user_id"],
                text=(
                    "✅ Твій пост прийнято!\n\n"
                    "Його опубліковано в каналі "
                    "«Сутність Калуша»."
                )
            )

        except Exception:
            pass

        await query.edit_message_reply_markup(
            reply_markup=None
        )

        await query.message.reply_text(
            f"✅ Пост #{post_id} успішно опубліковано!"
        )

    # ======================================
    # ВІДХИЛИТИ
    # ======================================

    elif action == "reject":

        admin_states[ADMIN_ID] = {
            "action": "reject",
            "post_id": post_id
        }

        await query.message.reply_text(
            f"❌ ВІДХИЛЕННЯ ПОСТУ #{post_id}\n\n"
            "Напиши причину відхилення.\n\n"
            "Це повідомлення буде надіслано автору.\n\n"
            "Для скасування напиши /cancel."
        )

    # ======================================
    # ВІДКОРЕГУВАТИ
    # ======================================

    elif action == "edit":

        admin_states[ADMIN_ID] = {
            "action": "edit",
            "post_id": post_id
        }

        await query.message.reply_text(
            f"✏️ РЕДАГУВАННЯ ПОСТУ #{post_id}\n\n"
            "Надішли відкорегований пост.\n\n"
            "Можеш надіслати:\n"
            "📷 Фото з підписом\n"
            "📝 Лише текст\n"
            "📷 Лише фото\n\n"
            "Після отримання він буде опублікований.\n\n"
            "Для скасування напиши /cancel."
        )


# ==========================================
# ПОВІДОМЛЕННЯ ВІД АДМІНІСТРАТОРА
# ==========================================

async def handle_admin_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = update.message

    state = admin_states.get(ADMIN_ID)

    if not state:
        return

    post_id = state["post_id"]

    post = get_post(post_id)

    if not post or post["status"] != "pending":

        admin_states.pop(ADMIN_ID, None)

        await message.reply_text(
            "⚠️ Ця заявка вже опрацьована."
        )

        return

    # ======================================
    # ПРИЧИНА ВІДХИЛЕННЯ
    # ======================================

    if state["action"] == "reject":

        if not message.text or not message.text.strip():

            await message.reply_text(
                "⚠️ Напиши причину звичайним текстом."
            )

            return

        reason = message.text.strip()

        try:

            await context.bot.send_message(
                chat_id=post["user_id"],
                text=(
                    "❌ Твій пост не було прийнято.\n\n"
                    "Причина відхилення:\n"
                    f"{reason}"
                )
            )

        except Exception:

            await message.reply_text(
                "❌ Не вдалося надіслати повідомлення автору.\n"
                "Можливо, він заблокував бота."
            )

            return

        update_status(post_id, "rejected")

        admin_states.pop(ADMIN_ID, None)

        await message.reply_text(
            f"✅ Причину відхилення надіслано автору посту #{post_id}."
        )

    # ======================================
    # ВІДКОРЕГУВАТИ
    # ======================================

    elif state["action"] == "edit":

        text = message.text or message.caption or ""

        photo = None

        if message.photo:
            photo = message.photo[-1].file_id

        if not text.strip() and not photo:

            await message.reply_text(
                "⚠️ Надішли текст або фото для публікації."
            )

            return

        try:

            await publish_post(
                context.bot,
                text,
                photo
            )

        except Exception as error:

            logging.exception("Помилка публікації")

            await message.reply_text(
                f"❌ Не вдалося опублікувати пост:\n{error}"
            )

            return

        update_status(post_id, "edited")

        admin_states.pop(ADMIN_ID, None)

        try:

            await context.bot.send_message(
                chat_id=post["user_id"],
                text=(
                    "✏️ Твій пост було відкореговано "
                    "адміністрацією та опубліковано "
                    "в каналі «Сутність Калуша»!"
                )
            )

        except Exception:
            pass

        await message.reply_text(
            f"✅ Відкорегований пост #{post_id} опубліковано!"
        )


# ==========================================
# ЗАПУСК БОТА
# ==========================================

def main():

    if not TOKEN:
        raise ValueError(
            "Не задано BOT_TOKEN у Railway Variables!"
        )

    init_db()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("cancel", cancel)
    )

    app.add_handler(
        CallbackQueryHandler(admin_callback)
    )

    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & ~filters.COMMAND,
            handle_private_message
        )
    )

    print("================================")
    print("СУТНІСТЬ КАЛУША")
    print("Бот успішно запущений!")
    print("================================")

    app.run_polling()


if __name__ == "__main__":
    asyncio.set_event_loop(asyncio.new_event_loop())
    main()
