from __future__ import annotations

import re
from collections import Counter


TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "with",
}


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text)]


def normalized_terms(text: str) -> list[str]:
    return [token for token in tokenize(text) if token not in STOP_WORDS]


def term_frequencies(text: str) -> Counter[str]:
    return Counter(normalized_terms(text))
