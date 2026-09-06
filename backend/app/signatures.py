"""Reading the Google Form signature export (spec §4.4; Appendix A.7).

The file is a real form-response export, not a clean roster: 16 sheets, ~1800 rows for
~760 students, headers that are sometimes absent, header rows that leak into the data,
roll numbers stored three different ways, and students who submitted up to ten times.

The job here is to reduce all of that to one Drive link per roll number, deterministically.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import datetime

import openpyxl

from .normalize import looks_like_header_label, normalize, normalize_roll
from .parsing import Issue, SpreadsheetError

#: Header labels that identify the real header row (spec §4.4).
_HEADER_TOKENS = {"fullname", "universityrollnumber", "signaturedrivelink"}

#: Fixed positions used when a sheet has no header at all: name=B, roll=C, link=F.
_FALLBACK_NAME_COL = 1
_FALLBACK_ROLL_COL = 2
_FALLBACK_LINK_COL = 5

#: The catch-all dump sheet. Loses an exact-timestamp tie to a per-department sheet
#: (Appendix A.7) -- those look hand-curated.
_CATCH_ALL_SHEET = "sheet1"

_DRIVE_ID = re.compile(r"(?:id=|/d/)([a-zA-Z0-9_-]+)")


def extract_drive_id(link: object) -> str | None:
    """Pull the file ID out of a Drive link.

    Accepts both shapes that occur in the file: ``/file/d/<ID>/view`` and ``open?id=<ID>``.
    This is the same regex the teacher's own SignURL formula used.
    """
    if link in (None, ""):
        return None
    match = _DRIVE_ID.search(str(link))
    return match.group(1) if match else None


@dataclass
class SignatureRow:
    roll: str  # normalized -- the join key
    raw_roll: str
    name: str
    link: str
    drive_id: str | None
    timestamp: datetime | None
    sheet: str

    @property
    def is_catch_all(self) -> bool:
        return self.sheet.strip().lower() == _CATCH_ALL_SHEET


@dataclass
class ParsedSignatures:
    #: normalized roll -> the winning submission
    by_roll: dict[str, SignatureRow] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)
    rows_read: int = 0
    sheets_read: int = 0

    def get(self, roll: str) -> SignatureRow | None:
        return self.by_roll.get(normalize_roll(roll))


def _coerce_timestamp(value: object) -> datetime | None:
    """Column A is a form timestamp, but 14 rows have none (Appendix A.7)."""
    if isinstance(value, datetime):
        return value
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M:%S",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _locate_columns(rows: list[tuple], scan: int = 10) -> tuple[int, int, int, int]:
    """Find the header row and the name/roll/link columns.

    Returns ``(first_data_row, name_col, roll_col, link_col)``. Falls back to the fixed
    positions when no header is present -- the layout is consistent even on the sheets
    that lack one (spec §4.4).
    """
    for index, row in enumerate(rows[:scan]):
        labels = {normalize(cell): position for position, cell in enumerate(row) if cell}
        if len(set(labels) & _HEADER_TOKENS) >= 2:
            return (
                index + 1,
                labels.get("fullname", _FALLBACK_NAME_COL),
                labels.get("universityrollnumber", _FALLBACK_ROLL_COL),
                labels.get("signaturedrivelink", _FALLBACK_LINK_COL),
            )
    return 0, _FALLBACK_NAME_COL, _FALLBACK_ROLL_COL, _FALLBACK_LINK_COL


def _beats(candidate: SignatureRow, incumbent: SignatureRow) -> bool:
    """Is ``candidate`` the submission we should keep? (spec §4.4; Appendix A.7)

    Latest timestamp wins. A row with no timestamp is older than any timestamped row.
    On an exact tie a per-department sheet beats the catch-all ``Sheet1``.
    """
    if candidate.timestamp != incumbent.timestamp:
        if incumbent.timestamp is None:
            return True
        if candidate.timestamp is None:
            return False
        return candidate.timestamp > incumbent.timestamp
    # Exact tie.
    return incumbent.is_catch_all and not candidate.is_catch_all


def parse_signature_workbook(
    data: bytes, filename: str = "Signature.xlsx"
) -> ParsedSignatures:
    """Read every sheet and reduce to one signature per roll number."""
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    except Exception as exc:
        raise SpreadsheetError(
            f"{filename}: could not be opened as a spreadsheet ({exc})."
        )

    result = ParsedSignatures()
    # Rows that tied on timestamp with a different Drive link. Both sides are kept
    # because which one wins is decided later -- reporting only the candidate would
    # compare the winner against itself and drop the warning.
    conflicting_ties: dict[str, list[SignatureRow]] = {}

    try:
        for sheet in workbook.worksheets:
            rows = [row for row in sheet.iter_rows(values_only=True)]
            if not rows:
                continue
            result.sheets_read += 1
            start, name_col, roll_col, link_col = _locate_columns(rows)

            for row in rows[start:]:
                if not any(value not in (None, "") for value in row):
                    continue

                raw_roll = row[roll_col] if roll_col < len(row) else None
                # Header rows leak into the data on the headerless sheets (A.7).
                if looks_like_header_label(raw_roll):
                    continue
                roll = normalize_roll(raw_roll)
                if not roll:
                    continue

                link = row[link_col] if link_col < len(row) else None
                name = row[name_col] if name_col < len(row) else None
                candidate = SignatureRow(
                    roll=roll,
                    raw_roll=str(raw_roll).strip(),
                    name=str(name).strip() if name not in (None, "") else "",
                    link=str(link).strip() if link not in (None, "") else "",
                    drive_id=extract_drive_id(link),
                    timestamp=_coerce_timestamp(row[0] if row else None),
                    sheet=sheet.title,
                )
                result.rows_read += 1

                incumbent = result.by_roll.get(roll)
                if incumbent is None:
                    result.by_roll[roll] = candidate
                    continue

                # An exact-timestamp tie between rows pointing at *different* files is
                # a genuine ambiguity -- resolve it deterministically but say so.
                if (
                    candidate.timestamp == incumbent.timestamp
                    and candidate.drive_id != incumbent.drive_id
                    and candidate.drive_id
                    and incumbent.drive_id
                ):
                    conflicting_ties.setdefault(roll, []).extend([incumbent, candidate])

                if _beats(candidate, incumbent):
                    result.by_roll[roll] = candidate
    finally:
        workbook.close()

    for roll, tied in conflicting_ties.items():
        winner = result.by_roll[roll]
        # A tie only matters if it actually decided the outcome: when a later
        # submission exists, it wins outright and the tie is irrelevant.
        losers = [
            row
            for row in tied
            if row.timestamp == winner.timestamp and row.drive_id != winner.drive_id
        ]
        if not losers:
            continue
        rejected = ", ".join(sorted({f"'{row.sheet}'" for row in losers}))
        when = (
            f"timestamp {winner.timestamp:%Y-%m-%d %H:%M:%S}"
            if winner.timestamp
            else "no timestamp"
        )
        result.issues.append(
            Issue(
                roll=winner.raw_roll,
                name=winner.name,
                level="warning",
                message=(
                    f"{len(losers) + 1} signature submissions share {when} but point at "
                    f"different Drive files. Used the one from '{winner.sheet}' "
                    f"(also found in {rejected})."
                ),
            )
        )

    for roll, row in result.by_roll.items():
        if not row.drive_id:
            result.issues.append(
                Issue(
                    roll=row.raw_roll,
                    name=row.name,
                    level="warning",
                    message=(
                        "Signature row has no usable Google Drive link."
                        if not row.link
                        else f"Signature link is not a Drive file link: {row.link!r}"
                    ),
                )
            )
    return result
