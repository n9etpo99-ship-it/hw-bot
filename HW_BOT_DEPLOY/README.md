# 🤖 Homework Helper Bot

Telegram-бот для решения домашних заданий по физике, математике и химии.  
Поддерживает текст и **фотографии задач** (распознавание через Google Gemini).

---

## 🚀 Деплой на Railway (пошагово)

### Шаг 1 — GitHub

1. Зайди на [github.com](https://github.com) → **New repository**
2. Назови репозиторий `hw-bot`, сделай **Private**
3. Нажми **Create repository**
4. Загрузи файлы — нажми **uploading an existing file** и перетащи ВСЕ файлы из папки `HW_BOT` **кроме `config.py`**

> ⚠️ `config.py` содержит секреты — его загружать НЕ НАДО, `.gitignore` его уже исключает

### Шаг 2 — Railway

1. Зайди на [railway.app](https://railway.app)
2. Нажми **Login** → **Login with GitHub**
3. Нажми **New Project** → **Deploy from GitHub repo**
4. Выбери репозиторий `hw-bot`
5. Railway сам определит что это Python-проект

### Шаг 3 — Переменные окружения (ОБЯЗАТЕЛЬНО)

В Railway открой свой проект → вкладка **Variables** → добавь:

| Переменная | Значение |
|---|---|
| `TELEGRAM_TOKEN` | `8726743895:AAEqG...` (твой токен) |
| `OPENROUTER_KEY` | `sk-or-v1-...` (твой ключ) |
| `GEMINI_KEY` | `AQ.Ab8RN6L2...` (твой ключ Gemini) |

### Шаг 4 — Deploy

- Railway автоматически запустит бота после добавления переменных
- Статус должен стать **Active** (зелёный)
- Бот работает 24/7 без твоего ПК ✅

---

## 🔧 Локальный запуск (для разработки)

```bash
pip install -r requirements.txt
python bot.py
```

---

## 📁 Структура проекта

```
bot.py          — основной код бота
renderer.py     — рендер решений в картинки
config.py       — ключи (локально, не заливать!)
requirements.txt
Procfile        — команда запуска для Railway
runtime.txt     — версия Python
```

---

## ⚡ Возможности

- 📝 Решение задач по математике, физике, химии
- 📸 Распознавание фото задач (Google Gemini)
- 🖼️ Красивое оформление решений картинками
- 💬 Помнит контекст диалога
