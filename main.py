import asyncio
import json
import logging
import os
import re
import sqlite3

from aiogram import Bot, Dispatcher
from aiogram import F
from aiogram.filters import CommandStart
from aiogram.types import (BusinessConnection, CallbackQuery, FSInputFile,
                           InlineKeyboardButton, InlineKeyboardMarkup, Message)

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ["BOT_TOKEN"].strip()
ADMIN_CHAT_ID = int(os.environ["ADMIN_CHAT_ID"].strip())
DB_PATH = os.environ.get("DB_PATH", "state.db")
CHANNEL = os.environ.get("CHANNEL", "@info_anya").strip()
GUIDE_FILE = os.environ.get("GUIDE_FILE", "guide.pdf").strip()

GREETING = (
    "Здравствуйте! Меня зовут Анна, я турагент и подберу вам тур. "
    "Отвечу на несколько вопросов, это займёт минуту, и я сразу начну подбор."
)
STEPS = [
    ("dest", "Куда хотите поехать? Страна или направление, можно несколько."),
    ("dates", "Из какого города вылет и на какие даты?"),
    ("party", "Сколько человек летит? Если с детьми, напишите их возраст."),
    ("nights", "Сколько ночей хотите отдыхать?"),
    ("budget", "Какой примерный бюджет на всех?"),
    ("contact", "Как с вами связаться, если пропадёте? Почта или телефон, можно пропустить."),
]
DONE = (
    "Спасибо, всё записала. Подберу варианты и напишу вам лично. "
    "Отвечаю ежедневно с 5:00 до 20:00 по Москве."
)

db = sqlite3.connect(DB_PATH)
db.execute("CREATE TABLE IF NOT EXISTS chats (chat_id INTEGER PRIMARY KEY, step INTEGER, answers TEXT, paused INTEGER DEFAULT 0, source TEXT)")
db.execute("CREATE TABLE IF NOT EXISTS conns (id TEXT PRIMARY KEY, owner_id INTEGER, enabled INTEGER)")
db.commit()


def get_chat(chat_id):
    r = db.execute("SELECT step, answers, paused, source FROM chats WHERE chat_id=?", (chat_id,)).fetchone()
    return None if r is None else {"step": r[0], "answers": json.loads(r[1]), "paused": r[2], "source": r[3]}


def save_chat(chat_id, step, answers, paused=0, source=""):
    db.execute("INSERT OR REPLACE INTO chats VALUES (?,?,?,?,?)", (chat_id, step, json.dumps(answers, ensure_ascii=False), paused, source))
    db.commit()


bot = Bot(BOT_TOKEN)
dp = Dispatcher()


@dp.business_connection()
async def on_connection(c: BusinessConnection):
    db.execute("INSERT OR REPLACE INTO conns VALUES (?,?,?)", (c.id, c.user.id, int(c.is_enabled)))
    db.commit()
    logging.info("business connection %s enabled=%s", c.id, c.is_enabled)
    await bot.send_message(ADMIN_CHAT_ID, f"Бот {'подключён' if c.is_enabled else 'отключён'} к аккаунту {c.user.full_name}.")


async def send_card(chat: dict, m: Message):
    a = chat["answers"]
    u = m.from_user
    link = f"@{u.username}" if u.username else f"id {u.id}"
    text = (
        f"Новая заявка: {u.full_name} ({link})\n"
        f"Источник: {chat['source'] or 'не указан'}\n\n"
        f"Направление: {a.get('dest','-')}\n"
        f"Вылет и даты: {a.get('dates','-')}\n"
        f"Состав: {a.get('party','-')}\n"
        f"Ночей: {a.get('nights','-')}\n"
        f"Бюджет: {a.get('budget','-')}\n"
        f"Контакт: {a.get('contact','-')}"
    )
    await bot.send_message(ADMIN_CHAT_ID, text)


@dp.business_message()
async def on_message(m: Message):
    cid = m.business_connection_id
    row = db.execute("SELECT owner_id FROM conns WHERE id=?", (cid,)).fetchone()
    owner_id = row[0] if row else None
    chat_id = m.chat.id
    chat = get_chat(chat_id)

    # Анна сама написала в чат: бот замолкает
    if m.from_user and m.from_user.id == owner_id:
        if chat:
            save_chat(chat_id, chat["step"], chat["answers"], 1, chat["source"])
        return
    if chat and chat["paused"]:
        return
    text = (m.text or m.caption or "").strip()
    if not text:
        return

    async def say(t):
        await bot.send_message(chat_id, t, business_connection_id=cid)

    if chat is None:
        src = re.search(r"\(([^)]*страниц[^)]*)\)", text)
        save_chat(chat_id, 0, {}, 0, src.group(1) if src else "")
        await say(GREETING)
        await say(STEPS[0][1])
        return

    step, answers = chat["step"], chat["answers"]
    answers[STEPS[step][0]] = text
    step += 1
    if step < len(STEPS):
        save_chat(chat_id, step, answers, 0, chat["source"])
        await say(STEPS[step][1])
    else:
        chat.update(step=step, answers=answers)
        save_chat(chat_id, step, answers, 1, chat["source"])  # дальше пишет Анна
        await say(DONE)
        await send_card(chat, m)


def sub_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Подписаться на канал", url=f"https://t.me/{CHANNEL.lstrip('@')}")],
        [InlineKeyboardButton(text="Я подписался, получить гайд", callback_data="check_sub")],
    ])


@dp.message(CommandStart())
async def on_start(m: Message):
    await m.answer(
        "Привет! Гайд пришлю в подарок за подписку на канал «Туры с умом». "
        "Подпишитесь и нажмите вторую кнопку.",
        reply_markup=sub_kb(),
    )


@dp.callback_query(F.data == "check_sub")
async def on_check(c: CallbackQuery):
    try:
        member = await bot.get_chat_member(CHANNEL, c.from_user.id)
        ok = member.status in ("member", "administrator", "creator")
    except Exception as e:
        logging.error("get_chat_member failed: %s", e)
        await c.answer("Не удалось проверить подписку, напишите Анне.", show_alert=True)
        return
    if not ok:
        await c.answer("Подписки пока не вижу. Подпишитесь и нажмите ещё раз.", show_alert=True)
        return
    await c.answer()
    if os.path.exists(GUIDE_FILE):
        await bot.send_document(c.from_user.id, FSInputFile(GUIDE_FILE), caption="Ваш гайд. Приятных поездок!")
    else:
        logging.error("guide file %s not found", GUIDE_FILE)
        await bot.send_message(c.from_user.id, "Гайд сейчас недоступен, Анна пришлёт его лично.")


async def main():
    await bot.delete_webhook(drop_pending_updates=False)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
