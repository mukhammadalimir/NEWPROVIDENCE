# БКРС Telegram-бот + Mini App

Бот для словаря [bkrs.info](https://bkrs.info). Пользователь отправляет слово
(китайское, русское или пиньинь) — и страница bkrs.info с результатом
открывается **прямо внутри Telegram** (Mini App). Отображается всё, что
есть на сайте: переводы, примеры, разбор иероглифов, ссылки.

## Возможности
- Любое сообщение → кнопка «🔎 в БКРС» (открывает сайт внутри Telegram) и «🌐 в браузере».
- Кнопка-меню **БКРС** слева от поля ввода → приложение с поиском и историей запросов.
- Inline-режим: `@имя_бота 你好` в любом чате.

## Установка
1. Создайте бота у [@BotFather](https://t.me/BotFather) (`/newbot`), получите токен.
   Для inline-режима: `/setinline`.
2. Разместите `webapp/index.html` на HTTPS. Проще всего — GitHub Pages:
   Settings → Pages → Branch `main`, папка `/ (root)`. Адрес будет
   `https://<user>.github.io/<repo>/bkrs-bot/webapp/`.
   (Можно пропустить — тогда Mini App сразу открывает bkrs.info.)
3. Запуск:
   ```bash
   cd bkrs-bot
   pip install -r requirements.txt
   cp .env.example .env   # впишите BOT_TOKEN и WEBAPP_URL
   python bot.py
   ```
