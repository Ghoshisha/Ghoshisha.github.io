"""The single source of truth for text normalization.

Spec §9.1 and Appendix A.9. Roll number is the only join key between the roster, the
marks sheet and the signature workbook, and it arrives dirty from all three. Question
numbers are equally dirty as spreadsheet *headers*. If two modules normalize even
slightly differently, students silently fail to match and get no PDF.

Every comparison site in this codebase imports from here. Do not write a local variant.
"""

from __future__ import annotations

import re
from datetime import date, datetime

_NON_ALNUM = re.compile(r"[^a-z0-9]")

# Header labels that appear as *data* in the signature workbook: the headerless sheets
# (BCASIMT, BCA2025-2028) carry a stray header row in the middle of their rows.
# Appendix A.7.
HEADER_LABEL_TOKENS = frozenset(
    {
        "fullname",
        "universityrollnumber",
        "rollnumber",
        "roll",
        "name",
        "semester",
        "department",
        "signaturedrivelink",
        "timestamp",
    }
)


def _to_text(value: object) -> str:
    """Render a spreadsheet cell as text without introducing a float artifact.

    openpyxl hands back numbers as floats, so the header ``2`` arrives as ``2.0`` and
    the roll ``25300122014`` as ``25300122014.0``. ``str(2.0)`` would give ``"2.0"``,
    which the trailing-suffix strip below then repairs -- but a large float printed in
    scientific notation would not survive that, so integral floats are formatted as
    integers up front.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):  # NaN / inf
            return ""
        if value.is_integer():
            return str(int(value))
        return repr(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def strip_float_suffix(text: str) -> str:
    """Drop a trailing ``.0`` or bare ``.`` left behind by spreadsheet round-tripping.

    Real values this repairs: ``"25300122014.0"``, ``"25300124010."``, header ``"2.0"``.
    Runs on headers as well as values -- Appendix A.9. Without it, ``normalize("2.0")``
    would be ``"20"`` and every five-mark score would go missing.
    """
    text = text.strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text.rstrip(".")


def normalize(value: object) -> str:
    """Case-, space- and punctuation-insensitive key for headers and values alike.

    ``normalize("1.a") == normalize("1a") == normalize(" 1 A ")``
    ``normalize("2") == normalize("2.0") == normalize(2.0)``
    """
    return _NON_ALNUM.sub("", strip_float_suffix(_to_text(value)).lower())


def normalize_roll(value: object) -> str:
    """Normalize a roll number. Identical rules to :func:`normalize`.

    Kept as a distinct name because call sites read better, and because roll matching is
    the failure mode §9.1 warns about -- an explicit name makes a stray local
    reimplementation easier to spot in review.
    """
    return normalize(value)


def looks_like_header_label(value: object) -> bool:
    """True if a cell is really a column heading that leaked into the data rows."""
    return normalize(value) in HEADER_LABEL_TOKENS


def is_numeric_id(value: object) -> bool:
    """True if a cell looks like a roll number rather than a person's name.

    Used by the value-based swap detection in :mod:`app.parsing` (Appendix A.8), where
    the column headed ``Roll`` turns out to hold names for every row.
    """
    text = strip_float_suffix(_to_text(value))
    return bool(text) and text.isdigit()


def slugify_name(name: str) -> str:
    """Filename-safe student name: spaces to underscores, other punctuation dropped.

    Spec §6 -- output PDFs are named ``<roll>_<name>.pdf``.
    """
    cleaned = re.sub(r"[^A-Za-z0-9\s-]", "", _to_text(name)).strip()
    slug = re.sub(r"[\s-]+", "_", cleaned)
    return slug or "unnamed"
