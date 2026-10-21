"""Shared normalized verbatim coverage contract for novel generation and books."""

from __future__ import annotations

import re
import unicodedata


def normalize_for_coverage(text: str) -> str:
    """Normalize Unicode NFC and whitespace without deleting internal word separators."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def covers_source_verbatim(parts: list[str], source: str) -> bool:
    """Require ordered full coverage, permitting one normalized space between trimmed parts."""
    cursor = 0
    for index, part in enumerate(parts):
        if index and source.startswith(" ", cursor):
            cursor += 1
        if not source.startswith(part, cursor):
            return False
        cursor += len(part)
    return cursor == len(source)
