from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path

from .config import RootConfig
from .index_registry import IndexRegistry
from .models import SearchHit
from .paging import load_page_number

TOKEN_RE = re.compile(r"[A-Za-z0-9]{2,}")
STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "being",
    "but",
    "by",
    "for",
    "from",
    "have",
    "in",
    "into",
    "is",
    "it",
    "its",
    "me",
    "my",
    "our",
    "ours",
    "of",
    "on",
    "or",
    "she",
    "so",
    "that",
    "the",
    "their",
    "theirs",
    "them",
    "there",
    "they",
    "this",
    "to",
    "us",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "whom",
    "why",
    "will",
    "with",
    "would",
    "you",
    "your",
    "yours",
}

IRREGULAR_NORMALIZATIONS = {
    "analyses": "analysis",
    "children": "child",
    "indices": "index",
    "matrices": "matrix",
    "men": "man",
    "mice": "mouse",
    "people": "person",
    "teeth": "tooth",
    "women": "woman",
}


class SearchBackend:
    def __init__(
        self,
        registry: IndexRegistry,
        *,
        roots: list[RootConfig] | None = None,
        snippet_length: int = 240,
    ) -> None:
        self.registry = registry
        self.roots = roots or []
        self.snippet_length = snippet_length

    def bootstrap(self) -> None:
        return

    def search(self, query: str, per_page: int = 100, page: int = 1, *, hydrate: bool = True) -> dict[str, object]:
        terms = tokenize_terms(query)
        if not terms:
            return {"hits": [], "related_terms": [], "total_hits": 0, "page": 1, "per_page": per_page}

        candidate_rows = self.registry.search_documents(terms, self.roots)
        if not candidate_rows:
            return {"hits": [], "related_terms": [], "total_hits": 0, "page": 1, "per_page": per_page}

        total_pages = max(self.registry.page_count(self.roots), 1)
        candidates: dict[tuple[str, int], dict[str, object]] = {}
        for row in candidate_rows:
            path = row["path"]
            page_number = int(row["page_number"])
            relative_path = self._relative_path(Path(str(path)))
            item = candidates.setdefault(
                (str(path), page_number),
                {
                    "content_hash": row["content_hash"],
                    "file_path": path,
                    "relative_path": relative_path,
                    "page_number": page_number,
                    "matched_terms": set(),
                    "score": 0.0,
                },
            )
            term = row["term"]
            item["matched_terms"].add(term)
            doc_freq = max(self.registry.document_frequency(term, self.roots), 1)
            item["score"] += math.log(1.0 + (total_pages / doc_freq))

        ranked = sorted(
            (
                self._boost_candidate(item, set(terms))
                for item in candidates.values()
            ),
            key=lambda item: float(item["score"]),
            reverse=True,
        )
        total_hits = len(ranked)
        current_page = max(page, 1)
        start = (current_page - 1) * per_page
        end = start + per_page
        paged_candidates = ranked[start:end]

        if hydrate:
            hits: list[SearchHit] = []
            for candidate in paged_candidates:
                hits.extend(self._locate_hits(candidate, terms))
            hits.sort(key=lambda hit: hit.score, reverse=True)
            hit_payload = [_to_dict(hit) for hit in hits]
        else:
            hit_payload = [self._candidate_to_dict(candidate) for candidate in paged_candidates]

        return {
            "hits": hit_payload,
            "related_terms": self._related_terms(paged_candidates, set(terms)),
            "total_hits": total_hits,
            "page": current_page,
            "per_page": per_page,
        }

    def _boost_candidate(self, item: dict[str, object], query_terms: set[str]) -> dict[str, object]:
        relative_path = str(item["relative_path"]).casefold()
        file_name = Path(relative_path).name.casefold()
        coverage = len(item["matched_terms"]) / max(len(query_terms), 1)
        exact_file = 10.0 if any(term == file_name for term in query_terms) else 0.0
        path_boost = 4.0 if any(term in relative_path for term in query_terms) else 0.0
        item["score"] = float(item["score"]) + coverage * 6.0 + exact_file + path_boost
        return item

    def _locate_hits(
        self,
        candidate: dict[str, object],
        query_terms: list[str],
    ) -> list[SearchHit]:
        file_path = Path(str(candidate["file_path"]))
        if not file_path.exists():
            return []

        page_number, line_start, line_end, page_text = load_page_number(
            file_path,
            int(candidate["page_number"]),
        )
        page_lines = page_text.splitlines()
        line_matches: list[tuple[int, int, str]] = []
        for offset, line in enumerate(page_lines):
            absolute_line = line_start + offset
            lowered = line.casefold()
            match_count = sum(1 for term in query_terms if term in lowered)
            if match_count == 0:
                continue
            line_matches.append((match_count, absolute_line, line))

        if not line_matches:
            return []
        best_match_count, best_line_number, best_line_text = max(line_matches, key=lambda item: (item[0], -item[1]))
        best_line_offset = best_line_number - line_start
        page_offset = sum(len(line) + 1 for line in page_lines[:best_line_offset])
        best_line_lower = best_line_text.casefold()
        term_positions = [best_line_lower.find(term) for term in query_terms if best_line_lower.find(term) != -1]
        anchor_pos = page_offset + (min(term_positions) if term_positions else 0)
        return [
            SearchHit(
                content_hash=str(candidate["content_hash"]),
                file_path=str(candidate["file_path"]),
                relative_path=str(candidate["relative_path"]),
                page_number=page_number,
                snippet=build_snippet(page_text, query_terms, self.snippet_length, anchor_pos=anchor_pos),
                score=float(candidate["score"]) + best_match_count * 3.0 + max(4.0 - (page_number * 0.2), 0.0),
            )
        ]

    def update_roots(self, roots: list[RootConfig]) -> None:
        self.roots = roots

    def snippet_for_location(self, file_path: str, page_number: int, query_terms: list[str]) -> str:
        file = Path(file_path)
        if not file.exists():
            return ""
        _, line_start, _, page_text = load_page_number(file, page_number)
        page_lines = page_text.splitlines()
        line_matches: list[tuple[int, int, str]] = []
        for offset, line in enumerate(page_lines):
            absolute_line = line_start + offset
            lowered = line.casefold()
            match_count = sum(1 for term in query_terms if term in lowered)
            if match_count == 0:
                continue
            line_matches.append((match_count, absolute_line, line))
        if not line_matches:
            return build_snippet(page_text, query_terms, self.snippet_length)
        _, best_line_number, best_line_text = max(line_matches, key=lambda item: (item[0], -item[1]))
        best_line_offset = best_line_number - line_start
        page_offset = sum(len(line) + 1 for line in page_lines[:best_line_offset])
        best_line_lower = best_line_text.casefold()
        term_positions = [best_line_lower.find(term) for term in query_terms if best_line_lower.find(term) != -1]
        anchor_pos = page_offset + (min(term_positions) if term_positions else 0)
        return build_snippet(page_text, query_terms, self.snippet_length, anchor_pos=anchor_pos)

    def _relative_path(self, path: Path) -> str:
        for root in self.roots:
            base = Path(root.path)
            try:
                return str(path.relative_to(base))
            except ValueError:
                continue
        return path.name

    def _candidate_to_dict(self, candidate: dict[str, object]) -> dict[str, object]:
        return {
            "file_path": str(candidate["file_path"]),
            "relative_path": str(candidate["relative_path"]),
            "page_number": int(candidate["page_number"]),
            "score": float(candidate["score"]),
        }

    def _related_terms(self, candidates: list[dict[str, object]], query_terms: set[str], limit: int = 8) -> list[str]:
        term_scores: Counter[str] = Counter()
        hit_scores = {
            (str(candidate["content_hash"]), int(candidate["page_number"])): max(float(candidate["score"]), 1.0)
            for candidate in candidates[:12]
        }
        for row in self.registry.page_terms(list(hit_scores.keys()), self.roots):
            term = str(row["term"])
            if term in query_terms:
                continue
            page_key = (str(row["content_hash"]), int(row["page_number"]))
            term_scores[term] += hit_scores.get(page_key, 1.0)

        return [term for term, _ in term_scores.most_common(limit)]


def tokenize_terms(text: str) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for match in TOKEN_RE.finditer(text):
        raw_term = match.group(0).casefold()
        if len(raw_term) < 2 or raw_term in STOP_WORDS:
            continue
        term = normalize_term(raw_term)
        if len(term) < 2 or term in STOP_WORDS or term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return terms


def normalize_term(term: str) -> str:
    if term in IRREGULAR_NORMALIZATIONS:
        return IRREGULAR_NORMALIZATIONS[term]

    if len(term) > 4 and term.endswith("ies"):
        return term[:-3] + "y"
    if len(term) > 4 and term.endswith(("ches", "shes", "sses", "xes", "zes")):
        return term[:-2]
    if len(term) > 3 and term.endswith("s") and not term.endswith(("ss", "us", "is")):
        return term[:-1]
    return term


def build_snippet(text: str, query_terms: list[str], snippet_length: int, *, anchor_pos: int | None = None) -> str:
    lowered = text.casefold()
    positions = [lowered.find(term) for term in query_terms if lowered.find(term) != -1]
    match_pos = anchor_pos if anchor_pos is not None else (min(positions) if positions else 0)
    start = max(match_pos - snippet_length // 4, 0)
    end = min(start + snippet_length, len(text))
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    for term in sorted(set(query_terms), key=len, reverse=True):
        snippet = re.sub(rf"(?i)({re.escape(term)})", r"<mark>\1</mark>", snippet)
    return snippet


def _to_dict(hit: SearchHit) -> dict[str, object]:
    return {
        "file_path": hit.file_path,
        "relative_path": hit.relative_path,
        "page_number": hit.page_number,
        "snippet": hit.snippet,
        "score": hit.score,
    }
