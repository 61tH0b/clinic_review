"""Phrase matching on normalized tokens.

Text is lowercased, "?" becomes the word "query" (so "?DM" reads as uncertain), and every
run of other non-alphanumeric characters becomes a space. Phrases match whole tokens
only, so "total hysterectomy" never matches inside "subtotal hysterectomy" and "dm" never
matches inside "admission".
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize(text: str) -> str:
    text = text.lower().replace("?", " query ")
    return " ".join(_NON_ALNUM.sub(" ", text).split())


def tokens(text: str) -> tuple[str, ...]:
    return tuple(normalize(text).split())


def find(haystack: tuple[str, ...], phrase: tuple[str, ...]) -> list[int]:
    """Start index of every whole-token occurrence of phrase in haystack."""
    n = len(phrase)
    return [i for i in range(len(haystack) - n + 1) if haystack[i : i + n] == phrase]


def contains(haystack: tuple[str, ...], phrase: tuple[str, ...]) -> bool:
    return bool(find(haystack, phrase))


@dataclass(frozen=True)
class Span:
    concept: str
    start: int
    end: int  # exclusive
    phrase: tuple[str, ...]

    @property
    def length(self) -> int:
        return self.end - self.start

    def inside(self, other: "Span") -> bool:
        """Strictly shorter and within other's span: "smoker" inside "ex smoker"."""
        return other.start <= self.start and self.end <= other.end and other.length > self.length
