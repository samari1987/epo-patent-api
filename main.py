# main.py — EPO Patent API for "Scientific Innovator"
# v2.1.0
#
# Что умеет:
#  - /status  : статус сервиса, режим ("ops" или "demo")
#  - /search  : поиск патентов через EPO OPS с fallback на демо
#
# Переменные окружения для EPO OPS:
#   OPS_CONSUMER_KEY / OPS_CONSUMER_SECRET
#   (или синонимы)  CONSUMER_KEY / CONSUMER_SECRET
#
# Формат ответа:
#   SearchResponse {
#       total, page, size, nextPage, items[PatentItem]
#   }
#
#   PatentItem {
#       publicationNumber, publicationDate(YYYY-MM-DD), country, kindCode,
#       titleOriginal, titleRu, abstractOriginal, abstractRu, linkEspacenet
#   }
#
# Важно:
#  - CQL (OPS) формируем корректно: ti=.../ab=... с OR;
#  - если OPS недоступен (нет токена, 400, и т.д.) — отдаём демо;
#  - сортируем newest → oldest;
#  - аккуратный перевод GoogleTranslator (обрезка 500 символов).

import os
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import List, Optional, Tuple
from urllib.parse import quote_plus

from fastapi import FastAPI, Query, Body, HTTPException
from pydantic import BaseModel
from deep_translator import GoogleTranslator


APP_VERSION = "2.1.0"
app = FastAPI(title="EPO Patent API", version=APP_VERSION)

# ---------- Pydantic модели ----------

class PatentItem(BaseModel):
    publicationNumber: str
    kindCode: Optional[str] = None
    country: Optional[str] = None
    publicationDate: Optional[str] = None  # "YYYY-MM-DD"
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


# ---------- Утилиты ----------

_tr = GoogleTranslator(source="auto", target="ru")

def _translate_ru(text: Optional[str]) -> Optional[str]:
    """Перевод EN → RU, обрезка до ~500 символов."""
    if not text:
        return None
    try:
        t = _tr.translate(text.strip())
        if t and len(t) > 500:
            t = t[:500].rsplit(" ", 1)[0] + "…"
        return t
    except Exception:
        return None


def _clip(text: Optional[str], n: int = 1200) -> Optional[str]:
    """Нормализуем пробелы и мягко обрезаем до n символов (с завершением по слову)."""
    if not text:
        return None
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + "…"


def _parse_date_safe(raw: Optional[str]) -> datetime:
    """
    Парсим дату: YYYYMMDD, YYYY-MM-DD, YYYYMM, YYYY.
    На нераспознаваемое — 1900-01-01 (чтобы сортировка не падала).
    """
    if not raw:
        return datetime(1900, 1, 1)
    raw = raw.strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y%m", "%Y"):
        try:
            return datetime.strptime(raw, fmt)
        except Exception:
            pass
    return datetime(1900, 1, 1)


def _fmt_date_iso(raw: Optional[str]) -> Optional[str]:
    """Возвращаем ISO YYYY-MM-DD (или None, если дата мусор)."""
    d = _parse_date_safe(raw)
    return d.strftime("%Y-%m-%d") if d.year > 1900 else None


# ---------- OPS credentials / endpoints ----------

OPS_KEY    = os.getenv("OPS_CONSUMER_KEY")    or os.getenv("CONSUMER_KEY")
OPS_SECRET = os.getenv("OPS_CONSUMER_SECRET") or os.getenv("CONSUMER_SECRET")

OPS_AUTH_URL   = "https://ops.epo.org/3.2/auth/accesstoken"
OPS_SEARCH_URL = "https://ops.epo.org/3.2/rest-services/published-data/search"


def _get_ops_token() -> Optional[str]:
    """OAuth2 access_token для EPO OPS (client_credentials)."""
    if not OPS_KEY or not OPS_SECRET:
        return None
    try:
        r = requests.post(
            OPS_AUTH_URL,
            data={"grant_type": "client_credentials"},
            auth=(OPS_KEY, OPS_SECRET),
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        return data.get("access_token")
    except Exception as e:
        print("epo-api:get_ops_token ERROR:", e)
        return None


# ---------- CQL построение запроса ----------

def _build_cql_from_query(q: str) -> str:
    """
    Переводим пользовательский текст в корректный CQL для OPS.
    Пример: "solar desalination lithium"
    -> "ti=solar or ab=solar or ti=desalination or ab=desalination or ti=lithium or ab=lithium"
    """
    # очень простая токенизация: убираем запятые и разбиваем по пробелам
    words = [w.strip() for w in q.replace(",", " ").split() if len(w.strip()) > 2]
    if not words:
        # пустой запрос — вернём что-то безопасное
        return "ti=water or ab=water"

    parts = []
    for w in words:
        # можно усложнить (фразы в кавычках, AND/OR), но для стабильности — OR по ti/ab
        parts.append(f"ti={w}")
        parts.append(f"ab={w}")

    cql = " or ".join(parts)
    return cql


def _ops_search_raw(query_text: str, page: int, size: int, token: str) -> str:
    """
    GET к OPS /published-data/search.
    Возвращаем XML-строку, либо кидаем HTTPError при 4xx/5xx.
    """
    # Range: 1-25, 26-50, ...
    start = (page - 1) * size + 1
    end   = start + size - 1
    range_header = f"{start}-{end}"

    # Собираем CQL и кодируем (в params — requests сам закодирует, но лог выводим «как есть»)
    cql = _build_cql_from_query(query_text)
    params = {"q": cql}

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/xml",
        "Range": range_header,
    }

    # Для удобного дебага видим, что реально отправляем:
    print(f"[OPS] Range={range_header}  CQL={cql}")

    r = requests.get(
        OPS_SEARCH_URL,
        headers=headers,
        params=params,
        timeout=30
    )
    if r.status_code >= 400:
        print("OPS SEARCH ERROR:", r.status_code, r.text[:600])
        r.raise_for_status()

    return r.text


# ---------- Парсер XML ответа OPS ----------

def _parse_ops_xml(xml_text: str) -> Tuple[List[PatentItem], int]:
    """
    Парсим XML OPS.
    Возвращаем (items, total). На неудачу — ([], 0).
    """
    ns = {
        "ops": "http://ops.epo.org",
        "ex":  "http://www.epo.org/exchange",
    }

    try:
        root = ET.fromstring(xml_text)
    except Exception as e:
        print("XML parse fail:", e)
        return [], 0

    # total-результаты
    total = 0
    for attr in ["total-result-count", "total-result-size"]:
        v = root.attrib.get(attr)
        if v and v.isdigit():
            total = int(v)
            break
    if total == 0:
        tr = root.find(".//ops:total-result-count", ns)
        if tr is not None and tr.text and tr.text.isdigit():
            total = int(tr.text)

    out_items: List[PatentItem] = []

    for doc in root.findall(".//ex:exchange-document", ns):
        country = (doc.get("country") or "").strip()
        docnum  = (doc.get("doc-number") or "").strip()
        kind    = (doc.get("kind") or "").strip()
        pn      = f"{country}{docnum}{kind}"

        # дата публикации
        pub_date = None
        di = doc.find(".//ex:document-id", ns)
        if di is not None:
            dt_el = di.find(".//ex:date", ns)
            if dt_el is not None and dt_el.text:
                pub_date = _fmt_date_iso(dt_el.text)

        # title (предпочтительно en)
        title_val = None
        for t in doc.findall(".//ex:invention-title", ns):
            lang = (t.get("{http://www.w3.org/XML/1998/namespace}lang") or "").lower()
            cand = (t.text or "").strip()
            if not title_val and cand:
                title_val = cand
            if lang == "en" and cand:
                title_val = cand
                break
        if not title_val:
            title_val = "—"

        # abstract (предпочтительно en)
        abstract_val = None
        for ab in doc.findall(".//ex:abstract", ns):
            lang = (ab.get("{http://www.w3.org/XML/1998/namespace}lang") or "").lower()
            parts = []
            for p in ab.findall(".//ex:p", ns):
                if p.text:
                    parts.append(p.text.strip())
            joined = " ".join(parts).strip()
            if not abstract_val and joined:
                abstract_val = joined
            if lang == "en" and joined:
                abstract_val = joined
                break

        abstract_val = _clip(abstract_val, 1200)

        link_esp = f"https://worldwide.espacenet.com/patent/search?q=pn%3D{pn}"

        item = PatentItem(
            publicationNumber = pn,
            kindCode          = kind or None,
            country           = country or None,
            publicationDate   = pub_date,
            titleOriginal     = title_val,
            abstractOriginal  = abstract_val,
            linkEspacenet     = link_esp,
        )
        out_items.append(item)

    # newest → oldest
    out_items.sort(key=lambda it: _parse_date_safe(it.publicationDate), reverse=True)
    return out_items, total


# ---------- Обёртка получения из OPS ----------

def fetch_real_patents(query: str, page: int, size: int) -> Optional[SearchResponse]:
    """Возвращает SearchResponse из OPS или None при ошибке/отсутствии токена."""
    token = _get_ops_token()
    if not token:
        return None

    try:
        xml_text = _ops_search_raw(query_text=query, page=page, size=size, token=token)
    except requests.HTTPError as e:
        # 400 — чаще всего синтаксис запроса; не роняем, вернём None (демо подхватится)
        print("OPS fetch error:", e)
        return None
    except Exception as e:
        print("OPS fetch error (network):", e)
        return None

    items, total = _parse_ops_xml(xml_text)

    # Переводы
    for it in items:
        it.titleRu    = _translate_ru(it.titleOriginal)
        it.abstractRu = _translate_ru(it.abstractOriginal)

    # nextPage
    start_index = (page - 1) * size + 1
    next_page = page + 1 if (start_index - 1 + len(items)) < total else None

    return SearchResponse(
        total    = total,
        page     = page,
        size     = size,
        nextPage = next_page,
        items    = items[:size],
    )


# ---------- DEMO fallback ----------

def _demo_pool() -> List[PatentItem]:
    demo = [
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
    demo.sort(key=lambda it: _parse_date_safe(it.publicationDate), reverse=True)
    for it in demo:
        it.titleRu    = _translate_ru(it.titleOriginal)
        it.abstractRu = _translate_ru(it.abstractOriginal)
    return demo


def _paginate_demo(page: int, size: int) -> SearchResponse:
    pool = _demo_pool()
    total = len(pool)
    start = (page - 1) * size
    end   = start + size
    items = pool[start:end]
    nextp = page + 1 if end < total else None

    return SearchResponse(
        total    = total,
        page     = page,
        size     = size,
        nextPage = nextp,
        items    = items,
    )


# ---------- ENDPOINTS FastAPI ----------

@app.get("/status")
def status():
    """Проверка готовности сервиса."""
    mode = "ops" if OPS_KEY and OPS_SECRET else "demo"
    return {
        "status": "ok",
        "service": "epo",
        "mode": mode,
        "version": APP_VERSION,
        "time": datetime.utcnow().isoformat()
    }


@app.post("/search", response_model=SearchResponse)
def search_post(payload: dict = Body(...)):
    """
    POST /search
    payload:
      {
        "query": "solar desalination lithium",
        "page": 1,
        "size": 25
      }
    """
    query = payload.get("query", "")
    page  = int(payload.get("page", 1))
    size  = int(payload.get("size", 25))

    # Сначала реальный OPS
    sr = fetch_real_patents(query=query, page=page, size=size)
    if sr:
        return sr

    # Fallback
    return _paginate_demo(page=page, size=size)


@app.get("/search", response_model=SearchResponse)
def search_get(q: str = Query(""), page: int = 1, size: int = 25):
    """GET /search?q=...&page=1&size=25"""
    sr = fetch_real_patents(query=q, page=page, size=size)
    if sr:
        return sr
    return _paginate_demo(page=page, size=size)
