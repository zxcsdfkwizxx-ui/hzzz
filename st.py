import os
import asyncio
import sqlite3
import logging
import json

from telegram import (
    Update,
    InputMediaPhoto,
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

# НАЛАШТУВАННЯ

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


# БАЗА ДАНИХ

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


# КЛАВІАТУРИ

def main_keyboard():
    return ReplyKeyboardMarkup(
        [["📝 Написати нову сутність"]],
        resize_keyboard=True
    )


def moderation_keyboard(post_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "✅ Прийняти",
            callback_data=f"accept:{post_id}"
        )],
        [InlineKeyboardButton(
            "❌ Відхилити",
            callback_data=f"reject:{post_id}"
        )],
        [InlineKeyboardButton(
            "✏️ Відкорегувати пост",
            callback_data=f"edit:{post_id}"
        )]
    ])


# ДОВГИЙ ТЕКСТ

async def send_long_text(bot, chat_id, text):
    if not text:
        return

    for i in range(0, len(text), 4000):
        await bot.send_message(
            chat_id=chat_id,
            text=text[i:i + 4000]
        )


# ПУБЛІКАЦІЯ В КАНАЛ

async def publish_post(bot, text, photo):
    photos = []

    if photo:
        if isinstance(photo, list):
            photos = photo
        else:
            try:
                decoded = json.loads(photo)
                photos = decoded if isinstance(decoded, list) else [photo]
            except (TypeError, json.JSONDecodeError):
                photos = [photo]

    if photos:
        if len(photos) == 1:
            await bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=photos[0],
                caption=text[:1024] if text and len(text) <= 1024 else None
            )
        else:
            media = [
                InputMediaPhoto(
                    media=file_id,
                    caption=(
                        text[:1024]
                        if index == 0 and text and len(text) <= 1024
                        else None
                    )
                )
                for index, file_id in enumerate(photos[:10])
            ]

            await bot.send_media_group(
                chat_id=CHANNEL_ID,
                media=media
            )

        if text and len(text) > 1024:
            await send_long_text(bot, CHANNEL_ID, text)

    else:
        await send_long_text(bot, CHANNEL_ID, text)


# START

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


# СКАСУВАННЯ

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    user_states.pop(user_id, None)

    if user_id == ADMIN_ID:
        admin_states.pop(ADMIN_ID, None)

    await update.message.reply_text(
        "❌ Дію скасовано.",
        reply_markup=main_keyboard()
    )


# ОБРОБКА АЛЬБОМІВ

async def _finish_album(key, context):
    try:
        await asyncio.sleep(1.2)

        album = context.application.bot_data.get(
            "albums", {}
        ).pop(key, None)

        if not album:
            return

        messages = sorted(
            album["messages"],
            key=lambda item: item.message_id
        )

        await process_user_post(messages, context)

    except asyncio.CancelledError:
        raise

    except Exception:
        logging.exception("Помилка обробки альбому")


async def process_user_post(messages, context):
    message = messages[0]
    user = message.from_user
    user_id = user.id

    if user_states.get(user_id) != "waiting_post":
        await message.reply_text(
            "Щоб запропонувати пост, натисніть "
            "«📝 Написати нову сутність»."
        )
        return

    text = next(
        (m.caption for m in messages if m.caption),
        None
    ) or ""

    photos = [
        m.photo[-1].file_id
        for m in messages
        if m.photo
    ]

    if not text.strip() and not photos:
        await message.reply_text(
            "⚠️ Надішліть текст або фото для посту."
        )
        return

    username = (
        f"@{user.username}"
        if user.username
        else user.full_name
    )

    photo_data = json.dumps(
        photos,
        ensure_ascii=False
    ) if photos else None

    post_id = save_post(
        user_id,
        username,
        text,
        photo_data
    )

    user_states.pop(user_id, None)

    await message.reply_text(
        "✅ Дякуємо за пост!\n\n"
        "Очікуйте на підтвердження адміністрації.",
        reply_markup=main_keyboard()
    )

    if len(photos) == 1:
        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=photos[0]
        )

    elif len(photos) > 1:
        await context.bot.send_media_group(
            chat_id=ADMIN_ID,
            media=[
                InputMediaPhoto(media=file_id)
                for file_id in photos[:10]
            ]
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


# ПОВІДОМЛЕННЯ КОРИСТУВАЧІВ

async def handle_private_message(update, context):
    message = update.message
    user_id = update.effective_user.id

    if user_id == ADMIN_ID:
        await handle_admin_message(update, context)
        return

    if message.text == "📝 Написати нову сутність":
        user_states[user_id] = "waiting_post"

        await message.reply_text(
            "📝 Надішліть фото та текст для посту.\n\n"
            "Можна надіслати альбом до 10 фото, "
            "фото з підписом або лише текст.\n\n"
            "Для скасування напишіть /cancel"
        )
        return

    if user_states.get(user_id) != "waiting_post":
        await message.reply_text(
            "Щоб запропонувати пост, натисніть "
            "«📝 Написати нову сутність»."
        )
        return

    if message.media_group_id:
        key = (
            message.chat_id,
            message.media_group_id
        )

        albums = context.application.bot_data.setdefault(
            "albums", {}
        )

        album = albums.setdefault(
            key,
            {"messages": [], "task": None}
        )

        album["messages"].append(message)

        if album["task"] and not album["task"].done():
            album["task"].cancel()

        album["task"] = asyncio.create_task(
            _finish_album(key, context)
        )

        return

    await process_user_post([message], context)


# МОДЕРАЦІЯ

async def admin_callback(update, context):
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

    elif action == "edit":
        admin_states[ADMIN_ID] = {
            "action": "edit",
            "post_id": post_id
        }

        await query.message.reply_text(
            f"✏️ РЕДАГУВАННЯ ПОСТУ #{post_id}\n\n"
            "Надішли відкорегований пост.\n\n"
            "Можеш надіслати фото з підписом, "
            "лише текст або лише фото.\n\n"
            "Після отримання він буде опублікований.\n\n"
            "Для скасування напиши /cancel."
        )


# ПОВІДОМЛЕННЯ АДМІНІСТРАТОРА

async def handle_admin_message(update, context):
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


# ПОМИЛКИ

async def error_handler(update, context):
    logging.error(
        "Необроблена помилка під час обробки Telegram update",
        exc_info=(
            type(context.error),
            context.error,
            context.error.__traceback__
        ) if context.error else None,
    )


# ЗАПУСК БОТА

def main():
    if not TOKEN:
        raise RuntimeError(
            "Не задано BOT_TOKEN у Railway Variables. "
            "Додайте змінну BOT_TOKEN зі значенням токена бота."
        )

    init_db()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(admin_callback))

    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & ~filters.COMMAND,
            handle_private_message,
        )
    )

    app.add_error_handler(error_handler)

    print("================================", flush=True)
    print("СУТНІСТЬ КАЛУША", flush=True)
    print("Запуск Telegram-бота...", flush=True)
    print("================================", flush=True)

    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )


if __name__ == "__main__":
    main()
