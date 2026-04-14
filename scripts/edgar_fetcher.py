"""SEC EDGAR API integration for fetching M&A training documents."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any
import requests

from scripts.ma_corpus_db import get_db

ROOT = Path(__file__).resolve().parents[1]
EDGAR_DOWNLOAD_DIR = ROOT / "training_docs_inbox" / "edgar"

EFTS_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
EDGAR_BASE = "https://www.sec.gov"

HEADERS = {
    "User-Agent": "LawAgent-Demo/1.0 (educational M&A research tool; lawagent@demo.replit.app)",
    "Accept": "application/json",
}

TEXT_HEADERS = {
    "User-Agent": "LawAgent-Demo/1.0 (educational M&A research tool; lawagent@demo.replit.app)",
    "Accept": "text/html, text/plain, application/xhtml+xml",
}

MA_SEARCH_QUERIES = [
    '"agreement and plan of merger"',
    '"asset purchase agreement"',
    '"stock purchase agreement"',
    '"merger agreement" exhibit',
]


def _sanitize_filename(name: str) -> str:
    name = re.sub(r"[^\w\s\-.]", "_", name)
    name = re.sub(r"\s+", "_", name)
    return name[:120]


def search_edgar_filings(
    query: str = '"agreement and plan of merger"',
    forms: str = "8-K,8-K/A",
    start_date: str = "2022-01-01",
    end_date: str = "2025-12-31",
    max_results: int = 10,
) -> list[dict[str, Any]]:
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
        response = requests.get(EFTS_SEARCH_URL, params=params, headers=HEADERS, timeout=20)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
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

        results.append({
            "entity_name": entity_name,
            "file_date": source.get("file_date", ""),
            "file_type": source.get("file_type", ""),
            "file_description": source.get("file_description") or source.get("form", ""),
            "file_url": file_url,
            "display_names": display_names,
            "adsh": adsh,
        })

    return results


def fetch_filing_text(file_url: str) -> str | None:
    if not file_url:
        return None
    try:
        import html as html_mod
        response = requests.get(file_url, headers=TEXT_HEADERS, timeout=30)
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
    except Exception:
        return None


def download_and_ingest(
    file_url: str,
    entity_name: str,
    file_date: str,
    file_description: str = "",
) -> dict[str, Any]:
    EDGAR_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    text = fetch_filing_text(file_url)
    if not text:
        return {"status": "skipped", "reason": "no_text_extracted", "url": file_url}

    safe_name = _sanitize_filename(f"{entity_name}_{file_date}_{file_description or 'merger_agreement'}")
    file_path = EDGAR_DOWNLOAD_DIR / f"{safe_name}.txt"
    file_path.write_text(text, encoding="utf-8")

    result = get_db().upsert_document(file_path)
    result["edgar_url"] = file_url
    result["entity_name"] = entity_name
    return result


def search_and_ingest(
    query: str = '"agreement and plan of merger"',
    max_filings: int = 5,
    start_date: str = "2022-01-01",
    end_date: str = "2025-12-31",
) -> dict[str, Any]:
    filings = search_edgar_filings(
        query=query,
        forms="8-K,8-K/A",
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
        )
        ingested.append(result)
        time.sleep(0.15)

    return {
        "status": "complete",
        "filings_found": len(filings),
        "ingested": ingested,
        "corpus_status": get_db().stats(),
    }
