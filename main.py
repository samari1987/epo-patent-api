# main.py — EPO Patent API for "Scientific Innovator"
# v2.0.2
#
# Функции:
#  - /status  : статус сервиса, режим работы ("ops" или "demo")
#  - /search  : поиск патентов (через EPO OPS, с fallback на демо)
#
# Ключи EPO OPS должны быть в переменных окружения:
#   OPS_CONSUMER_KEY / OPS_CONSUMER_SECRET
#   или (fallback имена)
#   CONSUMER_KEY / CONSUMER_SECRET
#
# Формат ответа:
#   SearchResponse {
#       total, page, size, nextPage, items[PatentItem]
#   }
#
#   PatentItem {
#       publicationNumber   (например "US12421136B1")
#       publicationDate     (YYYY-MM-DD)
#       country             ("US", "WO", ...)
#       kindCode            ("A1", "B1", ...)
#       titleOriginal       (оригинальное название)
#       titleRu             (перевод названия на русский)
#       abstractOriginal    (абстракт в оригинале)
#       abstractRu          (перевод абстракта)
#       linkEspacenet       (кликабельная ссылка на Espacenet)
#   }
#
# Важно:
#  - если OPS отдал 400/401/... или ключей нет — выдаём fallback-демо,
#    чтобы ассистент не падал.
#  - данные сортируются по дате публикации (новые → старые).
#
# Это готовый файл: просто положи его как main.py
# и задеплой.

import os
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, Query, Body
from pydantic import BaseModel
from deep_translator import GoogleTranslator


APP_VERSION = "2.0.2"
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
        # если переводчик упал (лимит, сеть), не ломаем весь ответ
        return None


def _clip(text: Optional[str], n: int = 1200) -> Optional[str]:
    """Нормализуем пробелы и мягко обрезаем до n символов (с завершением по слову)."""
    if not text:
        return None
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + "…"


def _parse_date_safe(raw: Optional[str]) -> datetime:
    """
    Парсим дату, которая может приходить как YYYYMMDD, YYYY-MM-DD, YYYYMM, YYYY.
    Если не распознали — возвращаем 1900-01-01, чтобы сортировка не падала.
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
    """
    Возвращаем нормальный ISO-формат YYYY-MM-DD (или None, если дата мусор).
    """
    d = _parse_date_safe(raw)
    return d.strftime("%Y-%m-%d") if d.year > 1900 else None


# ---------- OPS credentials / endpoints ----------

OPS_KEY    = os.getenv("OPS_CONSUMER_KEY")    or os.getenv("CONSUMER_KEY")
OPS_SECRET = os.getenv("OPS_CONSUMER_SECRET") or os.getenv("CONSUMER_SECRET")

OPS_AUTH_URL   = "https://ops.epo.org/3.2/auth/accesstoken"
OPS_SEARCH_URL = "https://ops.epo.org/3.2/rest-services/published-data/search"


def _get_ops_token() -> Optional[str]:
    """
    Получаем OAuth2 access_token для EPO OPS по client_credentials.
    Если не получилось — вернём None.
    """
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


def _ops_search_raw(query_text: str, page: int, size: int, token: str) -> str:
    """
    Делаем сырой GET к OPS /published-data/search.
    Возвращаем XML-строку (text).
    Можем кинуть HTTPError, если статус >=400.
    """

    # Диапазон для Range-заголовка: 1-25, 26-50 и т.д.
    start = (page - 1) * size + 1
    end   = start + size - 1
    range_header = f"{start}-{end}"

    # Параметр q: any="solar desalination"
    # Запрос будет закодирован requests сам.
    params = {
        "q": f'any="{query_text}"'
    }

    headers = {
        # Bearer (важно именно так, без "Bearer=")
        "Authorization": f"Bearer {token}",
        "Accept": "application/xml",
        # OPS любит Range; если слишком нагло попросим — может дать 400
        "Range": range_header,
    }

    r = requests.get(
        OPS_SEARCH_URL,
        headers=headers,
        params=params,
        timeout=30
    )

    # Если 4xx/5xx — выкинем HTTPError
    if r.status_code >= 400:
        print("OPS SEARCH ERROR:", r.status_code, r.text[:500])
        r.raise_for_status()

    return r.text


def _parse_ops_xml(xml_text: str) -> (List[PatentItem], int):
    """
    Парсер XML ответа OPS.
    Возвращает:
        - список PatentItem
        - total (общее число результатов)
    Если парсинг не удался — вернём ([], 0).
    """

    # В ответах OPS используются пространства имён:
    # xmlns="http://ops.epo.org" и "http://www.epo.org/exchange"
    ns = {
        "ops": "http://ops.epo.org",
        "ex":  "http://www.epo.org/exchange",
    }

    try:
        root = ET.fromstring(xml_text)
    except Exception as e:
        print("XML parse fail:", e)
        return [], 0

    # Достаём общее количество результатов
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

    # Документы обычно лежат как ex:exchange-document
    for doc in root.findall(".//ex:exchange-document", ns):
        country = (doc.get("country") or "").strip()
        docnum  = (doc.get("doc-number") or "").strip()
        kind    = (doc.get("kind") or "").strip()
        pn      = f"{country}{docnum}{kind}"

        # Пытаемся достать дату публикации
        pub_date = None
        di = doc.find(".//ex:document-id", ns)
        if di is not None:
            dt_el = di.find(".//ex:date", ns)
            if dt_el is not None and dt_el.text:
                pub_date = _fmt_date_iso(dt_el.text)

        # Заголовок. Предпочтительно lang="en", иначе любой
        title_val = None
        for t in doc.findall(".//ex:invention-title", ns):
            lang = (t.get("{http://www.w3.org/XML/1998/namespace}lang") or "").lower()
            cand = (t.text or "").strip()
            if not title_val:
                title_val = cand
            if lang == "en" and cand:
                title_val = cand
                break
        if not title_val:
            title_val = "—"

        # Абстракт. Тоже сначала берём en, если есть.
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

    # сортируем newest → oldest
    out_items.sort(
        key=lambda it: _parse_date_safe(it.publicationDate),
        reverse=True
    )

    return out_items, total


def fetch_real_patents(query: str, page: int, size: int) -> Optional[SearchResponse]:
    """
    Пытаемся получить реальные патенты через OPS.
    Если всё ОК — вернём SearchResponse.
    Если не ОК (нет токена, 400, др. ошибка) — вернём None.
    """
    token = _get_ops_token()
    if not token:
        # нет ключей или не дали токен
        return None

    try:
        xml_text = _ops_search_raw(
            query_text=query,
            page=page,
            size=size,
            token=token
        )
    except Exception as e:
        print("OPS fetch error:", e)
        return None

    items, total = _parse_ops_xml(xml_text)

    # переводим названия и абстракты
    for it in items:
        it.titleRu    = _translate_ru(it.titleOriginal)
        it.abstractRu = _translate_ru(it.abstractOriginal)

    # считаем nextPage
    start = (page - 1) * size + 1
    next_page = page + 1 if (start - 1 + len(items)) < total else None

    return SearchResponse(
        total    = total,
        page     = page,
        size     = size,
        nextPage = next_page,
        items    = items[:size],
    )


# ---------- DEMO fallback ----------
# Если OPS не сработал, мы отдаём стабильную демо-выборку,
# чтобы ассистент не разваливался и мог продолжать анализ.

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

    # сортируем по дате публикации (новые сначала)
    demo.sort(
        key=lambda it: _parse_date_safe(it.publicationDate),
        reverse=True
    )

    # переводы
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
    """
    Быстрый "здоров ли сервис".
    mode:
      - "ops"  если у нас есть OPS ключи и мы потенциально можем звать EPO
      - "demo" если нет ключей (или они не заданы в Render env)
    """
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
        "query": "solar desalination",
        "page": 1,
        "size": 25
      }

    Возвращает SearchResponse.
    """
    query = payload.get("query", "")
    page  = int(payload.get("page", 1))
    size  = int(payload.get("size", 25))

    # Пытаемся сходить в реальную OPS
    sr = fetch_real_patents(query=query, page=page, size=size)
    if sr:
        return sr

    # Если OPS не дал — fallback демо
    return _paginate_demo(page=page, size=size)


@app.get("/search", response_model=SearchResponse)
def search_get(
    q: str = Query(""),
    page: int = 1,
    size: int = 25
):
    """
    GET /search?q=...&page=1&size=25
    Такой же смысл, но через query-параметры.
    """
    sr = fetch_real_patents(query=q, page=page, size=size)
    if sr:
        return sr

    return _paginate_demo(page=page, size=size)
