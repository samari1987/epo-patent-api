# main.py — 25 результатов + автоперевод названия/абстракта
from fastapi import FastAPI, Body, Query
from pydantic import BaseModel
from typing import List, Optional
from deep_translator import GoogleTranslator

app = FastAPI(title="EPO Patent API", version="1.3.0")

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

# ---------- статус ----------
@app.get("/status")
def status():
    return {"status": "ok", "service": "epo", "version": "1.3.0"}

# ---------- демо-данные (размножаем до 25) ----------
def _demo_items_raw() -> List[PatentItem]:
    base = [
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
        )
    ]
    items: List[PatentItem] = []
    for i in range(25):  # делаем 25 записей
        b = base[i % len(base)].model_copy(deep=True)
        b.publicationNumber = f"{b.publicationNumber}-D{i+1}"  # уникализируем, чтобы строки не слипались
        items.append(b)
    return items

def _demo_items_with_translation() -> List[PatentItem]:
    items = _demo_items_raw()
    for it in items:
        it.abstractOriginal = _clip_en(it.abstractOriginal, 500)
        it.titleRu = _translate_ru(it.titleOriginal)
        it.abstractRu = _translate_ru(it.abstractOriginal)
    return items

# ---------- поиск ----------
@app.post("/search", response_model=SearchResponse)
def search_post(payload: dict = Body(...)):
    page = int(payload.get("page", 1))
    size = min(int(payload.get("size", 25)), 25)  # default 25
    all_items = _demo_items_with_translation()
    return SearchResponse(total=len(all_items), page=page, size=size, nextPage=None, items=all_items[:size])

# Для ручной проверки из браузера
@app.get("/search", response_model=SearchResponse)
def search_get(q: str = Query(""), page: int = 1, size: int = 25):
    size = min(size, 25)
    all_items = _demo_items_with_translation()
    return SearchResponse(total=len(all_items), page=page, size=size, nextPage=None, items=all_items[:size])
