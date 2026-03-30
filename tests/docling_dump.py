#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from app.services.ingest import build_docling_converter, extract_structured_units


def print_items(document: object, *, max_items: int = 100) -> None:
    iterate_items = getattr(document, "iterate_items", None)
    if not callable(iterate_items):
        print("Document does not expose `iterate_items`.")
        return
    for index, (item, level) in enumerate(
        iterate_items(root=getattr(document, "body", None), with_groups=True, traverse_pictures=True)
    ):
        if index >= max_items:
            break
        label = getattr(getattr(item, "label", None), "value", getattr(item, "label", None))
        text = getattr(item, "text", None)
        if not isinstance(text, str):
            text = getattr(item, "orig", None)
        snippet = (text or "").strip().splitlines()
        snippet = snippet[0] if snippet else ""
        print(f"{index + 1:>3}. level={level} label={label} snippet={snippet[:80]}")


def dump_units(units: Sequence[object], *, max_units: int, show_all: bool) -> None:
    limit = len(units) if show_all else min(len(units), max_units)
    for index in range(limit):
        unit = units[index]
        print(f"\n[{index + 1}] {unit.unit_type} | page {unit.page_number} | {unit.section_name}")
        print(f"Anchor: {unit.anchor_key}")
        print(f"Caption: {unit.caption or '<none>'}")
        print(f"Tokens: {unit.token_count if hasattr(unit, 'token_count') else 'n/a'}")
        snippet = str(unit.display_text).replace("\n", " ").strip()
        print(f"Text: {snippet[:400]}")
    if not show_all and len(units) > max_units:
        print(f"\n... {len(units) - max_units} more units omitted ...")


def main() -> None:
    parser = argparse.ArgumentParser(description="Dump Docling output for a document.")
    parser.add_argument("source", type=Path, help="Path to the document to inspect.")
    parser.add_argument("--max-units", type=int, default=20, help="How many parsed units to print.")
    parser.add_argument(
        "--show-all-units",
        action="store_true",
        help="Show every parsed unit instead of truncating to --max-units.",
    )
    parser.add_argument(
        "--show-items",
        action="store_true",
        help="Print the first items that Docling emits via `iterate_items`.",
    )
    args = parser.parse_args()

    source_path = args.source.expanduser()
    if not source_path.exists():
        raise SystemExit(f"Document not found: {source_path}")
    converter = build_docling_converter()
    result = converter.convert(str(source_path))
    document = getattr(result, "document", None)
    if document is None:
        raise SystemExit("Docling did not produce a document object.")

    print(f"Converted document: {source_path}")
    print(f"Document repr: {document}")
    if args.show_items:
        print("\n=== Raw Docling items ===")
        print_items(document, max_items=100)

    units = extract_structured_units(document)
    print(f"\nParsed units: {len(units)} (Docling structured output only)")
    dump_units(units, max_units=args.max_units, show_all=args.show_all_units)


if __name__ == "__main__":
    main()
