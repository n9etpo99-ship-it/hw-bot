"""
bot.py — Telegram-бот для помощи с ДЗ.
ИИ: OpenRouter (text) + Google Gemini (vision через прокси)
Рендер: matplotlib -> PNG картинки с решением
Поддержка: текст + картинки (распознавание через Gemini)
"""
import logging
import asyncio
import urllib3
import base64
import requests as rq

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Прокси для Gemini API (только локально, на Railway не нужен)
import os as _os
_ON_RAILWAY = _os.environ.get("RAILWAY_ENVIRONMENT") is not None
PROXY = {} if _ON_RAILWAY else {"http": "http://127.0.0.1:10809", "https": "http://127.0.0.1:10809"}
GEMINI_KEY = _os.environ.get("GEMINI_KEY", "AQ.Ab8RN6L2wRFnzsJs2LZYFjv2F1Cvi50v8IjOYmqnWOzsvK_Fbg")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key=" + GEMINI_KEY
GEMINI_VISION_MODELS = [
    "gemini-3.5-flash-lite",   # быстрый, стабильный — первым
    "gemini-3.8-flash",        # резервный
    "gemini-2.5-flash",        # резервный
]

from telegram import Update, InputMediaPhoto
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes
)
from telegram.constants import ChatAction

from config import TELEGRAM_TOKEN, OPENROUTER_KEY
from renderer import render_solution, render_pages

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Текстовые модели (fallback список)
MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
FALLBACK_MODELS = [
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3.5-super-vl:free",
    "nvidia/nemotron-3.5-lightning:free",
    "openrouter/free",
]

SYSTEM_PROMPT = (
    "Ты — умный помощник по учёбе для школьников и студентов России. "
    "Отвечай ТОЛЬКО на русском языке. "
    "Для задач по математике, физике и химии давай ПОШАГОВОЕ решение: "
    "Дано → Шаг 1 → Шаг 2 → Ответ. "
    "Формулы пиши просто: x^2, sqrt(x), pi. "
    "Для химии: тип реакции + коэффициенты. "
    "Для физики: формула → подстановка → результат с единицами. "
    "Будь дружелюбным и понятным."
)

# ── История диалогов ──────────────────────────────────────────────
chat_history: dict[int, list] = {}

def get_history(cid: int) -> list:
    h = chat_history.setdefault(cid, [])
    return h

def push(cid: int, role: str, text: str):
    h = get_history(cid)
    h.append({"role": role, "content": text})
    if len(h) > 20:
        chat_history[cid] = h[-20:]

# ── Запрос к OpenRouter ───────────────────────────────────────────
def _call_ai(history: list) -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/hw-bot",
        "X-Title": "Homework Helper Bot",
    }
    for model in FALLBACK_MODELS:
        body = {
            "model": model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 2048,
        }
        try:
            r = rq.post(OPENROUTER_URL, json=body, headers=headers,
                        timeout=60, verify=False)
            if r.status_code == 200:
                log.info(f"Ответил: {model}")
                return r.json()["choices"][0]["message"]["content"].strip()
            elif r.status_code == 429:
                log.warning(f"Rate limit на {model}, пробую следующую...")
                continue
            else:
                log.error(f"OpenRouter {r.status_code} ({model}): {r.text[:200]}")
                continue
        except Exception as e:
            log.error(f"OpenRouter exception ({model}): {e}")
            continue
    return "⚠️ Все модели временно перегружены. Подожди 1 минуту и попробуй снова."

async def ask_ai(cid: int, user_text: str) -> str:
    push(cid, "user", user_text)
    answer = await asyncio.to_thread(_call_ai, get_history(cid))
    push(cid, "assistant", answer)
    return answer

# ── Vision: анализ картинки через Gemini ─────────────────────────
def _call_vision(image_bytes: bytes, caption: str) -> str:
    """Отправляет картинку в Google Gemini vision и возвращает ответ."""
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    prompt = (caption if caption else
              "Это учебное задание. Реши его пошагово на русском языке: "
              "Дано → Шаг 1 → Шаг 2 → Ответ. Объясни каждый шаг.")
    body = {
        "contents": [{
            "parts": [
                {"inline_data": {"mime_type": "image/jpeg", "data": b64}},
                {"text": SYSTEM_PROMPT + "\n\n" + prompt}
            ]
        }],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 2048,
        }
    }
    for model in GEMINI_VISION_MODELS:
        url = GEMINI_URL.format(model=model)
        try:
            r = rq.post(url, json=body, timeout=20,
                        verify=False, proxies=PROXY)
            if r.status_code == 200:
                text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                log.info(f"Gemini vision ответил: {model}")
                return text.strip()
            elif r.status_code == 429:
                log.warning(f"Gemini rate limit: {model}, пробую следующую...")
                continue
            else:
                try:
                    msg = r.json().get("error", {}).get("message", r.text[:200])
                except:
                    msg = r.text[:200]
                log.error(f"Gemini {r.status_code} ({model}): {msg}")
                continue
        except Exception as e:
            log.error(f"Gemini exception ({model}): {e}")
            continue
    return "⚠️ Не удалось распознать картинку. Попробуй описать задачу текстом."

async def ask_vision(image_bytes: bytes, caption: str) -> str:
    return await asyncio.to_thread(_call_vision, image_bytes, caption)

# ── Определение предмета ──────────────────────────────────────────
MATH_KW = ["реши","вычисли","найди","докажи","упрости","уравнение",
           "неравенство","интеграл","производная","функция","теорема",
           "площадь","объём","периметр","угол","треугольник","задача",
           "sin","cos","log","sqrt","x=","y=","^2","^3","²","³"]
PHYS_KW = ["скорость","ускорение","сила","масса","энергия","мощность",
           "давление","температура","ток","напряжение","сопротивление",
           "заряд","волна","частота","период","импульс","физика",
           "ньютон","джоуль","ватт","кинетическая","потенциальная",
           "центростремительное","центробежное","момент","инерция"]
CHEM_KW = ["реакция","уравняй","расставь","коэффициент","молярная",
           "моль","валентность","оксид","кислота","щёлочь","соль",
           "электролиз","гидролиз","окисление","восстановление","химия",
           "вещество","элемент","атом","молекула","ион","fe","h2o","co2"]

def detect_subject(text: str) -> str:
    t = text.lower()
    scores = {
        "math": sum(1 for k in MATH_KW if k in t),
        "phys": sum(1 for k in PHYS_KW if k in t),
        "chem": sum(1 for k in CHEM_KW if k in t),
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "other"

def needs_image(text: str) -> bool:
    if detect_subject(text) in ("math", "phys", "chem"):
        return True
    return any(w in text.lower() for w in
               ["реши","вычисли","найди","посчитай","задача","пример"])

# ── Команды ───────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name or "друг"
    await update.message.reply_text(
        f"Привет, {name}! 👋\n\n"
        "Я твой умный помощник по учёбе:\n\n"
        "📐 *Математика* — уравнения, задачи, неравенства\n"
        "⚗️ *Химия* — коэффициенты, типы реакций\n"
        "⚡ *Физика* — задачи с формулами\n"
        "📚 *Другие предметы* — история, биология, литература\n\n"
        "Для точных наук пришлю *картинку с пошаговым решением* 🖼\n\n"
        "Просто напиши свой вопрос!",
        parse_mode="Markdown"
    )

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Как пользоваться:*\n\n"
        "• Напиши задачу — получишь ответ\n"
        "• Математика/физика/химия → картинка с решением\n"
        "• 📸 Отправь *фото задачи* — бот прочитает и решит!\n"
        "• Бот помнит контекст диалога\n\n"
        "*Команды:*\n"
        "/start — приветствие\n"
        "/help — справка\n"
        "/clear — очистить историю\n\n"
        "*Примеры:*\n"
        "• Реши уравнение 2x^2 - 5x + 3 = 0\n"
        "• Fe + O2 = Fe2O3 расставь коэффициенты\n"
        "• Что такое центростремительное ускорение?\n"
        "• [фото из учебника] — бот сам всё прочитает и решит",
        parse_mode="Markdown"
    )

async def cmd_clear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_history.pop(update.effective_chat.id, None)
    await update.message.reply_text("🗑 История очищена. Начнём заново!")

# ── Отправка решения картинками ──────────────────────────────────
async def send_solution_images(update: Update, ctx, answer: str, title: str) -> bool:
    """
    Рендерит ответ в одну или несколько картинок и отправляет.
    Возвращает True если отправлено успешно.
    """
    await ctx.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.UPLOAD_PHOTO
    )
    try:
        pages = await asyncio.to_thread(render_pages, answer, title)
        if len(pages) == 1:
            await update.message.reply_photo(
                photo=pages[0],
                caption=f"*{title}*",
                parse_mode="Markdown"
            )
        else:
            # Отправляем альбом — до 10 фото за раз
            for batch_start in range(0, len(pages), 10):
                batch = pages[batch_start:batch_start + 10]
                media = []
                for i, buf in enumerate(batch):
                    cap = f"*{title}* [{batch_start+i+1}/{len(pages)}]" if i == 0 else None
                    media.append(InputMediaPhoto(
                        media=buf,
                        caption=cap,
                        parse_mode="Markdown" if cap else None
                    ))
                await update.message.reply_media_group(media=media)
        return True
    except Exception as e:
        log.error(f"Render/send error: {e}")
        return False


# ── Основной обработчик (текст) ───────────────────────────────────
async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid       = update.effective_chat.id
    user_text = update.message.text.strip()
    if not user_text:
        return

    await ctx.bot.send_chat_action(chat_id=cid, action=ChatAction.TYPING)
    answer = await ask_ai(cid, user_text)

    if needs_image(user_text) and len(answer) > 80:
        titles = {
            "math":  "Решение — Математика",
            "phys":  "Решение — Физика",
            "chem":  "Решение — Химия",
            "other": "Ответ",
        }
        title = titles[detect_subject(user_text)]
        sent = await send_solution_images(update, ctx, answer, title)
        if sent:
            return

    clean = answer.replace("**", "*")
    for chunk in [clean[i:i+4000] for i in range(0, len(clean), 4000)]:
        try:
            await update.message.reply_text(chunk, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(chunk)

# ── Обработчик картинок ───────────────────────────────────────────
async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id

    # Берём фото в наилучшем качестве (последнее в списке = самое большое)
    photo = update.message.photo[-1]
    caption = update.message.caption or ""

    await ctx.bot.send_chat_action(chat_id=cid, action=ChatAction.TYPING)
    await update.message.reply_text("🔍 Анализирую картинку, подожди немного...")

    try:
        # Скачиваем файл через Telegram API
        file = await ctx.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()
        image_bytes = bytes(image_bytes)
    except Exception as e:
        log.error(f"Ошибка скачивания фото: {e}")
        await update.message.reply_text("❌ Не удалось загрузить картинку. Попробуй ещё раз.")
        return

    answer = await ask_vision(image_bytes, caption)

    # Сохраняем ответ в историю чата
    push(cid, "user", f"[Картинка] {caption}" if caption else "[Картинка с задачей]")
    push(cid, "assistant", answer)

    # Если решение математическое/физическое — рендерим как изображение
    if needs_image(answer) and len(answer) > 80:
        sent = await send_solution_images(update, ctx, answer, "Решение по картинке")
        if sent:
            return

    clean = answer.replace("**", "*")
    for chunk in [clean[i:i+4000] for i in range(0, len(clean), 4000)]:
        try:
            await update.message.reply_text(chunk, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(chunk)

# ── Запуск ────────────────────────────────────────────────────────
def main():
    log.info("Бот запускается (OpenRouter)...")
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    log.info("Бот запущен! Ctrl+C для остановки.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
