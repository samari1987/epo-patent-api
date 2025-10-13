# EPO Patent Search API

Этот проект разворачивает FastAPI-сервис, который подключается к European Patent Office (EPO) API.

## Эндпоинты:
- **GET /status** — проверка статуса сервиса
- **POST /search** — поиск патентов по названию

Пример тела запроса:
```json
{ "query": "CRISPR" }
```

## Запуск локально:
```bash
pip install -r requirements.txt
uvicorn main:app --reload
```
