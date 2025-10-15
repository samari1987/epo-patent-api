from fastapi import FastAPI, Body, Query
from pydantic import BaseModel
from typing import List, Optional

app = FastAPI(title="EPO Patent API", version="1.0.0")

class PatentItem(BaseModel):
    publicationNumber: str
    kindCode: Optional[str] = None
    country: Optional[str] = None
    publicationDate: Optional[str] = None
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

@app.get("/status")
def status():
    return {"status":"ok","service":"epo","version":"1.0.0"}

def demo_item() -> PatentItem:
    return PatentItem(
        publicationNumber="US12421136B1",
        kindCode="B1",
        country="US",
        publicationDate="2022-01-10",
        titleOriginal="Solar desalination system",
        abstractOriginal="A system for solar-driven desalination using integrated photothermal and membrane modules...",
        linkEspacenet="https://worldwide.espacenet.com/patent/search?q=pn%3DUS12421136B1"
    )

@app.post("/search", response_model=SearchResponse)
def search_post(payload: dict = Body(...)):
    q = payload.get("query","")
    page = int(payload.get("page",1))
    size = min(int(payload.get("size",10)), 25)
    return SearchResponse(total=1, page=page, size=size, nextPage=None, items=[demo_item()])

@app.get("/search", response_model=SearchResponse)
def search_get(q: str = Query(""), page: int = 1, size: int = 10):
    return SearchResponse(total=1, page=page, size=min(size,25), nextPage=None, items=[demo_item()])
