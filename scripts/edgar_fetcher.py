"""SEC EDGAR API integration for fetching M&A training documents."""

from __future__ import annotations

from datetime import date
import logging
import re
import time
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from scripts.ma_corpus_db import get_db

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
EDGAR_DOWNLOAD_DIR = ROOT / "training_docs_inbox" / "edgar"

EFTS_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
EFTS_FULLTEXT_URL = "https://efts.sec.gov/LATEST/search-index"
EDGAR_FULL_TEXT_SEARCH = "https://efts.sec.gov/LATEST/search-index"
EDGAR_BASE = "https://www.sec.gov"

HEADERS = {
    "User-Agent": "LawAgent/1.0 (educational M&A research tool; contact@nickvbattaglia.com)",
    "Accept": "application/json",
}

TEXT_HEADERS = {
    "User-Agent": "LawAgent/1.0 (educational M&A research tool; contact@nickvbattaglia.com)",
    "Accept": "text/html, text/plain, application/xhtml+xml",
}

MA_SEARCH_QUERIES = [
    '"agreement and plan of merger"',
    '"asset purchase agreement"',
    '"stock purchase agreement"',
    '"merger agreement" exhibit',
]

SEC_RATE_LIMIT_DELAY = 0.12
DEFAULT_END_DATE = date.today().isoformat()

EXHIBIT_MERGER = ["EX-2.1", "EX-2", "MERGER AGREEMENT", "AGREEMENT AND PLAN OF MERGER"]
EXHIBIT_MATERIAL = ["EX-10", "EX-10.1", "EX-10.2", "MATERIAL CONTRACT"]


def _get_session() -> requests.Session:
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _sanitize_filename(name: str) -> str:
    name = re.sub(r"[^\w\s\-.]", "_", name)
    name = re.sub(r"\s+", "_", name)
    return name[:120]


def _rate_limit():
    time.sleep(SEC_RATE_LIMIT_DELAY)


def search_edgar_filings(
    query: str = '"agreement and plan of merger"',
    forms: str = "8-K,8-K/A",
    start_date: str = "2022-01-01",
    end_date: str = DEFAULT_END_DATE,
    max_results: int = 10,
) -> list[dict[str, Any]]:
    session = _get_session()
    params = {
        "q": query,
        "forms": forms,
        "dateRange": "custom",
        "startdt": start_date,
        "enddt": end_date,
        "from": 0,
        "size": min(max_results, 40),
    }
    try:
        _rate_limit()
        response = session.get(EFTS_SEARCH_URL, params=params, headers=HEADERS, timeout=20)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.HTTPError as exc:
        logger.warning("EDGAR search HTTP error: %s", exc)
        return [{"error": f"SEC EDGAR returned {exc.response.status_code}: {exc.response.reason}"}]
    except requests.exceptions.ConnectionError as exc:
        logger.warning("EDGAR search connection error: %s", exc)
        return [{"error": "Could not connect to SEC EDGAR. Please try again later."}]
    except requests.exceptions.Timeout:
        return [{"error": "SEC EDGAR request timed out. Please try again."}]
    except Exception as exc:
        logger.exception("EDGAR search unexpected error")
        return [{"error": str(exc)}]

    hits = data.get("hits", {}).get("hits", [])
    results = []
    for hit in hits[:max_results]:
        source = hit.get("_source", {})
        hit_id = hit.get("_id", "")
        display_names = source.get("display_names", [])
        entity_name = display_names[0] if display_names else "Unknown"
        entity_name = re.sub(r"\s*\(CIK \d+\)", "", entity_name).strip()

        adsh = source.get("adsh", "")
        ciks = source.get("ciks", [])
        cik = ciks[0].lstrip("0") if ciks else ""

        file_url = ""
        if adsh and cik and hit_id:
            doc_filename = hit_id.split(":", 1)[-1] if ":" in hit_id else ""
            adsh_path = adsh.replace("-", "")
            if doc_filename:
                file_url = f"{EDGAR_BASE}/Archives/edgar/data/{cik}/{adsh_path}/{doc_filename}"

        file_desc = source.get("file_description") or source.get("form", "")
        file_type = source.get("file_type", "")

        is_merger_exhibit = any(ex.lower() in file_desc.lower() or ex.lower() in file_type.lower() for ex in EXHIBIT_MERGER)
        is_material_exhibit = any(ex.lower() in file_desc.lower() or ex.lower() in file_type.lower() for ex in EXHIBIT_MATERIAL)

        results.append({
            "entity_name": entity_name,
            "file_date": source.get("file_date", ""),
            "file_type": file_type,
            "file_description": file_desc,
            "file_url": file_url,
            "display_names": display_names,
            "adsh": adsh,
            "exhibit_type": "merger_agreement" if is_merger_exhibit else ("material_contract" if is_material_exhibit else "other"),
        })

    return results


def fetch_filing_text(file_url: str) -> str | None:
    if not file_url:
        return None
    session = _get_session()
    try:
        import html as html_mod
        _rate_limit()
        response = session.get(file_url, headers=TEXT_HEADERS, timeout=30)
        response.raise_for_status()
        text = response.text
        text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = html_mod.unescape(text)
        text = re.sub(r"&#\d+;", " ", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = text.strip()
        return text if len(text) > 500 else None
    except requests.exceptions.HTTPError as exc:
        logger.warning("EDGAR fetch HTTP error for %s: %s", file_url, exc)
        return None
    except requests.exceptions.Timeout:
        logger.warning("EDGAR fetch timeout for %s", file_url)
        return None
    except Exception:
        logger.exception("EDGAR fetch unexpected error for %s", file_url)
        return None


def download_and_ingest(
    file_url: str,
    entity_name: str,
    file_date: str,
    file_description: str = "",
    exhibit_type: str = "other",
) -> dict[str, Any]:
    EDGAR_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    text = fetch_filing_text(file_url)
    if not text:
        return {"status": "skipped", "reason": "no_text_extracted", "url": file_url}

    safe_name = _sanitize_filename(f"{entity_name}_{file_date}_{file_description or 'merger_agreement'}")
    file_path = EDGAR_DOWNLOAD_DIR / f"{safe_name}.txt"
    file_path.write_text(text, encoding="utf-8")

    tag_overrides: dict[str, str] = {}
    if exhibit_type == "merger_agreement":
        tag_overrides["deal_structure"] = "merger"
    elif "asset" in file_description.lower():
        tag_overrides["deal_structure"] = "asset purchase"
    elif "stock" in file_description.lower():
        tag_overrides["deal_structure"] = "stock purchase"

    result = get_db().upsert_document(file_path, tag_overrides=tag_overrides or None)
    result["edgar_url"] = file_url
    result["entity_name"] = entity_name
    result["exhibit_type"] = exhibit_type
    return result


def search_and_ingest(
    query: str = '"agreement and plan of merger"',
    max_filings: int = 5,
    start_date: str = "2022-01-01",
    end_date: str = DEFAULT_END_DATE,
    forms: str = "8-K,8-K/A",
) -> dict[str, Any]:
    filings = search_edgar_filings(
        query=query,
        forms=forms,
        start_date=start_date,
        end_date=end_date,
        max_results=max_filings,
    )

    if not filings or (len(filings) == 1 and "error" in filings[0]):
        return {
            "status": "error",
            "message": filings[0].get("error", "No results") if filings else "No results",
            "filings_found": 0,
            "ingested": [],
        }

    ingested = []
    for filing in filings:
        if "error" in filing or not filing.get("file_url"):
            continue
        result = download_and_ingest(
            file_url=filing["file_url"],
            entity_name=filing["entity_name"],
            file_date=filing.get("file_date", "unknown"),
            file_description=filing.get("file_description", ""),
            exhibit_type=filing.get("exhibit_type", "other"),
        )
        ingested.append(result)

    return {
        "status": "complete",
        "filings_found": len(filings),
        "ingested": ingested,
        "corpus_status": get_db().stats(),
    }
