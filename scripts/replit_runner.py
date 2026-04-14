"""Replit console runner for the LawAgent command-line project."""

from __future__ import annotations

import signal
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"


def validate_environment() -> list[str]:
    sys.path.insert(0, str(SCRIPTS_DIR))

    import ma_agent_core
    import ma_eval_core

    checks = [
        f"Loaded {ma_agent_core.__name__}",
        f"Loaded {ma_eval_core.__name__}",
        f"Data directory: {(ROOT / 'data').resolve()}",
        f"Vector database directory: {(ROOT / 'chroma_db').resolve()}",
    ]

    if not any((ROOT / "chroma_db").iterdir()):
        checks.append("Vector database is empty. Run: python scripts/1_ingest_ma.py")

    return checks


def main() -> int:
    stopping = False

    def stop(_signum, _frame) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    print("LawAgent Replit runner starting...", flush=True)
    print("This is a CLI-based local RAG project that uses Ollama models.", flush=True)

    try:
        for check in validate_environment():
            print(f"OK: {check}", flush=True)
    except Exception as exc:
        print(f"Startup validation failed: {exc}", flush=True)
        return 1

    print("", flush=True)
    print("Useful commands:", flush=True)
    print("  python scripts/1_ingest_ma.py", flush=True)
    print('  python scripts/2_agent_ma.py --query "What are the assignment restrictions?"', flush=True)
    print("  python scripts/4_batch_test_ma.py --skip-eval", flush=True)
    print("", flush=True)
    print("Runner is idle and ready. Stop the workflow to exit.", flush=True)

    while not stopping:
        time.sleep(5)

    print("LawAgent Replit runner stopped.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())