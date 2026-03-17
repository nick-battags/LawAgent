"""CLI entrypoint for the local M&A CRAG agent."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ma_agent_core import AgentConfig, MAAgent

DEFAULT_CHROMA_DIR = Path("chroma_db")
DEFAULT_COLLECTION = "ma_test"
DEFAULT_EMBED_MODEL = "nomic-embed-text"
DEFAULT_LLM_MODEL = "qwen2.5:7b"
DEFAULT_K = 4
DEFAULT_MAX_REWRITES = 2
DEFAULT_QUERY = "What are the change of control provisions in the supply agreement?"


def build_filters(args: argparse.Namespace) -> dict[str, str] | None:
    filters = {}
    if args.filter_source:
        filters["source"] = args.filter_source
    if args.filter_document_type:
        filters["document_type"] = args.filter_document_type
    if args.filter_jurisdiction:
        filters["jurisdiction"] = args.filter_jurisdiction
    if args.filter_practice_area:
        filters["practice_area"] = args.filter_practice_area
    if args.filter_clause_type:
        filters["clause_type"] = args.filter_clause_type
    return filters or None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local M&A CRAG agent.")
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--chroma-dir", type=Path, default=DEFAULT_CHROMA_DIR)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--embed-model", default=DEFAULT_EMBED_MODEL)
    parser.add_argument("--llm-model", default=DEFAULT_LLM_MODEL)
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument("--max-rewrites", type=int, default=DEFAULT_MAX_REWRITES)
    parser.add_argument("--filter-source", default=None)
    parser.add_argument("--filter-document-type", default=None)
    parser.add_argument("--filter-jurisdiction", default=None)
    parser.add_argument("--filter-practice-area", default=None)
    parser.add_argument("--filter-clause-type", default=None)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=None,
        help="Optional path to persist the full run result as JSON.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Reduce node-level console logging.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    filters = build_filters(args)

    config = AgentConfig(
        chroma_dir=args.chroma_dir,
        collection=args.collection,
        embed_model=args.embed_model,
        llm_model=args.llm_model,
        k=args.k,
        max_rewrites=args.max_rewrites,
        filters=filters,
    )

    try:
        agent = MAAgent(config=config, verbose=not args.quiet)
    except (FileNotFoundError, ValueError) as exc:
        print(exc)
        return 1

    print(f"\nQuery: {args.query}\n")
    if filters:
        print(f"Active metadata filters: {json.dumps(filters)}")
    result = agent.run(args.query)

    print("\n" + "=" * 60)
    print("FINAL ANSWER")
    print("=" * 60)
    print(result["answer"] or "No answer generated.")

    if result["documents"]:
        print("\nSOURCES")
        print("=" * 60)
        for idx, doc in enumerate(result["documents"], start=1):
            print(f"{idx}. {doc['source']} (page={doc['page']})")

    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"\nSaved JSON result to: {args.json_output.resolve()}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
