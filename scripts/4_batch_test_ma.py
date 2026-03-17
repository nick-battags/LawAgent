"""Batch-run M&A diligence queries and optionally score faithfulness."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ma_agent_core import AgentConfig, MAAgent
from ma_eval_core import evaluate_ma_faithfulness

DEFAULT_QUERIES_FILE = Path("tests/ma_queries.json")
DEFAULT_OUTPUT_DIR = Path("outputs")


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


def load_queries(queries_file: Path) -> list[dict[str, str]]:
    if not queries_file.exists():
        raise FileNotFoundError(f"Queries file not found: {queries_file.resolve()}")

    raw = json.loads(queries_file.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Queries file must be a JSON array.")

    queries = []
    for idx, item in enumerate(raw, start=1):
        if isinstance(item, str):
            queries.append({"id": f"q{idx}", "query": item})
            continue

        if isinstance(item, dict) and "query" in item:
            query_id = str(item.get("id", f"q{idx}"))
            query_text = str(item["query"]).strip()
            if query_text:
                queries.append({"id": query_id, "query": query_text})
            continue

        raise ValueError(f"Invalid query item at index {idx - 1}: {item!r}")

    if not queries:
        raise ValueError("No valid queries found in queries file.")
    return queries


def default_output_file(output_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return output_dir / f"batch_results_{timestamp}.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch-run M&A due-diligence queries.")
    parser.add_argument("--queries-file", type=Path, default=DEFAULT_QUERIES_FILE)
    parser.add_argument("--output-file", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--skip-eval", action="store_true")
    parser.add_argument("--eval-model", default="qwen2.5:7b")
    parser.add_argument("--chroma-dir", type=Path, default=Path("chroma_db"))
    parser.add_argument("--collection", default="ma_test")
    parser.add_argument("--embed-model", default="nomic-embed-text")
    parser.add_argument("--llm-model", default="qwen2.5:7b")
    parser.add_argument("--k", type=int, default=4)
    parser.add_argument("--max-rewrites", type=int, default=2)
    parser.add_argument("--filter-source", default=None)
    parser.add_argument("--filter-document-type", default=None)
    parser.add_argument("--filter-jurisdiction", default=None)
    parser.add_argument("--filter-practice-area", default=None)
    parser.add_argument("--filter-clause-type", default=None)
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args()


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    scored = [r for r in results if r.get("faithfulness") is not None]
    passed = [r for r in scored if r["faithfulness"]["score"] == 5]
    flagged = [r for r in scored if r["faithfulness"]["score"] == 1]
    return {
        "total_queries": total,
        "evaluated_queries": len(scored),
        "faithful_5": len(passed),
        "flagged_1": len(flagged),
    }


def main() -> int:
    args = parse_args()
    queries = load_queries(args.queries_file)
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

    run_results = []
    for idx, item in enumerate(queries, start=1):
        query_id = item["id"]
        query = item["query"]
        print(f"\n[{idx}/{len(queries)}] {query_id}: {query}")
        result = agent.run(query)

        faithfulness = None
        if not args.skip_eval:
            context = result.get("context", "")
            if context.strip():
                faithfulness = evaluate_ma_faithfulness(
                    query=query,
                    context=context,
                    answer=result["answer"],
                    model=args.eval_model,
                    verbose=False,
                )
            else:
                faithfulness = {
                    "score": 1,
                    "reasoning": "No retrieved context available for faithfulness check.",
                }

        run_results.append(
            {
                "id": query_id,
                "query": query,
                "final_question": result["final_question"],
                "answer": result["answer"],
                "rewrites": result["rewrites"],
                "rewrite_history": result["rewrite_history"],
                "documents": result["documents"],
                "faithfulness": faithfulness,
            }
        )

    summary = summarize(run_results)
    payload = {
        "queries_file": str(args.queries_file),
        "config": {
            "chroma_dir": str(args.chroma_dir),
            "collection": args.collection,
            "embed_model": args.embed_model,
            "llm_model": args.llm_model,
            "k": args.k,
            "max_rewrites": args.max_rewrites,
            "eval_model": args.eval_model,
            "skip_eval": args.skip_eval,
            "filters": filters or {},
        },
        "summary": summary,
        "results": run_results,
    }

    output_file = args.output_file
    if output_file is None:
        output_file = default_output_file(args.output_dir)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print("\n" + "=" * 60)
    print("BATCH SUMMARY")
    print("=" * 60)
    print(json.dumps(summary, indent=2))
    print(f"\nSaved: {output_file.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
