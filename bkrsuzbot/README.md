# BKRSUZBOT — китайский словарь и переводчик в Telegram

Telegram-бот **@Bkrsuzbot** + Telegram Mini App для перевода и изучения китайского языка.
Основной язык интерфейса и результатов — узбекский (латиница), дополнительно — русский.

- Бот: слово или текст → сразу карточка/перевод прямо в чате, озвучка голосовым сообщением.
- Mini App: подробные карточки, история, избранное, повторение, настройки, админ-панель.
- Регистрация не нужна: пользователь определяется по Telegram ID.

## Содержание

1. [Архитектура](#1-архитектура)
2. [Источники данных и честность результатов](#2-источники-данных-и-честность-результатов)
3. [Настройка бота в BotFather](#3-настройка-бота-в-botfather)
4. [API-ключи: какие нужны и где их взять](#4-api-ключи-какие-нужны-и-где-их-взять)
5. [Платные сервисы](#5-платные-сервисы)
6. [Локальный запуск](#6-локальный-запуск)
7. [Размещение на сервере (Docker Compose)](#7-размещение-на-сервере-docker-compose)
8. [Проверки и как их повторить](#8-проверки-и-как-их-повторить)
9. [Безопасность](#9-безопасность)
10. [Администрирование](#10-администрирование)
11. [Решения, принятые без отдельных указаний](#11-решения-принятые-без-отдельных-указаний)
12. [Следующий этап](#12-следующий-этап)

---

## 1. Архитектура

```
Telegram ──► bot (aiogram 3, long polling) ─┐
                                            ├─► services (поиск, словарь, перевод, озвучка, AI)
Mini App ──► api (FastAPI) ─────────────────┘        │
   (React, раздаётся тем же api)                     ├─► PostgreSQL (словарь, пользователи, кэш)
                                                     ├─► Google Cloud Translation API (v2)
                                                     ├─► Google Cloud Text-to-Speech (cmn-CN)
                                                     └─► Claude API (необязательно)
```

| Часть | Путь | Стек |
|---|---|---|
| Бот | `backend/app/bot/` | Python 3.12, aiogram 3 |
| API Mini App | `backend/app/api/` | FastAPI, проверка initData |
| Поиск и словарь | `backend/app/services/` | SQLAlchemy 2 (async), jieba, pypinyin |
| БД и миграции | `backend/app/models.py`, `backend/alembic/` | PostgreSQL 16, Alembic |
| Mini App | `miniapp/` | React 18 + TypeScript + Vite |
| Запуск | `docker-compose.yml`, `Dockerfile` | db, migrate, api, bot, caddy (HTTPS) |

### Поиск

Язык ввода определяется автоматически (`backend/app/text/detect.py`):

| Ввод | Результат |
|---|---|
| Иероглифы `鱼`, `我喜欢吃鱼。` | китайский: слово → карточка; фраза → перевод + пиньинь + разбор по словам |
| `yu2`, `yú`, `ni3 hao3`, `nǐ hǎo` | пиньинь (тоны цифрами или знаками) → список слов |
| `baliq`, `o‘qimoq`, `o'qimoq`, `ўқимоқ` | узбекский (латиница/кириллица, все варианты o‘ g‘) |
| `рыба` | русский |
| `yu`, `ni hao`, `men`, `салом` | **неоднозначно** — бот спрашивает, как искать, а не угадывает |

Пользователь всегда может выбрать направление вручную: в Mini App — переключатели языков и
кнопка смены направления, в боте — кнопки «Искать как …».

### Карточка слова

Иероглифы крупно, упрощённое/традиционное написание, пиньинь, приблизительное звучание
(помечено как «taxminiy»), счётное слово, значения по смыслу, употребление, словосочетания,
примеры с переводом, кнопки озвучки, ⭐ избранное, «Сообщить об ошибке», «Поделиться».

**Разные чтения не смешиваются**: каждое чтение (`行 xíng` / `行 háng`) — отдельный блок со
своими значениями, примерами и словосочетаниями. Словосочетания распределяются по чтению
иероглифа внутри слова (`银行 yínháng` → к `háng`, `进行 jìnxíng` → к `xíng`).

### Схема базы данных

Миграция `backend/alembic/versions/0001_initial_schema.py`:

| Таблица | Назначение |
|---|---|
| `dict_entries` | словарные статьи: `source` = `cedict` (CC-CEDICT) или `curated` (редакция); одно написание + одно чтение на строку |
| `dict_glosses` | обратный индекс узбекских/русских значений редакционных карточек |
| `users` | Telegram ID, язык интерфейса, язык перевода, голос |
| `search_history` | история поиска (последние 50 запросов на пользователя) |
| `favorites` | избранное + интервальное повторение (коробки Лейтнера) |
| `error_reports` | сообщения «Сообщить об ошибке» |
| `service_events` | статистика запросов и ошибок сервисов |
| `feature_flags` | включение/выключение функций админом |
| `cache_items` | кэш машинного перевода и AI-ответов |
| `bot_payloads` | короткие ссылки для кнопок бота (лимит Telegram — 64 байта), чистятся через 30 дней |

---

## 2. Источники данных и честность результатов

Каждое значение в интерфейсе подписано источником:

| Метка | Что это |
|---|---|
| ✅ **Tahririyat lug‘ati** / Словарь редакции | редакционная карточка, проверенная админом |
| ✍️ **Tahririyat · tekshirilmagan** | редакционная карточка, ещё не проверенная |
| 📖 **CC-CEDICT · inglizcha** (`EN`) | английское определение из CC-CEDICT — **не** выдаётся за узбекский словарь |
| 🤖 **Mashina tarjimasi** (`MT`) | машинный перевод Google (определений CC-CEDICT, словосочетаний, фраз) |
| ✨ **AI yaratgan** | пояснение/примеры от Claude, только по кнопке, с пометкой «возможны ошибки» |

- **CC-CEDICT** (124 188 статей, лицензия CC BY-SA 4.0, https://cc-cedict.org) — иероглифы,
  чтения, английские определения, счётные слова. Источник указан в настройках Mini App.
- **Узбекский/русский словарь редакции.** Свободного китайско-узбекского словаря с подходящей
  лицензией нет, поэтому есть таблица редакционных карточек, которые админ пополняет через
  Mini App. В репозитории — **стартовый набор из 28 карточек** (`backend/app/data/seed_entries.json`),
  подготовленный вручную и помеченный как непроверенный. Это не полноценный словарь: его нужно
  проверить и расширять.
- **Материалы БКРС не используются** (ни база, ни тексты) — разрешения на это нет.
- Если для слова нет узбекского значения и не подключён перевод, карточка прямо говорит
  «O‘zbekcha ma’no hali lug‘atda yo‘q» и показывает английское определение с меткой.
- Частоты слов для сортировки — из словаря jieba (MIT). Пиньинь фраз и AI-примеров вычисляется
  библиотекой pypinyin (MIT), а не берётся у AI.

---

## 3. Настройка бота в BotFather

**Имя пользователя.** Имена ботов в Telegram не зависят от регистра, поэтому `BKRSUZBOT` и
`Bkrsuzbot` — одно и то же имя. Проверка через Bot API (`getMe`) для выданного токена вернула
`@Bkrsuzbot` (id 8791618844): **имя уже занято вашим ботом**, ничего регистрировать не нужно.
Для нового бота: `/newbot` → имя → username, оканчивающийся на `bot`; если занято, BotFather
сразу ответит «Sorry, this username is already taken».

Шаги в [@BotFather](https://t.me/BotFather):

1. `/newbot` (если бота ещё нет) → получить **токен** → вписать в `.env` как `BOT_TOKEN`.
2. `/setinline` → выбрать бота → placeholder, например `so‘z yoki matn…` — включает поиск
   `@Bkrsuzbot 鱼` в любом чате и кнопку «Ulashish/Поделиться».
3. (Необязательно) `/setuserpic` — аватар; `/setname` — отображаемое имя.
4. (Необязательно) `/newapp` — прямая ссылка `t.me/Bkrsuzbot/app` на Mini App; URL тот же,
   что `WEBAPP_URL`.

Команды, описание, короткое описание и кнопку меню **бот выставляет сам при запуске**
(`backend/app/bot/main.py`): кнопка меню открывает Mini App, если задан `WEBAPP_URL`,
иначе — обычное меню команд.

Свой Telegram ID для `ADMIN_IDS` можно узнать у [@userinfobot](https://t.me/userinfobot).

> ⚠️ Токен, который был отправлен в переписке, стоит перевыпустить: `/revoke` в BotFather,
> затем новый токен — только в `.env` на сервере.

---

## 4. API-ключи: какие нужны и где их взять

| Переменная | Обязательна | Для чего | Где взять |
|---|---|---|---|
| `BOT_TOKEN` | да | бот и проверка initData | @BotFather |
| `WEBAPP_URL` | для Mini App | HTTPS-адрес Mini App | ваш домен (см. §7) |
| `ADMIN_IDS` | для админки | Telegram ID админов | @userinfobot |
| `GOOGLE_API_KEY` | для перевода и озвучки | Cloud Translation + Text-to-Speech | Google Cloud Console |
| `ANTHROPIC_API_KEY` | нет | AI-пояснения и примеры | https://platform.claude.com |

**Google Cloud (перевод + озвучка):**

1. https://console.cloud.google.com → создать проект → привязать платёжный аккаунт
   (без него API не работают даже в рамках бесплатной квоты).
2. *APIs & Services → Library* → включить **Cloud Translation API** и **Cloud Text-to-Speech API**.
3. *APIs & Services → Credentials → Create credentials → API key*.
4. Ограничить ключ: *API restrictions* → только эти два API.
5. Вписать в `.env` как `GOOGLE_API_KEY` (или раздельно `GOOGLE_TRANSLATE_API_KEY` / `GOOGLE_TTS_API_KEY`).

Перевод использует REST v2 (`translation.googleapis.com/language/translate/v2`, языки
`uz`, `ru`, `zh-CN`, `en`), озвучка — `texttospeech.googleapis.com/v1/text:synthesize`
с голосами `cmn-CN-Wavenet-A…D` (список — `TTS_VOICES`, выбор голоса — в настройках Mini App).
Замедленная озвучка — `speakingRate=0.7` (`TTS_SLOW_RATE`).

**Claude (AI-пояснения, необязательно):** https://platform.claude.com → API Keys →
`ANTHROPIC_API_KEY`. Модель — `AI_MODEL` (по умолчанию `claude-opus-5-5`). Запрос использует
структурированный JSON-ответ и серверный резервный вариант при отказе модели
(`fallbacks: "default"`). AI вызывается **только по кнопке** «AI izoh», ответы кэшируются.

Без ключей проект работает в ограниченном режиме: словарь CC-CEDICT, редакционные карточки,
пиньинь, разбор фраз по словам, история, избранное. Функции без ключа не показываются как
рабочие: кнопки озвучки скрыты, а при поиске фразы выводится сообщение, что перевод не подключён.

---

## 5. Платные сервисы

Цены — ориентировочные на момент подготовки; проверьте актуальные на страницах сервисов.

| Сервис | Тариф | Бесплатно | Как экономим |
|---|---|---|---|
| Google Cloud Translation (Basic v2) | ≈ $20 за 1 млн символов | 500 тыс. символов/мес | кэш каждого перевода в БД |
| Google Cloud Text-to-Speech (WaveNet) | ≈ $16 за 1 млн символов | ≈ 1 млн символов/мес для WaveNet | кэш аудиофайлов на диске, лимит 300 символов |
| Claude API (Opus 5.5) | $4 / $20 за 1 млн входных/выходных токенов | — | только по кнопке, кэш, лимит 20 запросов/час на пользователя |
| VPS для сервера | от ~$5/мес | — | 1 vCPU / 1–2 ГБ RAM достаточно |
| Telegram Bot API, CC-CEDICT, jieba, pypinyin | бесплатно | — | — |

Админ может выключить любую платную функцию в админ-панели без перезапуска.

---

## 6. Локальный запуск

Требуется: Python 3.12+, Node 20+, PostgreSQL 16.

```bash
# 1. База
createuser -P bkrsuz            # пароль, например bkrsuz
createdb -O bkrsuz bkrsuz

# 2. Backend
cd bkrsuzbot/backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp ../.env.example .env         # вписать BOT_TOKEN и DATABASE_URL=postgresql+asyncpg://bkrsuz:bkrsuz@localhost:5432/bkrsuz
alembic upgrade head

# 3. Данные словаря (один раз; повторный запуск обновляет CC-CEDICT, правки редакции не трогает)
python -m app.scripts.import_cedict --url https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.txt.gz
python -m app.scripts.seed
python -m app.scripts.import_wikt --file ../webapp/data/wikt.json   # переводы ru/uz из Wiktionary

# 4. Mini App
cd ../miniapp && npm ci && npm run build && cd ../backend

# 5. Запуск (два процесса)
uvicorn app.api.main:app --port 8000      # API + Mini App на http://localhost:8000
python -m app.bot.main                     # бот
```

Открыть Mini App в обычном браузере для разработки можно только в режиме
`APP_ENV=dev DEV_AUTH_USER_ID=<ваш id>`: тогда сервер принимает заголовок `X-Dev-User`
вместо initData. **На сервере всегда `APP_ENV=prod`.** Горячая перезагрузка фронтенда:
`cd miniapp && npm run dev` (проксирует `/api` на :8000).

---

## 7. Размещение на сервере (Docker Compose)

Telegram открывает Mini App только по **HTTPS**. Нужны VPS и домен (A-запись на IP сервера).

```bash
git clone <репозиторий> && cd <репозиторий>/bkrsuzbot
cp .env.example .env
#   BOT_TOKEN=…   ADMIN_IDS=…   POSTGRES_PASSWORD=<сложный пароль>
#   DOMAIN=bkrsuz.example.uz   WEBAPP_URL=https://bkrsuz.example.uz/
#   GOOGLE_API_KEY=…   (ANTHROPIC_API_KEY=… по желанию)
docker compose --profile https up -d --build      # db, migrate, api, bot, caddy

# Данные словаря — один раз:
docker compose run --rm api python -m app.scripts.import_cedict \
  --url https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.txt.gz
docker compose run --rm api python -m app.scripts.seed
docker compose run --rm api python -m app.scripts.import_wikt --file data/wikt.json
docker compose restart bot
```

- `migrate` применяет миграции Alembic перед стартом `api` и `bot`.
- `caddy` автоматически получает сертификат Let’s Encrypt для `DOMAIN` и проксирует на `api`.
  Если HTTPS уже настроен (nginx и т.п.), запускайте без `--profile https` и проксируйте на `127.0.0.1:8000`.
- Аудио-кэш — том `audio`, БД — том `pgdata`. Резервная копия:
  `docker compose exec db pg_dump -U bkrsuz bkrsuz > backup.sql`.
- Обновление: `git pull && docker compose --profile https up -d --build`.
- Логи: `docker compose logs -f bot api`.
- Если хостинг не пускает к `api.telegram.org`, задайте `PROXY_URL`.

### Mini App без сервера (GitHub Pages)

Пока сервера нет, Mini App работает в **автономном режиме** — папка `webapp/` в репозитории,
публикуется через GitHub Pages:
`https://mukhammadalimir.github.io/NEWPROVIDENCE/bkrsuzbot/webapp/` → это значение `WEBAPP_URL` для бота.

- Словарь (CC-CEDICT + редакционные карточки) загружается в телефон один раз (~4 МБ сжато)
  и ищется прямо в браузере: иероглифы, пиньинь, узбекский/русский по словарю редакции
  и Wiktionary,
  разные чтения, словосочетания, примеры, разбор фраз по словам.
- Избранное, история, повторение и настройки хранятся в **Telegram CloudStorage**
  (отдельно для каждого пользователя, синхронизируются между устройствами).
- Озвучка — китайский голос телефона (Web Speech API); если его нет, кнопки скрыты.
- Нет: машинного перевода фраз, AI, админки и «Сообщить об ошибке» (эти функции — в боте
  и в серверной версии). Интерфейс прямо пишет об этом.

Обновление после правок словаря или кода:

```bash
cd bkrsuzbot/miniapp && npm run build:offline
cd ../backend && python -m app.scripts.export_offline --out ../webapp/data
git add ../webapp && git commit -m "Update offline Mini App" && git push
```

Проверка: `python3 -m http.server 8090` из корня репозитория, затем
`node bkrsuzbot/e2e/offline-smoke.cjs` (31 проверка на экране iPhone/Android).

### Переводы ru/uz ↔ китайский из Wiktionary

CC-CEDICT — китайско-английский словарь, поэтому русские и узбекские слова без карточки
редакции раньше не находились. Файл `webapp/data/wikt.json` (~7 000 русских и ~4 400
узбекских слов) собран из открытых данных Wiktionary (CC BY-SA 4.0, выгрузки
wiktextract с kaikki.org): берутся переводы одного и того же значения слова на
русский/узбекский и на путунхуа, остаются только слова, которые есть в CC-CEDICT.
В выдаче такие значения помечены «Wiktionary · не проверено» (в боте — 🌐).
Данные БКРС не используются.

Пересборка (нужен доступ к kaikki.org, английский файл — 3,4 ГБ, читается потоком):

```bash
cd bkrsuzbot/backend
curl -s https://kaikki.org/dictionary/English/kaikki.org-dictionary-English.jsonl \
  | python -m app.scripts.extract_wiktionary --kind en > /tmp/wikt_en.tsv
curl -s https://kaikki.org/dictionary/downloads/ru/ru-extract.jsonl.gz | gunzip \
  | python -m app.scripts.extract_wiktionary --kind ru > /tmp/wikt_ru.tsv
python -m app.scripts.build_wikt --cedict ../webapp/data/cedict.json \
  --out ../webapp/data/wikt.json /tmp/wikt_en.tsv /tmp/wikt_ru.tsv
python -m app.scripts.import_wikt --file ../webapp/data/wikt.json   # для бота/сервера
```

---

## 8. Проверки и как их повторить

### Автотесты (40 шт.)

```bash
createdb -O bkrsuz bkrsuz_test
cd bkrsuzbot/backend
TEST_DATABASE_URL=postgresql+asyncpg://bkrsuz:bkrsuz@localhost:5432/bkrsuz_test python -m pytest -q
```

Тесты используют настоящую PostgreSQL, миграции Alembic и фрагмент CC-CEDICT
(`tests/data/cedict_sample.u8`). Ответы Google в тестах подменяются через
`httpx.MockTransport` (формат запросов и ответов как у настоящего API) — это тестовые
двойники, а не проверка работы с настоящим Google. Те же тесты запускает GitHub Actions
(`.github/workflows/bkrsuzbot.yml`).

| Сценарий из ТЗ | Тест |
|---|---|
| поиск `baliq` → 鱼 / 魚, yú, 条, 海鱼, пример | `test_search.py::test_uzbek_word_baliq`, `test_bot_flow.py::test_word_card_audio_and_favorite` |
| варианты `o‘qimoq` / `o'qimoq` / `ўқимоқ` | `test_search.py::test_uzbek_apostrophe_variants` |
| поиск `鱼` | `test_search.py::test_chinese_word` |
| пиньинь `yu` (с выбором), `yu2`, `yú` | `test_search.py::test_pinyin_search`, `test_bot_flow.py::test_ambiguous_then_pinyin` |
| предложение zh→uz, zh→ru, uz→zh | `test_search.py::test_sentence_*` |
| разные чтения `行` без смешивания | `test_search.py::test_multiple_readings_not_mixed` |
| озвучка слова и предложения, медленная, кэш | `test_api.py::test_tts`, `test_bot_flow.py::test_word_card_audio_and_favorite` |
| избранное: добавление и удаление, изоляция пользователей | `test_api.py::test_favorites_add_remove_isolated` |
| понятная ошибка без сервиса / при сбое сервиса | `test_search.py::test_service_unavailable_messages`, `test_api.py::test_tts_not_configured`, `test_tts_service_down`, `test_bot_flow.py::test_tts_not_configured_alert` |
| проверка initData (подпись, подмена, срок) | `test_api.py::test_init_data_signature`, `test_requires_auth` |
| доступ администратора | `test_api.py::test_admin_access`, `test_bot_flow.py::test_admin_commands_protected` |
| сообщение об ошибке доходит только до админов | `test_bot_flow.py::test_report_reaches_admin_only` |
| удаление всех данных | `test_api.py::test_delete_all_data`, `test_bot_flow.py::test_delete_data` |

### Mini App на экране телефона (Playwright, iPhone 13)

```bash
cd bkrsuzbot/backend
APP_ENV=dev DEV_AUTH_USER_ID=1000 ADMIN_IDS=1000 uvicorn app.api.main:app --port 8000 &
cd .. && node e2e/mobile-smoke.cjs        # 23 проверки + скриншоты в e2e/shots/
```

Проверяются: главная, `baliq`, `行`, `yu` → выбор → список → карточка, фраза без ключа перевода,
избранное и повторение, ошибка сети, админка, настройки, тёмная тема, кнопки озвучки,
ссылка `?q=`, экран «откройте в Telegram» при отказе авторизации. В блоке озвучки ответ
`/api/tts` подменяется в браузере (проверяются кнопки и запросы, а не синтез Google).

### Ручная проверка в Telegram

1. `/start` → выбор языка → приветствие.
2. `baliq`, `鱼`, `yu`, `yu2`, `yú`, `行`, `我喜欢吃鱼。`, `Men baliq yeyishni yaxshi ko‘raman`.
3. На карточке: 🔊 и 🐢 (голосовое сообщение), ⭐, «Xato haqida xabar», «Ulashish».
4. `/favorites`, `/review`, `/history`, `/settings`, `/deletedata`; админу — `/admin`, `/reports`.
5. Кнопка меню «Lug‘at» → Mini App (после настройки HTTPS и `WEBAPP_URL`).

---

## 9. Безопасность

- **initData Mini App проверяется на сервере** по официальному алгоритму Telegram
  (HMAC-SHA256 с ключом `WebAppData` + токен бота, проверка `auth_date` — не старше 24 ч).
  ID пользователя берётся только из проверенных данных; фронтенд передаёт initData в
  заголовке `Authorization: tma …`.
- Все операции с историей/избранным/повторением фильтруются по проверенному ID — чужие данные
  недоступны (есть тест).
- **Админ-функции** доступны только ID из `ADMIN_IDS` — и в API (403), и в боте (для остальных
  команды не отвечают). Рассылок пользователям нет: уведомления об ошибках получают только админы.
- **Ограничения частоты** на пользователя: поиск 30/мин, озвучка 30/мин, AI 20/час
  (в памяти процесса; для нескольких экземпляров — заменить на Redis).
- Секреты только в `.env` (в `.gitignore`); в коде и репозитории токенов и ключей нет.
- Режим `APP_ENV=dev` (вход без Telegram) в prod отключён — есть тест.

---

## 10. Администрирование

Mini App → вкладка **Admin** (видна только админам) или команды бота:

| Что | Mini App | Бот |
|---|---|---|
| Статистика пользователей, запросов, ошибок сервисов | Statistika | `/admin` |
| Включить/выключить перевод, озвучку, AI, словосочетания | Statistika → Funksiyalar | `/admin` → кнопки |
| Сообщения об ошибках, отметка «решено» | Xabarlar | `/reports` |
| Исправить/добавить карточку (uz/ru значения, примеры, словосочетания, «проверено») | Lug‘at | — |

Чтобы добавить узбекское значение к слову из CC-CEDICT: Lug‘at → найти иероглифы →
«Tahririyat kartasini yaratish» → заполнить → «Tekshirilgan» → Saqlash.

---

## 11. Решения, принятые без отдельных указаний

- **Стек:** Python + aiogram + FastAPI + PostgreSQL + React/Vite, один Docker-образ для API и бота.
- **Перевод и озвучка — Google Cloud** (одна учётная запись на оба API, поддерживает узбекский).
- **AI — Claude**, только по запросу пользователя, с отдельной меткой.
- **Неоднозначный ввод** (латиница, которая является корректным пиньинем: `yu`, `ni hao`;
  кириллица без узбекских букв: `салом`) — всегда вопрос пользователю.
- **Озвучка в чате** — голосовым сообщением (OGG/Opus), в Mini App — MP3 по кнопке.
- **Приблизительное звучание** узбекскими буквами строится по правилам из пиньиня и всегда
  подписано «taxminiy talaffuz».
- **Повторение** — простая система Лейтнера (интервалы 0/1/3/7/14/30 дней).
- **История** — последние 50 запросов; удаление данных — полностью (история, избранное, настройки).
- **Фото (OCR) и голосовые** — бот вежливо сообщает, что функция пока не подключена.

---

## 12. Следующий этап

| Функция | Как подключить | Сервис |
|---|---|---|
| Перевод текста с фото | распознавание иероглифов → обычный поиск/перевод | Google Cloud Vision (платно) |
| Голосовое сообщение → текст → перевод | распознавание `cmn-CN`/`uz-UZ`/`ru-RU` | Google Cloud Speech-to-Text (платно) |
| Больше примеров предложений | импорт пар предложений Tatoeba (CC BY 2.0 FR) | бесплатно |
| Синонимы и связанные слова | при наличии лицензируемого источника | — |
| Масштабирование | Redis для лимитов, webhook вместо polling | — |
