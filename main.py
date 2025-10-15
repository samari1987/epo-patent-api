# main.py — готовая демо-версия для Научного Инноватора
from fastapi import FastAPI, Body, Query
from pydantic import BaseModel
from typing import List, Optional

app = FastAPI(title="EPO Patent API", version="1.0.0")

# ---- Модели данных ----
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

# ---- Проверка статуса ----
@app.get("/status")
def status():
    return {"status": "ok", "service": "epo", "version": "1.0.0"}

# ---- Примерные данные (демо-патенты) ----
def demo_items() -> List[PatentItem]:
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
        )
    ]

# ---- Основной эндпоинт поиска ----
@app.post("/search", response_model=SearchResponse)
def search_post(payload: dict = Body(...)):
    q = payload.get("query", "")
    page = int(payload.get("page", 1))
    size = min(int(payload.get("size", 10)), 25)
    items = demo_items()[:size]
    return SearchResponse(total=len(items), page=page, size=size, nextPage=None, items=items)

# ---- Проверка через браузер (GET) ----
@app.get("/search", response_model=SearchResponse)
def search_get(q: str = Query(""), page: int = 1, size: int = 10):
    items = demo_items()[:min(size, 25)]
    return SearchResponse(total=len(items), page=page, size=min(size, 25), nextPage=None, items=items)

    items = demo_items()[:min(size, 25)]
    return SearchResponse(total=len(items), page=page, size=min(size, 25), nextPage=None, items=items)

