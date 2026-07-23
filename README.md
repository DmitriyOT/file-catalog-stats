# Сервис скачивания и анализа файлов

Сервис скачивает каталог текстовых файлов через внешнее API
(с учётом rate limit) и считает статистику по цифрам в их содержимом.

## Стек

- **Backend:** Python 3.12, FastAPI, SQLAlchemy (async), PostgreSQL, httpx
- **Frontend:** React 18, TypeScript, Vite
- **Запуск:** Docker + docker-compose
- **Тесты:** pytest (unit + integration)

## Быстрый старт

```bash
docker compose up --build
```

- UI: http://localhost:8085
- API (Swagger): http://localhost:8000/docs

### Локальная разработка

Backend:

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # Windows; на *nix: .venv/bin/pip
uvicorn app.main:app --reload                   # нужен PostgreSQL, см. DATABASE_URL
```

Frontend (dev-сервер с прокси `/api` на localhost:8000):

```bash
cd frontend
npm install
npm run dev
```

Тесты:

```bash
cd backend
.venv/Scripts/python -m pytest                  # БД — SQLite in-memory
```

## Переменные окружения (backend)

| Переменная | По умолчанию | Описание |
|---|---|---|
| `API_BASE_URL` | `http://91.199.149.128:18001` | URL внешнего API выдачи файлов |
| `CANDIDATE_ID` | `installbiz-candidate` | Значение заголовка `X-Candidate-Id`; прогресс скачивания привязан к нему |
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/filestats` | DSN базы |
| `REQUEST_MIN_INTERVAL` | `1.5` | Минимальная пауза между запросами к внешнему API, сек |
| `REQUEST_TIMEOUT` | `30.0` | Таймаут запроса к внешнему API, сек |
| `MAX_RETRIES` | `10` | Максимум повторов запроса при 429/403/5xx |

## Как это работает

1. **Скачивание.** Кнопка «Скачать данные» запускает фоновую задачу:
   цикл `GET /api/files/names` → скачивание по 3 файла (ZIP) →
   `POST /api/files/downloaded`, пока ручка имён не вернёт пустой список.
   Клиент учитывает rate limit: паузы по `Retry-After` при 429/403,
   backoff при сетевых ошибках и 5xx. Прогресс (старт по НСК,
   «получено N названий, скачано M из N») обновляется раз в 1,5 с.
2. **Файлы и расчёты.** Список скачанных файлов с сортировкой по времени
   скачивания и пагинацией. Файлы можно выбрать точечно, все на странице
   или вообще все. Кнопка «Произвести расчёты» показывает общую статистику
   цифр 0–9 и статистику по каждому файлу.

## Структура

```
backend/
  app/
    api_client.py   # клиент внешнего API (rate limit, retry, ZIP)
    downloader.py   # фоновая задача скачивания каталога
    stats.py        # расчёт частот цифр
    routes/         # download (старт/статус), files (список), stats (расчёты)
  tests/
frontend/
  src/pages/        # DownloadPage, FilesPage
  src/components/   # Header, StatsPanel
docker-compose.yml  # db, backend, frontend (nginx)
```
