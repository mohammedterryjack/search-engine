from __future__ import annotations

import re
from collections import Counter

from simplemma import lemmatize


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


def normalize_token(token: str) -> str:
    lemma = lemmatize(token.lower(), lang="en")
    return lemma.lower().strip()


def normalized_terms(text: str) -> list[str]:
    normalized: list[str] = []
    for token in tokenize(text):
        token = normalize_token(token)
        if token and token not in STOP_WORDS:
            normalized.append(token)
    return normalized


def term_frequencies(text: str) -> Counter[str]:
    return Counter(normalized_terms(text))
