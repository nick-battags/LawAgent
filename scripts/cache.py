"""Postgres-backed query cache for /api/v2/analyze.

cache_key = sha256(query + posture + contract_hash)
TTL defaults to CACHE_TTL_MINUTES (default 60).

Usage:
    cache = QueryCache(db_url)
    hit = cache.get(key)
    if hit:
        return hit, True   # X-Cache: hit
    result = ... # run pipeline
    cache.set(key, result)
    return result, False

Env vars:
  DATABASE_URL       — Neon connection string
  CACHE_TTL_MINUTES  — default 60
  CACHE_ENABLED      — default true
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


def make_cache_key(query: str, posture: str = "", contract_text: str = "") -> str:
    """Stable cache key for a given (query, posture, contract) triple."""
    contract_hash = hashlib.sha256(contract_text.encode()).hexdigest()[:16] if contract_text else ""
    raw = f"{query.strip().lower()}|{posture}|{contract_hash}"
    return hashlib.sha256(raw.encode()).hexdigest()


class QueryCache:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or os.environ.get("DATABASE_URL", "")
        self.ttl_minutes = int(os.environ.get("CACHE_TTL_MINUTES", "60"))
        self.enabled = os.environ.get("CACHE_ENABLED", "true").lower() not in ("false", "0", "no")

    def get(self, cache_key: str) -> dict[str, Any] | None:
        if not self.enabled or not self.database_url:
            return None
        try:
            import psycopg
            with psycopg.connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE query_cache
                        SET hits = hits + 1
                        WHERE cache_key = %s AND expires_at > NOW()
                        RETURNING response
                        """,
                        (cache_key,),
                    )
                    row = cur.fetchone()
                    conn.commit()
            if row:
                return row[0]
            return None
        except Exception as exc:
            logger.warning("Cache GET failed (key=%s): %s", cache_key[:12], exc)
            return None

    def set(self, cache_key: str, response: dict[str, Any]) -> None:
        if not self.enabled or not self.database_url:
            return
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=self.ttl_minutes)
        try:
            import psycopg
            with psycopg.connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO query_cache (cache_key, response, expires_at)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (cache_key) DO UPDATE
                        SET response = EXCLUDED.response,
                            expires_at = EXCLUDED.expires_at,
                            hits = 0
                        """,
                        (cache_key, json.dumps(response), expires_at),
                    )
                    conn.commit()
        except Exception as exc:
            logger.warning("Cache SET failed (key=%s): %s", cache_key[:12], exc)

    def purge_expired(self) -> int:
        if not self.database_url:
            return 0
        try:
            import psycopg
            with psycopg.connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM query_cache WHERE expires_at <= NOW()")
                    deleted = cur.rowcount
                    conn.commit()
            return deleted
        except Exception as exc:
            logger.warning("Cache purge failed: %s", exc)
            return 0


_cache: QueryCache | None = None


def get_cache() -> QueryCache:
    global _cache
    if _cache is None:
        _cache = QueryCache()
    return _cache
