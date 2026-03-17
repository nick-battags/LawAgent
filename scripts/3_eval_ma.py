"""Evaluate answer faithfulness against provided contract excerpts."""

from __future__ import annotations

import argparse
from pathlib import Path

from ma_eval_core import evaluate_ma_faithfulness

DEFAULT_MODEL = "qwen2.5:7b"
DEFAULT_QUERY = "What is the indemnification cap?"
DEFAULT_CONTEXT = (
    "Section 5. Indemnification. The Seller shall indemnify the Buyer for losses up to $10 million."
)
DEFAULT_ANSWER = "The indemnification cap is $10 million."


def load_text(value: str | None, file_path: Path | None, fallback: str) -> str:
    if file_path:
        return file_path.read_text(encoding="utf-8")
    if value:
        return value
    return fallback

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate faithfulness of an M&A answer.")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--query", default=None)
    parser.add_argument("--context", default=None)
    parser.add_argument("--answer", default=None)
    parser.add_argument("--context-file", type=Path, default=None)
    parser.add_argument("--answer-file", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    query = load_text(args.query, None, DEFAULT_QUERY)
    context = load_text(args.context, args.context_file, DEFAULT_CONTEXT)
    answer = load_text(args.answer, args.answer_file, DEFAULT_ANSWER)
    evaluate_ma_faithfulness(
        query=query,
        context=context,
        answer=answer,
        model=args.model,
        verbose=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
