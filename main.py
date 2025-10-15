# main.py — API для Научного Инноватора с автопереводом и size=25
from fastapi import FastAPI, Body, Query
from pydantic import BaseModel
from typing import List, Optional
from deep_translator import GoogleTranslator  # без ключа; есть лимиты, но для демо ок

app = FastAPI(title="EPO Patent API", version="1.1.0")

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
        # укоротим до 500 символов по слову
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
    return {"status": "ok", "service": "epo", "version": "1.1.0"}

# ---------- демо-данные (можно заменить реальным поиском позже) ----------
def demo_items() -> List[PatentItem]:
    items = [
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
    # автоперевод (мягкий фоллбэк)
    for it in items:
        it.abstractOriginal = _clip_en(it.abstractOriginal, 500)
        it.titleRu = _translate_ru(it.titleOriginal)
        it.abstractRu = _translate_ru(it.abstractOriginal)
    return items

# ---------- поиск ----------
@app.post("/search", response_model=SearchResponse)
def search_post(payload: dict = Body(...)):
    q = payload.get("query", "")
    page = int(payload.get("page", 1))
    size = min(int(payload.get("size", 25)), 25)  # по умолчанию 25
    items = demo_items()[:size]
    return SearchResponse(total=len(items), page=page, size=size, nextPage=None, items=items)

# для ручной проверки из браузера
@app.get("/search", response_model=SearchResponse)
def search_get(q: str = Query(""), page: int = 1, size: int = 25):
    size = min(size, 25)
    items = demo_items()[:size]
    return SearchResponse(total=len(items), page=page, size=size, nextPage=None, items=items)
