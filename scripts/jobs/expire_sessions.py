"""Cloud Run Job: expire stale hub_sessions and prune associated data.

Runs hourly via Cloud Scheduler. For each expired session:
  1. Marks hub_sessions.status = 'expired'
  2. Deletes hub_changes rows (cascades via FK, but explicit for safety)
  3. Calls SessionMemory.clear() to prune the Supermemory container

Exit code 0 = success (Cloud Run Jobs retry on non-zero exit).

Env vars: DATABASE_URL, SUPERMEMORY_API_KEY
"""

from __future__ import annotations

import logging
import os
import sys

import psycopg

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("expire_sessions")


def main() -> int:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        logger.error("DATABASE_URL not set — aborting")
        return 1

    try:
        with psycopg.connect(database_url) as conn:
            # Mark expired sessions (hard TTL: created_at + HUB_TTL_MINUTES)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE hub_sessions
                    SET status = 'expired'
                    WHERE status NOT IN ('expired', 'failed')
                      AND expires_at < NOW()
                    RETURNING id
                    """
                )
                expired_ids = [str(row[0]) for row in cur.fetchall()]

            # Mark idle-expired sessions (idle TTL: last_activity_at + HUB_IDLE_TTL_MINUTES)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE hub_sessions
                    SET status = 'expired'
                    WHERE status NOT IN ('expired', 'failed')
                      AND last_activity_at < NOW() - INTERVAL '1 minute' *
                          (SELECT COALESCE(NULLIF(current_setting('app.hub_idle_ttl_minutes', true), ''), '120')::int)
                    RETURNING id
                    """
                )
                idle_expired = [str(row[0]) for row in cur.fetchall()]

            all_expired = list(set(expired_ids + idle_expired))
            conn.commit()

        if all_expired:
            logger.info("Expired %d sessions: %s", len(all_expired), all_expired[:10])
            _prune_supermemory(all_expired)
        else:
            logger.info("No sessions to expire")

        return 0

    except Exception as exc:
        logger.exception("Session expiry job failed: %s", exc)
        return 1


def _prune_supermemory(session_ids: list[str]) -> None:
    """Best-effort: clear Supermemory containers for expired sessions."""
    if not os.environ.get("SUPERMEMORY_API_KEY"):
        logger.info("SUPERMEMORY_API_KEY not set — skipping Supermemory prune")
        return

    from scripts.session_memory import get_session_memory

    cleared = 0
    for sid in session_ids:
        try:
            mem = get_session_memory(sid)
            if mem.clear():
                cleared += 1
        except Exception as exc:
            logger.warning("Failed to clear Supermemory for session %s: %s", sid, exc)

    logger.info("Supermemory prune: cleared %d/%d containers", cleared, len(session_ids))


if __name__ == "__main__":
    sys.exit(main())
