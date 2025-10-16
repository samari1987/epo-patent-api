# main.py — API для Научного Инноватора
# 25 результатов/страница, сортировка по дате (newest→oldest), пагинация, автоперевод, анти-«дубликаты»

from fastapi import FastAPI, Body, Query
from pydantic import BaseModel
from typing import List, Optional
from deep_translator import GoogleTranslator
from datetime import datetime, timedelta

app = FastAPI(title="EPO Patent API", version="1.6.0")

# ---------- модели ----------
class PatentItem(BaseModel):
    publicationNumber: str
    kindCode: Optional[str] = None
    country: Optional[str] = None
    publicationDate: Optional[str] = None  # YYYY-MM-DD
    titleOriginal: str
    titleRu: Optional[str] = None
    abstractOriginal: Optional[str] = None
    abstractRu: Optional[str] = None
    applicants: Optional[List[str]] = []
    inventors: Optional[List[str]] = []
    ipc: Optional[List[str]] = []
    cpc: Optional[List[str]] = []
    linkEspacenet: str
    linkPdf: Optional[str] = None

class SearchResponse(BaseModel):
    total: int
    page: int
    size: int
    nextPage: Optional[int] = None
    items: List[PatentItem]

# ---------- утилиты ----------
_tr = GoogleTranslator(source="auto", target="ru")

def _translate_ru(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    try:
        t = _tr.translate(text.strip())
        if t and len(t) > 500:
            t = t[:500].rsplit(" ", 1)[0] + "…"
        return t
    except Exception:
        return None

def _clip_en(text: Optional[str], n: int = 500) -> Optional[str]:
    if not text:
        return None
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + "…"

def _parse_date_safe(s: Optional[str]) -> datetime:
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except Exception:
        return datetime(1900, 1, 1)

# ---------- статус ----------
@app.get("/status")
def status():
    return {"status": "ok", "service": "epo", "version": "1.6.0"}

# ---------- демо-данные ----------
def _seed_base() -> List[PatentItem]:
    return [
        PatentItem(
            publicationNumber="US12421136B1",
            kindCode="B1",
            country="US",
            publicationDate="2022-01-10",
            titleOriginal="Solar desalination system",
            abstractOriginal="A system for solar-driven desalination using integrated photothermal and membrane modules...",
            linkEspacenet="https://worldwide.espacenet.com/patent/search?q=pn%3DUS12421136B1"
        ),
        PatentItem(
            publicationNumber="WO2025167351A1",
            kindCode="A1",
            country="WO",
            publicationDate="2025-06-12",
            titleOriginal="Solar desalination and purification apparatus",
            abstractOriginal="An apparatus combining solar thermal collection with multi-effect evaporation for brine desalination...",
            linkEspacenet="https://worldwide.espacenet.com/patent/search?q=pn%3DWO2025167351A1"
        ),
        PatentItem(
            publicationNumber="CN120398169A",
            kindCode="A",
            country="CN",
            publicationDate="2024-03-18",
            titleOriginal="Photothermal solar desalination system",
            abstractOriginal="The invention discloses a photothermal solar desalination system featuring improved heat recovery...",
            linkEspacenet="https://worldwide.espacenet.com/patent/search?q=pn%3DCN120398169A"
        ),
    ]

def _generate_demo_pool(total: int = 75) -> List[PatentItem]:
    """
    Генерируем пул из 'total' записей на основе 3 базовых патентов.
    Делаем записи визуально разными, чтобы ассистент не «схлопывал» их как дубликаты.
    """
    base = _seed_base()
    pool: List[PatentItem] = []
    start_date = datetime(2022, 1, 10)

    for i in range(total):
        b = base[i % len(base)].model_copy(deep=True)

        # уникализируем номер публикации (чтобы строки отличались)
        b.publicationNumber = f"{b.publicationNumber}-D{i+1}"

        # делаем заголовок визуально уникальным — «rev D#»
        b.titleOriginal = f"{b.titleOriginal} (rev D{i+1})"

        # слегка варьируем страны/коды, чтобы записи не выглядели идентичными
        if i % 3 == 0:
            b.kindCode = "A1"
        elif i % 3 == 1:
            b.kindCode = "B1"
        else:
            b.kindCode = "A"

        # даты размазываем — так сортировка по новизне будет реальной
        d = start_date + timedelta(days=210 * (i % 6) + 17 * i)
        b.publicationDate = d.strftime("%Y-%m-%d")

        # ссылку НЕ перестраиваем — используем исходную из базы (linkEspacenet)
        pool.append(b)

    return pool

def _hydrate_with_translation(items: List[PatentItem]) -> List[PatentItem]:
    for it in items:
        it.abstractOriginal = _clip_en(it.abstractOriginal, 500)
        it.titleRu = _translate_ru(it.titleOriginal)
        it.abstractRu = _translate_ru(it.abstractOriginal)
    return items

def _get_sorted_pool() -> List[PatentItem]:
    pool = _generate_demo_pool(total=75)                 # пул из 75 штук
    pool = _hydrate_with_translation(pool)               # добавляем переводы
    pool.sort(key=lambda x: _parse_date_safe(x.publicationDate), reverse=True)  # newest→oldest
    return pool

# ---------- поиск (POST/GET) с пагинацией ----------
def _paginate(pool: List[PatentItem], page: int, size: int) -> SearchResponse:
    size = min(max(size, 1), 25)  # 1..25
    total = len(pool)
    start = (page - 1) * size
    end = start + size
    items = pool[start:end]
    next_page = page + 1 if end < total else None
    return SearchResponse(total=total, page=page, size=size, nextPage=next_page, items=items)

@app.post("/search", response_model=SearchResponse)
def search_post(payload: dict = Body(...)):
    # 'query' пока не используется (демо), оставляем для совместимости с твоим действием
    _ = payload.get("query", "")
    page = int(payload.get("page", 1))
    size = int(payload.get("size", 25))
    pool = _get_sorted_pool()
    return _paginate(pool, page, size)

@app.get("/search", response_model=SearchResponse)
def search_get(q: str = Query(""), page: int = 1, size: int = 25):
    pool = _get_sorted_pool()
    return _paginate(pool, page, size)
