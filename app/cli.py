from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from app.db.global_store import GlobalStore
from app.main import ensure_runtime_dirs
from app.services.search import search_all_sources


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="searchi", description="Query the local SearChi index.")
    parser.add_argument("query", help="Search query text.")
    parser.add_argument("--json", action="store_true", dest="json_mode", help="Emit JSON output.")
    parser.add_argument(
        "--source-id",
        action="append",
        type=int,
        default=[],
        help="Restrict search to a specific source root id. May be repeated.",
    )
    parser.add_argument(
        "--unit-type",
        action="append",
        choices=["section", "figure", "table"],
        default=[],
        help="Restrict search to one or more content unit types. May be repeated.",
    )
    parser.add_argument(
        "--semantic-threshold",
        type=float,
        default=None,
        help="Minimum semantic similarity score for vector candidates.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of results to print.",
    )
    return parser


def render_text_results(results: list[dict[str, object]]) -> str:
    if not results:
        return "No results."
    lines: list[str] = []
    for index, result in enumerate(results, start=1):
        header = f"{index}. {result['section_name'] or result['filename']}"
        meta = f"{result['unit_type']} | page {result['page_number'] or '-'} | score {result['score']:.3f}"
        path = str(result["document_path"])
        snippet = str(result["display_text"]).replace("\n", " ").strip()
        lines.extend([header, meta, path, snippet, ""])
    return "\n".join(lines).rstrip()


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    ensure_runtime_dirs()
    GlobalStore()

    results = search_all_sources(
        args.query,
        set(args.source_id) if args.source_id else None,
        unit_types=set(args.unit_type) if args.unit_type else None,
        vector_min_score=args.semantic_threshold,
    )
    trimmed = [asdict(result) for result in results[: max(args.limit, 0)]]

    if args.json_mode:
        print(json.dumps(trimmed, indent=2))
        return
    print(render_text_results(trimmed))


if __name__ == "__main__":
    main()
