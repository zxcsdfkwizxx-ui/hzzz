
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
