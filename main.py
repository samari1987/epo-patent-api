# main.py — EPO Patent API for "Scientific Innovator"
# Реальный EPO OPS + fallback demo, пагинация, сортировка по дате (newest→oldest), автоперевод
# v2.0.1 — читает OPS_CONSUMER_KEY/OPS_CONSUMER_SECRET или CONSUMER_KEY/CONSUMER_SECRET

from fastapi import FastAPI, Body, Query
from pydantic import BaseModel
from typing import List, Optional
from deep_translator import GoogleTranslator
from datetime import datetime, timedelta
import os
import requests
import xml.etree.ElementTree as ET

APP_VERSION = "2.0.1"
app = FastAPI(title="EPO Patent API", version=APP_VERSION)

# ========= MODELS =========
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

# ========= UTILS =========
# ---------- утилиты ----------
_tr = GoogleTranslator(source="auto", target="ru")

import re

def _build_ops_query(q: str) -> str:
    q_strip = q.strip()
    q_compact = re.sub(r"[\s\-]", "", q_strip).upper()
    # если это похоже на номер публикации (US12421136B1, WO2025167351A1, CN120398169A и т.п.)
    if re.match(r"^[A-Z]{2}\d{6,}[A-Z0-9]?$", q_compact):
        return f"pn={q_compact}"
    # иначе это текстовый запрос → переведём на английский и используем any="..."
    try:
        q_en = GoogleTranslator(source="auto", target="en").translate(q_strip)
    except Exception:
        q_en = q_strip
    return f'any="{q_en}"'

def _clip(text: Optional[str], n: int = 1200) -> Optional[str]:
    if not text:
        return None
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + "…"

def _parse_date_safe(s: Optional[str]) -> datetime:
    if not s:
        return datetime(1900, 1, 1)
    s = s.strip()
    try:
        if len(s) == 8:   # YYYYMMDD
            return datetime.strptime(s, "%Y%m%d")
        if len(s) == 6:   # YYYYMM
            return datetime.strptime(s, "%Y%m")
        if len(s) == 4:   # YYYY
            return datetime.strptime(s, "%Y")
        return datetime.strptime(s, "%Y-%m-%d")
    except Exception:
        return datetime(1900, 1, 1)

def _fmt_date_iso(d: Optional[str]) -> Optional[str]:
    dt = _parse_date_safe(d)
    return dt.strftime("%Y-%m-%d") if dt.year > 1900 else None

# ========= OPS (REAL) =========
OPS_KEY = os.getenv("OPS_CONSUMER_KEY") or os.getenv("CONSUMER_KEY")
OPS_SECRET = os.getenv("OPS_CONSUMER_SECRET") or os.getenv("CONSUMER_SECRET")
OPS_AUTH_URL = "https://ops.epo.org/3.2/auth/accesstoken"
OPS_SEARCH_URL = "https://ops.epo.org/3.2/rest-services/published-data/search"

def _get_ops_token() -> Optional[str]:
    if not OPS_KEY or not OPS_SECRET:
        return None
    try:
        r = requests.post(
            OPS_AUTH_URL,
            data={"grant_type": "client_credentials"},
            auth=(OPS_KEY, OPS_SECRET),
            timeout=30,
        )
        r.raise_for_status()
        return r.json().get("access_token")
    except Exception:
        return None

def _ops_search_raw(query: str, page: int, size: int, token: str) -> requests.Response:
    # OPS-пагинация через Range: "1-25", "26-50", ...
    start = (page - 1) * size + 1
    end = start + size - 1
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/xml",
        "Range": f"{start}-{end}",
    }
    params = {"q": f'any="{query}"'}  # универсальный запрос (название/реферат/текст)
    r = requests.get(OPS_SEARCH_URL, headers=headers, params=params, timeout=60)
    r.raise_for_status()
    return r

def _parse_ops_xml(xml_text: str) -> (List[PatentItem], int):
    ns = {
        "ops": "http://ops.epo.org",
        "exchange-doc": "http://www.epo.org/exchange",
    }
    root = ET.fromstring(xml_text)

    # total
    total = 0
    for attr in ["total-result-count", "total-result-size"]:
        val = root.attrib.get(attr)
        if val and val.isdigit():
            total = int(val)
            break
    if total == 0:
        tr = root.find(".//ops:total-result-count", ns)
        if tr is not None and tr.text and tr.text.isdigit():
            total = int(tr.text)

    items: List[PatentItem] = []
    for doc in root.findall(".//exchange-doc:exchange-document", ns):
        country = (doc.get("country") or "").strip()
        docnum = (doc.get("doc-number") or "").strip()
        kind = (doc.get("kind") or "").strip()
        pn = f"{country}{docnum}{kind}".strip()

        # дата публикации
        pub_date = None
        di = doc.find(".//exchange-doc:document-id", ns)
        if di is not None:
            dt_el = di.find(".//exchange-doc:date", ns)
            if dt_el is not None and dt_el.text:
                pub_date = _fmt_date_iso(dt_el.text)

        # название (en предпочтительно)
        title = None
        for t in doc.findall(".//exchange-doc:invention-title", ns):
            lang = t.get("{http://www.w3.org/XML/1998/namespace}lang", "").lower()
            if lang == "en":
                title = (t.text or "").strip()
                break
        if not title:
            t = doc.find(".//exchange-doc:invention-title", ns)
            title = (t.text or "").strip() if t is not None else "—"

        # абстракт (en, если есть)
        abstract = None
        for ab in doc.findall(".//exchange-doc:abstract", ns):
            lang = ab.get("{http://www.w3.org/XML/1998/namespace}lang", "").lower()
            text_parts = [p.text.strip() for p in ab.findall(".//exchange-doc:p", ns) if p.text]
            text_joined = " ".join(text_parts).strip()
            if not abstract:
                abstract = text_joined
            if lang == "en" and text_joined:
                abstract = text_joined
                break

        link = f"https://worldwide.espacenet.com/patent/search?q=pn%3D{pn}"

        items.append(PatentItem(
            publicationNumber=pn,
            kindCode=kind or None,
            country=country or None,
            publicationDate=pub_date,
            titleOriginal=title,
            abstractOriginal=_clip(abstract, 1200),
            linkEspacenet=link,
        ))

    items.sort(key=lambda x: _parse_date_safe(x.publicationDate), reverse=True)
    if total == 0:
        total = len(items)
    return items, total

def fetch_real_patents(query: str, page: int, size: int) -> Optional[SearchResponse]:
    token = _get_ops_token()
    if not token:
        return None
    r = _ops_search_raw(query=query, page=page, size=size, token=token)
    items, total = _parse_ops_xml(r.text)

    # автоперевод
    for it in items:
        it.titleRu = _translate_ru(it.titleOriginal)
        it.abstractRu = _translate_ru(it.abstractOriginal)

    start = (page - 1) * size + 1
    next_page = page + 1 if (start - 1 + len(items)) < total else None
    return SearchResponse(total=total, page=page, size=size, nextPage=next_page, items=items)

# ========= DEMO (FALLBACK) =========
def _seed_demo() -> List[PatentItem]:
    return [
        PatentItem(
            publicationNumber="CN120398169A",
            kindCode="A",
            country="CN",
            publicationDate="2025-08-01",
            titleOriginal="Solar seawater desalination device for evaporation driven by immersed heat pipe",
            abstractOriginal="The invention provides a solar seawater desalination device for evaporation driven by an immersed heat pipe...",
            linkEspacenet="https://worldwide.espacenet.com/patent/search?q=pn%3DCN120398169A",
        ),
        PatentItem(
            publicationNumber="WO2025167351A1",
            kindCode="A1",
            country="WO",
            publicationDate="2025-06-12",
            titleOriginal="Solar desalination and purification apparatus",
            abstractOriginal="An apparatus combining solar thermal collection with multi-effect evaporation for brine desalination...",
            linkEspacenet="https://worldwide.espacenet.com/patent/search?q=pn%3DWO2025167351A1",
        ),
        PatentItem(
            publicationNumber="US12421136B1",
            kindCode="B1",
            country="US",
            publicationDate="2022-01-10",
            titleOriginal="Solar desalination system",
            abstractOriginal="A system for solar-driven desalination using integrated photothermal and membrane modules...",
            linkEspacenet="https://worldwide.espacenet.com/patent/search?q=pn%3DUS12421136B1",
        ),
    ]

def _demo_pool(total: int = 75) -> List[PatentItem]:
    base = _seed_demo()
    pool: List[PatentItem] = []
    start_dt = datetime(2022, 1, 10)
    for i in range(total):
        b = base[i % len(base)].model_copy(deep=True)
        b.publicationNumber = f"{b.publicationNumber}-D{i+1}"
        b.titleOriginal = f"{b.titleOriginal} (rev D{i+1})"
        d = start_dt + timedelta(days=220 * (i % 6) + 13 * i)
        b.publicationDate = d.strftime("%Y-%m-%d")
        pool.append(b)
    pool.sort(key=lambda x: _parse_date_safe(x.publicationDate), reverse=True)
    for it in pool:
        it.titleRu = _translate_ru(it.titleOriginal)
        it.abstractRu = _translate_ru(it.abstractOriginal)
    return pool

def _paginate(pool: List[PatentItem], page: int, size: int) -> SearchResponse:
    size = min(max(size, 1), 25)
    total = len(pool)
    start = (page - 1) * size
    end = start + size
    items = pool[start:end]
    next_page = page + 1 if end < total else None
    return SearchResponse(total=total, page=page, size=size, nextPage=next_page, items=items)

# ========= ENDPOINTS =========
@app.get("/status")
def status():
    mode = "ops" if OPS_KEY and OPS_SECRET else "demo"
    return {"status": "ok", "service": "epo", "mode": mode, "version": APP_VERSION}

@app.post("/search", response_model=SearchResponse)
def search_post(payload: dict = Body(...)):
    query = payload.get("query", "")
    page = int(payload.get("page", 1))
    size = int(payload.get("size", 25))
    # пробуем OPS
    try:
        sr = fetch_real_patents(query=query, page=page, size=size)
        if sr:
            return sr
    except Exception:
        pass
    # fallback demo
    pool = _demo_pool(total=75)
    return _paginate(pool, page, size)

@app.get("/search", response_model=SearchResponse)
def search_get(q: str = Query(""), page: int = 1, size: int = 25):
    try:
        sr = fetch_real_patents(query=q, page=page, size=size)
        if sr:
            return sr
    except Exception:
        pass
    pool = _demo_pool(total=75)
    return _paginate(pool, page, size)
