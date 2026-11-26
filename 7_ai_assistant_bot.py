"""
ИИ-ассистент в Telegram: бот на базе OpenAI-совместимого API.
Ведёт диалог, помнит последние 20 сообщений (до перезапуска), уточняет запрос.
Пример промпта — для турагентства; свою нишу задай в SYSTEM_PROMPT.

Не вставляй ключи в код — добавь их в Railway → Variables:
  BOT_TOKEN     — токен от @BotFather
  AI_API_KEY    — ключ ИИ-сервиса (старое имя OPENAI_KEY тоже работает)
  AI_BASE_URL   — необязательно: адрес OpenAI-совместимого сервиса
                  (для DeepSeek: https://api.deepseek.com)
  AI_MODEL      — необязательно: модель (по умолчанию gpt-4o-mini;
                  для DeepSeek: deepseek-chat)
  SYSTEM_PROMPT — необязательно: свой системный промпт
  WELCOME_TEXT  — необязательно: своё приветствие на /start
"""

import asyncio, os
from openai import AsyncOpenAI
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart

# ── Настройки — читаются из переменных окружения ─────────────
BOT_TOKEN  = os.environ["BOT_TOKEN"]
# Ключ ИИ-сервиса. AI_API_KEY — новое имя, OPENAI_KEY — старое (тоже работает).
AI_API_KEY = os.environ.get("AI_API_KEY") or os.environ.get("OPENAI_KEY")
if not AI_API_KEY:
    raise SystemExit("Не задан ключ ИИ: добавь AI_API_KEY в Railway → Variables.")
# Необязательно: адрес OpenAI-совместимого сервиса (например, DeepSeek) и модель.
AI_BASE_URL = os.environ.get("AI_BASE_URL") or None
AI_MODEL    = os.environ.get("AI_MODEL", "gpt-4o-mini")

# ── Системный промпт — опиши своё агентство ──────────────────
# ЗАМЕНИ: специализация, менеджер, сайт
DEFAULT_SYSTEM_PROMPT = """
Ты — ИИ-помощник турагентства. Общаешься в Telegram с клиентами.

Твои задачи:
- Помочь клиенту выбрать тур или круиз
- Задавать уточняющие вопросы (бюджет, даты, количество человек, пожелания)
- Этот бот не подключён к каталогу. Собирай критерии поездки и предложи менеджеру уточнить варианты.
- Если клиент готов — предложить связаться с агентом напрямую

Стиль общения: тёплый, дружелюбный, короткие абзацы, по делу.
Не выдумывай цены, рейсы, даты, места, условия или правила въезда. Без подтверждённого источника прямо скажи, что сведения уточнит менеджер.

О нас:
- Специализация: [ЗАМЕНИ: например, круизы, Таиланд, Египет]
- Сайт: [ЗАМЕНИ: адрес сайта]
- Менеджер: [ЗАМЕНИ: имя менеджера]
""".strip()

# Свой промпт можно задать переменной SYSTEM_PROMPT в Railway — без правки кода.
SYSTEM_PROMPT = os.environ.get("SYSTEM_PROMPT") or DEFAULT_SYSTEM_PROMPT
WELCOME_TEXT = os.environ.get("WELCOME_TEXT") or (
    "Привет! Я помогу подобрать тур или круиз. "
    "Расскажи — куда хочется поехать, когда и сколько вас?"
)

# ── История диалогов (в памяти, сбрасывается при рестарте) ───
# Для постоянного хранения замени dict на SQLite (см. 3_database_bot.py)
histories: dict[int, list[dict]] = {}

MAX_HISTORY = 20  # последних сообщений в истории на одного пользователя

# ── OpenAI клиент ─────────────────────────────────────────────
client = AsyncOpenAI(api_key=AI_API_KEY, base_url=AI_BASE_URL)


async def ask_ai(user_id: int, user_text: str) -> str:
    """Отправляет сообщение в OpenAI и возвращает ответ."""
    if user_id not in histories:
        histories[user_id] = []

    histories[user_id].append({"role": "user", "content": user_text})

    # Обрезаем историю чтобы не превышать лимит токенов
    history = histories[user_id][-MAX_HISTORY:]

    response = await client.chat.completions.create(
        model=AI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            *history,
        ],
        temperature=0.7,
        max_tokens=600,
    )

    answer = response.choices[0].message.content
    histories[user_id].append({"role": "assistant", "content": answer})
    return answer


# ── Бот ───────────────────────────────────────────────────────
bot = Bot(BOT_TOKEN)
dp  = Dispatcher()


@dp.message(CommandStart())
async def start(msg: types.Message):
    histories.pop(msg.from_user.id, None)  # сброс истории
    await msg.answer(WELCOME_TEXT)


@dp.message()
async def handle(msg: types.Message):
    if not msg.text:
        await msg.answer("Пока работаю только с текстом — напиши вопрос.")
        return

    await msg.bot.send_chat_action(msg.chat.id, "typing")

    try:
        answer = await ask_ai(msg.from_user.id, msg.text)
        await msg.answer(answer)
    except Exception:
        await msg.answer("Что-то пошло не так. Попробуй ещё раз или напиши менеджеру.")


async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
