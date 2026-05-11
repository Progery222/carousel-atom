# Carousel Studio — обзор сервиса и предложения по улучшениям

Документ описывает что делает приложение, как оно устроено внутри, и содержит структурированный список идей по доработке.

---

## 1. Что это и зачем

Carousel Studio — локальное Mac/Linux-приложение, которое превращает поток RSS / HTML / NewsAPI новостей в готовые к публикации карусели для TikTok и Instagram. Пользователь выбирает топик (F1, NBA, Tech, Crypto и т.д.) и дизайн, нажимает Generate — бэкенд собирает свежие новости, фильтрует, скорит, рендерит PNG-слайды и подпись, фронтенд показывает превью, позволяет редактировать слайды / переписывать заголовки через LLM, и экспортировать всё в ZIP или отправить в Telegram-канал.

Запуск — двойной клик по `Start Carousel Studio.command` (или `dev.sh`). Поднимаются два сервера: FastAPI на :8000 и Vite-dev на :5173, в браузере открывается студия.

Ключевые проектные решения:
- **Локальный, без подписок.** Все ключи (LLM, NewsAPI, Pexels, Unsplash, Telegram) опциональны — на чистой машине работают только RSS + HTML-парсеры.
- **Plug-in архитектура для топиков и дизайнов.** Топик — это директория с `topic.yaml`. Дизайн — функция с фиксированной сигнатурой, зарегистрированная в `designs/__init__.py`. Ни то, ни другое не требует трогать пайплайн.
- **Идемпотентность через SQLite seen-store.** Та же история не попадает в карусель дважды.

---

## 2. Высокоуровневая архитектура

```
┌──────────── frontend (Vite + React 19 + Tailwind, :5173) ─────────────┐
│  TopicPicker · DesignPicker · HistoryPanel  │  CarouselPreview        │
│                                              │  SlideEditor / QuickEdit│
│                                              │  ExportPanel (ZIP/TG)   │
└──────────────────────────────────────────────┴─────────────────────────┘
                                 │   REST (fetch, no auth)
┌──────────── backend (FastAPI + Pillow, :8000) ────────────────────────┐
│  /topics  /designs  /render  /render/edit  /render/partial            │
│  /preview/articles  /runs  /dedup/{reset,prune}  /schedule/*          │
│  /deliver/{run_id}  /llm/rewrite-headline  /upload-image  /health     │
│                                                                        │
│  pipeline:  RSS|HTML|NewsAPI → enrich (og:*) → quality + severity     │
│             → score → cross-topic dedup → balance sources             │
│             → image-search fallback (Wikimedia/Pexels/Unsplash)       │
│             → verify download → optional LLM rewrite → render PNGs    │
│             → caption → optional Telegram delivery → log_post         │
│                                                                        │
│  storage:   SQLite (WAL) — seen-store, posts log, auto-prune on boot  │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Backend в деталях

### 3.1 Пайплайн (`backend/core/pipeline.py`)

Единственная точка входа — `run_once(topic, design, mark_seen, cross_topic_dedup, deliver, override_articles)`. Этапы:

1. **Collect** — параллельно тянем все включённые источники (`ThreadPoolExecutor`, до 8 потоков). Источник может быть `rss` (feedparser), `html` (BS4 + regex по `article_pattern`), или `newsapi` (https://newsapi.org/v2/everything).
2. **Freshness gate** — `dedup.is_seen(topic, url, title)` по url-hash и normalized-title-hash. При `cross_topic_dedup=True` дополнительно проверяется через все топики (одна и та же история Bleacher Report не уйдёт и в NBA, и в Lifestyle).
3. **In-batch dedup** — выкидываются почти-одинаковые заголовки внутри одного батча.
4. **Cheap pre-rank** — `score_article` без HTTP, чтобы взять `top 5×N` для дорогих стадий.
5. **Enrich** — три последовательных параллельных прохода: `enrich_article` (og:image / og:description / publish-time) → `find_replacement_image` (Wikimedia → Pexels → Unsplash) → `_verify_image_downloadable` (фактический HTTP-загрузка с верификацией размера и опционально heuristic photo-vs-graphic фильтром).
6. **Image-URL dedup** — `_dedupe_images` дропает статьи с одинаковыми hero-фотками (на F1.com одна и та же студийная фотка используется во всей серии "Cooldown Room").
7. **Re-score + balance** — добавляются trending-бонусы (entity overlap между статьями) и round-robin по источникам, чтобы один паблишер не занял всю карусель.
8. **LLM title rewrite (опционально)** — если в `topic.yaml` стоит `caption.llm_rewrite_titles: true` и есть `LLM_API_KEY`.
9. **Render** — `design.render(topic, articles, output_dir)` → PNG-файлы в `backend/data/output/<run_id>/`.
10. **Caption** — `render_caption()` по template + опциональный LLM-rewrite.
11. **Delivery (опционально)** — `core.delivery.telegram_adapter.send()`.
12. **Log** — `dedup.log_post()` пишет run в `posts` для истории.

### 3.2 Качество и дедупликация

- **`quality.passes_filters`** — длина заголовка, наличие изображения, фрешнесс (≤72ч), `min_image_width` (400px), blocklist, news-content gate (отсекает quiz/poll/opinion/guide/commerce).
- **`quality.score_article`** — комбинация: +2.0 за картинку, +1.5 за описание, +1.0 за нормальную длину тайтла, +0.5 за цифры, +1.0 за свежесть <24h, –1.5 за severity=severe (трагедии вниз), +1.5 за keyword из `boost` в topic.yaml.
- **`quality.severity_of` / `news_icon` / `news_emoji`** — regex-классификация по словам (death, crash, hospital, win, return, denial, rumour) → ASCII-глиф и colour-emoji, которые подмешиваются в дизайны.
- **`quality.balance_sources`** — round-robin с `max_per_source` (≈ N/2 + 1).
- **`dedup`** — SQLite в WAL-режиме, таблицы `seen(topic, url_hash, title_hash, ...)` и `posts(topic, run_id, posted_at, platform, slide_count, caption)`. `normalize_title` агрессивно режет всё кроме alphanumeric.

### 3.3 Парсеры (`core/parsers/`)

- **`rss.fetch_rss`** — feedparser + извлечение картинки по приоритету `media:content` → `media:thumbnail` → `enclosure` → `<img>` в summary. Limit 25 статей.
- **`html_scraper.fetch_html`** — `requests` + BS4, регулярка по `article_pattern` на href, чистка тайтлов от суффиксов сайта. Limit 20.
- **`html_scraper.enrich_article`** — догружает страницу, ищет og:image/twitter:image/srcset, og:description/первый абзац, парсит publish-time. Все исключения молча проглатываются.
- **`html_scraper.upgrade_image_url` / `looks_low_res` / `url_width_hint`** — heuristics, чтобы превратить thumbnail из RSS в большой press shot без HTTP-запроса.
- **`newsapi.fetch_newsapi`** — стандартный NewsAPI everything endpoint, фильтрует `[Removed]` и хардкодит `from=last 7 days`.

### 3.4 Дизайны (`backend/designs/`)

Все семь дизайнов реализуют один протокол: `render(topic, articles, output_dir) -> list[str]`. По умолчанию 1080×1920 (TikTok 9:16), у legacy newsflash — 1080×1350 (Instagram 4:5).

| Дизайн | Стиль |
|---|---|
| `tiktok_news` | Hero-фото + градиент + эмблема + sentiment dot + ALL-CAPS + accent на последних словах (≈@f1newsflash) |
| `newsflash` | Full-bleed photo + жирный bottom-headline + красный accent |
| `viral_roundup` | Hook + ranked countdown + CTA |
| `quote_card` | Editorial pull-quote |
| `premium_light` | Magazine cream layout |
| `story_mode` | Chapterised narrative + 2×3 collage cover |
| `blueprint` | Edge-detected hero на cobalt-blue canvas с grid + лейблами |

Регистрация — `designs/__init__.py`, порядок = порядок в UI. `_newsflash_legacy.py` и `_viral_roundup_legacy.py` остались как референс, не зарегистрированы.

### 3.5 Image-стек

- **`core/http.py`** — общий `requests.Session` с `HTTPAdapter`, retry total=3, backoff=0.7, retry на 429/500/502/503/504. `_download_one` кэширует по MD5(url) в `_verify_cache/`.
- **`core/image.py`** — `smart_cover` (saliency-aware cover-fit через gradient variance), `is_press_photograph` (heuristic по unique_color_count + edge_mean), `punch` (контраст/насыщенность/sharpness), `darken_band_under_text` (мягкий градиент под текстом для читаемости).
- **`core/image_search.py`** — Wikimedia (бесплатно) → Pexels (ключ) → Unsplash (ключ), first non-empty URL wins.

### 3.6 LLM (`core/llm.py`)

- OpenAI-compatible (gpt-4o-mini по умолчанию, можно Groq / Ollama / Anthropic-via-proxy через base_url).
- Две функции: `caption_rewriter` (целая caption, max_tokens=700) и `headline_rewriter` (один заголовок, max_tokens=80, temperature=0.55, санити-чек на длину).
- Один `requests.post` с timeout=30, без retry, без rate-limit-handling, без prompt-caching.

### 3.7 Доставка и расписание

- **`core/delivery/telegram.py`** — `sendMediaGroup` (≤10 фото) + опциональная отдельная caption-сообщение. `is_configured(topic)` проверяет `TELEGRAM_BOT_TOKEN` + `topic.telegram_chat` (с поддержкой `env:CHAT_X` indirection).
- **`core/scheduler.py`** — `due_topics(now, window_min)` проверяет, попадает ли `now` в ±window от любого `send_hours` в локальной TZ топика. `run_due_topics` крутит `run_once` для каждого due. Зовётся по cron через `POST /schedule/trigger`.

### 3.8 Тесты

Покрыто: quality (filters, scoring, severity), image (saliency, photo detection), text (entities, typography), LLM rewriter, scheduler logic, news icon mapping. Не покрыто: e2e pipeline, http retry, SQLite dedup, парсеры (RSS/HTML/NewsAPI), Telegram delivery.

---

## 4. Frontend в деталях

### 4.1 Структура `App.tsx`

Линейный workflow на чистом `useState`: pick topic → pick design → Generate → Edit → Export. Состояние держит ~20 переменных (topics, designs, topic, design, result, caption, editing, layout, loading, batchProgress, error, history, theme, lockedUrls, busySlot, pickerOpen, cmdkOpen, quickEditIndex, llmEnabled, ...). Персистентность — `localStorage` (история ран, layout, тема). Глобального state-менеджера нет.

### 4.2 Компоненты (`frontend/src/components/`)

| Компонент | Назначение |
|---|---|
| `TopicPicker` / `DesignPicker` | Sidebar-списки с emoji/icon-мапами (захардкоженными для 20+ топиков и 7 дизайнов) |
| `CarouselPreview` | Главное окно превью, режимы strip ↔ grid, hover-меню на слайде (lock / re-roll / edit) |
| `SlideEditor` | Нижняя панель с редактированием статей (drag, remove, image upload через `/upload-image`) |
| `SlideQuickEdit` | Модалка для одного слайда + 4 кнопки LLM-rewrite (punchier / factual / hook / RU translate) |
| `ExportPanel` | Caption-editor + chars-limits на платформы + ZIP-экспорт (jszip+file-saver) + Send to Telegram |
| `HistoryPanel` | localStorage-история ран с fuzzy-поиском |
| `CandidatePanel` | Модалка превью кандидатов (`/preview/articles`) с ручным выбором |
| `CmdK` | Command palette (⌘K) с собственной fuzzy-функцией |
| `StatusPill` | Polling `/health` каждые 30с, показывает live/offline, seen count, last post, LLM-флаг |
| `Toast` | Простые уведомления, auto-dismiss |
| `ThemeToggle` | Two-button light/dark, persist в `localStorage` |

### 4.3 API-клиент (`src/api.ts`)

Чистый `fetch` + generic `jsonOrThrow`. Все ответы типизированы. Без retry, без interceptors, без auth. `API_BASE` через `VITE_CAROUSEL_API`, дефолт `http://localhost:8000`.

### 4.4 Hotkeys и UX

| Клавиша | Действие |
|---|---|
| ⌘/Ctrl+K | Command palette |
| G | Generate / re-roll |
| B | Batch × 3 |
| A | All topics |
| E | Toggle slide editor |
| V | Toggle strip ↔ grid |
| P | Open candidate picker |
| Esc | Закрыть открытую модаль |

История ран в `localStorage` (до 24 записей), без undo/redo на уровне отдельных слайдов.

### 4.5 Стили

`Tailwind` + CSS-переменные в `index.css` (`--ink-900..100`, `--accent`, `--severe` и т.д.). `data-theme="dark"|"light"` на `<html>`. Цвета определяются один раз и читаются через `rgb(var(--color) / <alpha>)` — поддерживает альфу из коробки.

---

## 5. Конфигурация и env

Все опциональные интеграции (`.env.example`):

| Переменная | Что включает |
|---|---|
| `LLM_API_KEY` + `LLM_BASE_URL` + `LLM_MODEL` | Caption rewriter и кнопки в slide-editor |
| `TELEGRAM_BOT_TOKEN` + `CHAT_<TOPIC>` | Доставка в Telegram |
| `NEWSAPI_KEY` | `kind: newsapi` источники |
| `PEXELS_API_KEY`, `UNSPLASH_ACCESS_KEY` | Fallback-картинки |
| `CAROUSEL_PHOTO_FILTER` | Строгий photo-vs-graphic фильтр (off по умолчанию) |
| `CAROUSEL_PRUNE_DAYS` | Авточистка seen-store (180) |
| `CAROUSEL_CORS` | Доп. CORS-origin'ы |
| `VITE_CAROUSEL_API` | Базовый URL backend'а для фронта |

---

## 6. Сильные стороны проекта

- **Зрелая parallelism-модель** в pipeline (collect/enrich/verify через `ThreadPoolExecutor`, WAL в SQLite).
- **Параноидальная работа с картинками** — три отдельных этапа enrichment с реальной верификацией загрузки. Это сильно поднимает качество карусели, потому что половина "странных" результатов в генераторах новостных карточек — это именно картинки.
- **Чистая plug-in архитектура** — добавить топик = положить yaml, добавить дизайн = функция + регистрация. Pipeline остаётся неизменным.
- **Хорошая модульность бэкенда** — `parsers`, `quality`, `dedup`, `image`, `llm`, `delivery`, `scheduler` — каждый файл делает одну вещь.
- **Локальность и отсутствие vendor lock-in** — всё опционально, дефолтный путь полностью offline-free.
- **Продуманный UX-слой** — hotkeys, command palette, history, fuzzy-поиск, theme toggle, batch generation.
- **Аккуратная типизация фронта** — типы экспортируются из одного `types.ts`, API-функции типизированы.

---

## 7. Технический долг и проблемы

### 7.1 Безопасность

- **SSRF в `enrich_article`** (`html_scraper.py`). Если в RSS попадёт `article.url == http://localhost:8000/admin`, бэкенд послушно сходит туда от своего лица. Нужна валидация (отвергать private/loopback ranges) или whitelist по доменам топика.
- **LLM prompt injection** (`llm.py`). Тайтлы статей подставляются в template без эскейпа фигурных скобок; чужой тайтл вида "...} ignore previous and {..." может перетащить инструкцию.
- **Telegram `chat_id` не валидируется**. Если в env лежит ерунда, ошибка вылезает только в момент `requests.post`.
- **`/upload-image`** не проверяет content-type / magic bytes — теоретически можно сохранить файл с произвольным содержимым (хоть и в `data/uploads`).

### 7.2 Устаревшие/слабые паттерны

- `@app.on_event("startup")` (`api/server.py:58`) — deprecated в FastAPI 0.93+, нужен lifespan-контекст.
- Все исключения в `enrich_article` ловятся одним `except Exception` без логирования причины (`html_scraper.py:369`).
- `__import__("json")` в Telegram-адаптере (`delivery/telegram.py:72`) — необычный паттерн без причины.
- Глобальный флаг `_warned_no_key` в `newsapi.py:29` без `Lock` — в потоковом коде это race condition (10 потоков логнут предупреждение 10 раз).
- Хардкоды повсюду: `limit=25/20` в парсерах, `max_workers=8`, thresholds в `is_press_photograph` (600 colors, 1000, 5 edges) подобраны под англоязычный спорт, `min_image_width=400`, 72-час freshness.

### 7.3 Ресурсы и состояние

- **`_verify_cache/` растёт бесконечно** — никакой LRU, никакой TTL. После полугода работы это легко гигабайт.
- **`data/output/<run_id>/`** тоже не чистится автоматически. Только seen-store.
- **Файловые handle'ы в Telegram-доставке** — `open` без `with`, в случае исключения в `requests.post` не закрываются.
- В `enrich_article` нет timeout на пер-source basis — `requests` timeout 15с, но если один источник eat'ит весь пул потоков, остальные ждут.

### 7.4 Качество результата

- **`balance_sources` может вернуть меньше слайдов, чем нужно**, и caller (pipeline) об этом не узнаёт явно — fallback на safety break без warning.
- **`_dedupe_images` с min_keep**-хак — pragmatic, но может привести к карусели с двумя одинаковыми фотами.
- **`is_press_photograph`** fail-open: на ошибке возвращает True, т.е. странный файл всё равно пройдёт.
- **NewsAPI хардкод `from=last 7 days`** — два запуска в день частично перетянут одни и те же статьи (отфильтруются seen-store'ом, но это лишний трафик).
- **Никакого кэша на enriched articles** — повторный `/preview/articles` каждый раз проходит весь pipeline заново.

### 7.5 Frontend

- **Prop drilling** в `CarouselPreview` (9+ пропсов) — кандидат на Context.
- **Magic strings**: EMOJI/ICON-мапы в Topic/Design pickers, STYLES в QuickEdit, лимиты соцсетей в ExportPanel, ключи localStorage — всё это разбросано.
- **Inconsistent error handling** — местами `.catch`, местами `try/finally` без `catch`. В `downloadZip` нет обработки ошибок вообще: если один из fetch'ей слайдов упадёт, ZIP уедет неполным без warning.
- **Cmd+K срабатывает даже в текстовых полях** — нельзя ввести букву K с модификатором в caption-textarea.
- **Нет loading-skeleton'ов** (только generic "Generating…").
- **Нет тестов вообще** — ни unit, ни e2e.
- **Не используются React 19-фичи** (`useActionState`, `use()`) — на качество не влияет, но компоненты с async-сабмитом могли бы быть проще.
- **`SlideCard` не мемоизирован**, при переключении layout перерендериваются все слайды.

### 7.6 Документация и DX

- `dev.sh` есть только для bash, для Windows нет аналога (хотя приложение крутится на Windows-машинах: `OS Version: Windows 11`).
- Нет CI — все проверки руками. Нет precommit-хуков, ruff/black/eslint не запускаются автоматически.
- В `pyproject.toml` нет dev-deps (pytest вообще не указан как зависимость).

---

## 8. Предложения по доработке

Разбито по приоритету. ROI = "польза × частота × низкая стоимость внедрения".

### 8.1 High-priority — стабильность и безопасность

1. **Перевести startup-хук на lifespan-контекст FastAPI.** Тривиально, убирает DeprecationWarning, готовит к будущим версиям.
2. **SSRF-защита в `enrich_article`.** Перед `requests.get(article.url)` проверить, что hostname резолвится в публичный IP, и (опционально) что домен входит в список из `topic.yaml.sources`. Это закрывает класс уязвимостей.
3. **Лимит/чистка `_verify_cache` и `data/output/`.** Запустить prune при старте: дропать файлы старше N дней (новая env `CAROUSEL_CACHE_DAYS`, дефолт 30). По аналогии с уже существующим `dedup.prune_seen`.
4. **`with open` в Telegram-адаптере**, чтобы не течь файловыми хэндлами.
5. **Retry + rate-limit handling в `llm.py`.** Сейчас один `requests.post` без обработки 429/503 — на нагрузке LLM-кнопки в UI просто молча возвращают оригинал. Использовать тот же `core.http` session с retry policy.
6. **Эскейп curly braces в LLM-templates** (или переход на f-string-free template вроде `string.Template`). Закрывает простейший prompt-injection.
7. **Валидация `/upload-image`**: проверить magic bytes (PNG/JPEG), ограничить размер, отказываться от SVG (XSS-вектор при показе).
8. **Логирование причин в `enrich_article`** — заменить blanket `except Exception` на конкретные классы (Timeout, ConnectionError, HTTPError) с `log.debug(reason, exc_info=False)`. Текущий молчаливый drop усложняет диагностику "почему карусель пустая".

### 8.2 Medium — качество и UX

9. **Кэш для enriched-пула** (in-memory + TTL ~10 минут на `(topic, set-of-source-urls)`). `/preview/articles` за тем же столом сейчас полностью перепарсивает RSS — в UI это заметная задержка.
10. **Прокинуть progress в фронт.** Сейчас Generate — это чёрный ящик на 5-30 секунд. Простое улучшение: `/render` возвращает `run_id` сразу + SSE/long-polling endpoint, на котором фронт получает этапы (collecting, enriching, rendering). Skeleton можно положить параллельно.
11. **React Context для CarouselPreview-стека** — убрать prop-drilling, заодно даст возможность мемоизировать `SlideCard` через `React.memo`.
12. **Loading skeleton'ы** для CarouselPreview / HistoryPanel / CandidatePanel вместо текста "Generating…".
13. **Обработка ошибок в `downloadZip`.** Сейчас один упавший слайд → silently broken ZIP. Минимум — попробовать retry на 1 сбойную картинку и показать toast.
14. **Cmd+K блокировать в `<input>/<textarea>`** — починить очевидный UX-bug.
15. **Undo/redo на уровне SlideEditor.** Стек последних 10 состояний `articles`, кнопка ⌘Z. Сейчас если случайно удалил слайд — re-roll и собирай заново.
16. **Прогресс-бар на batch (B×3, All topics)** — сейчас просто `batchProgress.done/total` в углу, без визуального индикатора.
17. **Централизовать magic strings** — вынести EMOJI / ICON / STYLES / `HISTORY_KEY` / лимиты в `src/constants.ts`. Заодно убрать дубликаты определений localStorage-логики (loadTheme/loadHistory/loadLayout → generic `loadFromStorage<T>`).

### 8.3 Medium — пайплайн и качество данных

18. **Слить три прохода enrichment в один.** Сейчас `_enrich_and_filter` создаёт три `ThreadPoolExecutor`'а подряд — enrich → image-search → verify. Объединение даст параллелизм через все стадии (статьи с готовой картинкой сразу идут на verify, остальные — на search) и сократит общее время.
19. **NewsAPI: использовать `from=last_run + 1m`** вместо хардкода 7 дней. Сэкономит платный API-квот и снизит риск повторов.
20. **Параметризовать пороги `is_press_photograph`** (текущие подобраны под англоспорт). Передавать их через `topic.yaml.image_filter` — для топиков типа Tech / Crypto / Movies нужны другие thresholds (там логотипы и постеры — норма).
21. **Schema-валидация `topic.yaml`** через pydantic при загрузке. Сейчас плохой kind или опечатка в hex-цвете крашит pipeline на середине. Лучше падать на старте с понятной ошибкой.
22. **Расширить `severity_of`** — сейчас это набор regex'ов на ~10 английских слов. Можно добавить локализованные списки и более тонкие классы (`legal`, `injury`, `transfer`). Будет влиять и на скоринг, и на иконки.
23. **Replace `normalize_title` с чем-то менее агрессивным.** Сейчас "C++ dies" и "C dies" нормализуются одинаково. Минимум — сохранять `+`, `#`, числа.
24. **Пер-topic min-image-width** в `topic.yaml.carousel.min_image_width`. Для Tech новостей 400px часто слишком жёстко, для F1 — наоборот мало.

### 8.4 Low — DX и тестирование

25. **Windows-launcher** (`Start Carousel Studio.cmd` или `.ps1`), параллельный `dev.sh`. По логам видно, что разработка идёт на Windows — bash-only launcher неудобен.
26. **Pytest, ruff, mypy как dev-deps** в `pyproject.toml` + GitHub Action / pre-commit hook. Сейчас линтеров вообще нет.
27. **e2e тесты pipeline** с замоканной сетью (responses / vcrpy). Самая болезненная зона — парсеры; RSS-фид меняется → молчаливо ломается источник.
28. **Тесты для `dedup`** (is_seen / mark_seen / prune / cross-topic). Сейчас не покрыты, а это сердце идемпотентности.
29. **Frontend unit-тесты** через vitest + testing-library. Минимум — для `api.ts` и для `CmdK` fuzzy-score (там есть нетривиальная логика).
30. **OpenAPI-клиент для фронта** — сгенерировать `api.ts` из FastAPI-схемы вместо ручного дублирования типов. Убирает рассинхрон между `RenderResult` на бэке и `RenderResult` в `types.ts`.

### 8.5 Архитектурные / большие идеи

31. **Расписание-как-данные.** Сейчас `/schedule/trigger` зовётся внешним cron'ом. Стоит встроить опциональный APScheduler в backend, чтобы при `CAROUSEL_AUTOPOST=1` сервис сам тикал по `send_hours` без зависимости от системного cron. Сильно упрощает первый запуск.
32. **WebSocket-канал для frontend live-updates.** Когда у нас будет автопостинг (см. п.31), студия должна узнавать о новом ране без F5 — websocket с broadcast'ом `run_created`.
33. **Pluggable delivery.** Сейчас в `core/delivery/` только Telegram. Архитектура уже под это заточена (ADAPTERS dict), не хватает X/Bluesky/Discord. Самый дешёвый — Discord webhook.
34. **Ходовой LLM-rewrite caption-а на отдельном endpoint'е** (есть `/llm/rewrite-headline`, нет `/llm/rewrite-caption`). Это уменьшит количество "сгенерил → не нравится подпись → re-roll всё ради подписи".
35. **Multi-source ranking weights в `topic.yaml`** — сейчас все источники в скоринге равны. У некоторых топиков один-два authoritative источника, остальные — шум; явный `source_weight` это разрулит.
36. **History на диске, не только в localStorage.** Когда HISTORY_LIMIT=24 переполнится, старые карусели исчезают из UI хотя файлы лежат в `data/output/`. Дёшево вытащить из `dedup.posts` и показать поверх localStorage.
37. **Анализ "почему пусто".** Когда `/render` возвращает 409 с `status != ok`, фронт показывает generic error. Лучше — детальный breakdown (`drop_reasons` уже логируется в pipeline, надо его прокинуть в ответ): "из 87 статей: 23 уже видели, 41 без картинки, 12 в blocklist, 7 quality-fail, 4 image-verify-fail". Это превращает 0-результат из загадки в actionable feedback.
38. **Дизайн-превью без полного рендера** — render миниатюры (300×400) первого слайда для DesignPicker, чтобы пользователь видел стиль до клика. Сейчас выбор дизайна — это блайнд-выбор.

### 8.6 Quick wins (1-2 часа каждый)

- `with open` в Telegram-адаптере.
- Lifespan вместо on_event.
- Cmd+K-блок в input/textarea.
- Try/catch в downloadZip.
- Лимиты для `data/output/` (drop folders older than N days).
- Lock на `_warned_no_key` в newsapi.py.
- Заменить `Array.isArray(parsed)` после `JSON.parse` на нормальный type-guard.
- Скрытое логирование причины exception в enrich_article (log.debug с reason).

---

## 9. Итог

Carousel Studio — крепкий single-user локальный инструмент с правильной декомпозицией и неплохой проработкой деталей (особенно работа с картинками и dedup). Основные точки давления — это безопасность входных URL (SSRF), управление кэшами (растут без чистки), пара устаревших паттернов в FastAPI и предсказуемые UX-вещи на фронте (skeleton'ы, progress, undo). Бóльшая часть высокоприоритетных доработок — это 1-2-часовые правки с прямым эффектом на стабильность; среднеприоритетные (Context + memo + единый enrich-проход) дадут заметный прирост в feel'е и времени отклика, а архитектурные идеи (auto-scheduler, websocket, OpenAPI-клиент, "почему пусто") стоит держать в виду на горизонте следующих недель.
