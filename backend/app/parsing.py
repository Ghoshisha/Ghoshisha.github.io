"""Reading the roster and marks spreadsheets (spec §4.2, §4.3; Appendix A.8, A.9).

Header matching is fuzzy, then *validated by value* -- the column headed ``Roll`` in the
real working sheet contains names for every row, so trusting the header alone reproduces
the swap that named the old workflow's output files after students.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Iterable, Sequence

import openpyxl

from .models import ClassInfo
from .normalize import (
    is_numeric_id,
    looks_like_header_label,
    normalize,
    normalize_roll,
)

Row = Sequence[object]

#: How much of a column must look like a roll number before we believe the header.
_SWAP_CONFIDENCE = 0.6


class SpreadsheetError(ValueError):
    """A file we cannot read at all -- distinct from a per-row data problem."""


@dataclass
class Issue:
    roll: str = ""
    name: str = ""
    level: str = "error"  # "error" | "warning"
    message: str = ""

    def as_dict(self) -> dict:
        return {
            "roll": self.roll,
            "name": self.name,
            "level": self.level,
            "message": self.message,
        }


@dataclass
class RosterEntry:
    roll: str  # normalized -- the join key
    raw_roll: str  # as typed, for display
    name: str


@dataclass
class ParsedRoster:
    students: list[RosterEntry] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)

    def by_roll(self) -> dict[str, RosterEntry]:
        return {s.roll: s for s in self.students}


@dataclass
class ParsedMarks:
    #: normalized roll -> {qno: raw cell value}
    scores: dict[str, dict[str, object]] = field(default_factory=dict)
    #: normalized roll -> roll as typed
    raw_rolls: dict[str, str] = field(default_factory=dict)
    #: question numbers from ClassInfo that had no column in the file
    unmatched_questions: list[str] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)


def read_rows(data: bytes, filename: str) -> list[Row]:
    """Read an .xlsx or .csv upload into raw rows.

    openpyxl cannot read the legacy .xls format, so that is rejected with a message the
    teacher can act on rather than a stack trace.
    """
    lowered = filename.lower()
    if lowered.endswith(".xls"):
        raise SpreadsheetError(
            f"{filename}: the old .xls format is not supported. Open it and use "
            f"'Save As' to produce an .xlsx or .csv file."
        )
    if lowered.endswith(".csv"):
        text = data.decode("utf-8-sig", errors="replace")
        return [tuple(row) for row in csv.reader(io.StringIO(text))]
    if not lowered.endswith((".xlsx", ".xlsm")):
        raise SpreadsheetError(
            f"{filename}: expected a .xlsx or .csv file, got '{filename.rsplit('.', 1)[-1]}'."
        )
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    except Exception as exc:  # openpyxl raises a wide variety of low-level errors
        raise SpreadsheetError(f"{filename}: could not be opened as a spreadsheet ({exc}).")
    try:
        return _select_sheet_rows(workbook)
    finally:
        workbook.close()


def _select_sheet_rows(workbook) -> list[Row]:
    """Pick the sheet that actually holds the data, not simply the first one.

    The real working file leads with a 'Form Responses 1' sheet and keeps the marks on
    'Sheet1', so worksheet 0 is the wrong guess. Choose the first sheet whose header row
    names both a roll and a name column; fall back to the first non-empty sheet.
    """
    first_non_empty: list[Row] | None = None
    for sheet in workbook.worksheets:
        rows = [row for row in sheet.iter_rows(values_only=True)]
        if not any(any(v not in (None, "") for v in row) for row in rows):
            continue
        if first_non_empty is None:
            first_non_empty = rows
        if find_header_row(rows, {"roll", "name"}) is not None:
            return rows
    return first_non_empty or []


def find_header_row(rows: Iterable[Row], required: set[str], scan: int = 10) -> int | None:
    """Locate the header by content rather than assuming row 1 (spec §4.4).

    Returns the index of the first row containing at least two of the required
    normalized labels, or ``None`` if no row in the scan window qualifies.
    """
    for index, row in enumerate(list(rows)[:scan]):
        labels = {normalize(cell) for cell in row if cell not in (None, "")}
        if len(labels & required) >= 2:
            return index
    return None


def _column_containing(header: Row, token: str) -> int | None:
    """First column whose normalized header contains ``token`` (spec §4.2)."""
    for index, cell in enumerate(header):
        if token in normalize(cell):
            return index
    return None


def _looks_like_roll_column(rows: list[Row], index: int) -> float:
    """Fraction of non-blank cells in a column that look like roll numbers."""
    values = [
        row[index]
        for row in rows
        if index < len(row) and row[index] not in (None, "")
    ]
    if not values:
        return 0.0
    return sum(1 for v in values if is_numeric_id(v)) / len(values)


def resolve_roll_and_name_columns(
    header: Row, data_rows: list[Row]
) -> tuple[int | None, int | None, Issue | None]:
    """Locate the roll and name columns, correcting a swapped pair by value (A.8).

    Returns ``(roll_index, name_index, issue)``. The issue is a warning describing the
    swap when one was detected, so it reaches the manifest instead of passing silently.
    """
    roll_index = _column_containing(header, "roll")
    name_index = _column_containing(header, "name")

    if roll_index is None or name_index is None or roll_index == name_index:
        return roll_index, name_index, None

    roll_looks_right = _looks_like_roll_column(data_rows, roll_index)
    name_looks_right = _looks_like_roll_column(data_rows, name_index)

    # Only swap on clear evidence in both directions: the "roll" column is mostly not
    # numeric AND the "name" column mostly is. A roster with alphanumeric roll numbers
    # fails the first test but also fails the second, so it is left alone.
    if roll_looks_right < (1 - _SWAP_CONFIDENCE) and name_looks_right >= _SWAP_CONFIDENCE:
        return (
            name_index,
            roll_index,
            Issue(
                level="warning",
                message=(
                    "The 'Roll' and 'Name' columns are swapped in this file "
                    "(the 'Roll' column holds names). Reading them the right way "
                    "round; fix the spreadsheet to silence this warning."
                ),
            ),
        )
    return roll_index, name_index, None


def parse_roster(data: bytes, filename: str = "roster.xlsx") -> ParsedRoster:
    """Read the student roster: roll + name (spec §4.2)."""
    rows = read_rows(data, filename)
    result = ParsedRoster()
    if not rows:
        result.issues.append(Issue(message=f"{filename}: the file is empty."))
        return result

    header_index = find_header_row(rows, {"roll", "name"}) or 0
    header = rows[header_index]
    body = [r for r in rows[header_index + 1 :] if any(v not in (None, "") for v in r)]

    roll_index, name_index, swap_issue = resolve_roll_and_name_columns(header, body)
    if swap_issue:
        swap_issue.message = f"{filename}: {swap_issue.message}"
        result.issues.append(swap_issue)
    if roll_index is None:
        result.issues.append(
            Issue(message=f"{filename}: no column header containing 'roll' was found.")
        )
        return result

    seen: dict[str, RosterEntry] = {}
    for row in body:
        raw_roll = row[roll_index] if roll_index < len(row) else None
        raw_name = (
            row[name_index] if name_index is not None and name_index < len(row) else ""
        )
        if looks_like_header_label(raw_roll):
            continue  # a repeated header row inside the data
        roll = normalize_roll(raw_roll)
        if not roll:
            continue
        entry = RosterEntry(
            roll=roll,
            raw_roll=str(raw_roll).strip() if raw_roll is not None else "",
            name=str(raw_name).strip() if raw_name is not None else "",
        )
        if roll in seen:
            result.issues.append(
                Issue(
                    roll=entry.raw_roll,
                    name=entry.name,
                    level="warning",
                    message="Duplicate roll number in the roster; keeping the first row.",
                )
            )
            continue
        seen[roll] = entry
        result.students.append(entry)
    return result


def parse_marks(
    data: bytes, class_info: ClassInfo, filename: str = "marks.xlsx"
) -> ParsedMarks:
    """Read the marks sheet: one column per question, matched fuzzily (spec §4.3).

    Question columns arrive as floats in real files -- the header for question "2" is
    ``2.0`` -- which :func:`app.normalize.normalize` reconciles (Appendix A.9).
    """
    rows = read_rows(data, filename)
    result = ParsedMarks()
    if not rows:
        result.issues.append(Issue(message=f"{filename}: the file is empty."))
        return result

    header_index = find_header_row(rows, {"roll", "name"}) or 0
    header = rows[header_index]
    body = [r for r in rows[header_index + 1 :] if any(v not in (None, "") for v in r)]

    roll_index, _name_index, swap_issue = resolve_roll_and_name_columns(header, body)
    if swap_issue:
        swap_issue.message = f"{filename}: {swap_issue.message}"
        result.issues.append(swap_issue)
    if roll_index is None:
        result.issues.append(
            Issue(message=f"{filename}: no column header containing 'roll' was found.")
        )
        return result

    # Map each configured question to its column. Build the header index once so a
    # duplicated question column resolves consistently (first wins).
    header_keys: dict[str, int] = {}
    for index, cell in enumerate(header):
        key = normalize(cell)
        if key and key not in header_keys:
            header_keys[key] = index

    question_columns: dict[str, int] = {}
    for question in class_info.questions:
        index = header_keys.get(normalize(question.qno))
        if index is None:
            result.unmatched_questions.append(question.qno)
        else:
            question_columns[question.qno] = index

    if result.unmatched_questions:
        result.issues.append(
            Issue(
                level="warning",
                message=(
                    f"{filename}: no column found for question(s) "
                    f"{', '.join(result.unmatched_questions)}. Those will be blank on "
                    f"every top sheet."
                ),
            )
        )

    for row in body:
        raw_roll = row[roll_index] if roll_index < len(row) else None
        if looks_like_header_label(raw_roll):
            continue
        roll = normalize_roll(raw_roll)
        if not roll:
            continue
        if roll in result.scores:
            result.issues.append(
                Issue(
                    roll=str(raw_roll).strip(),
                    level="warning",
                    message="Duplicate roll number in the marks sheet; keeping the first row.",
                )
            )
            continue
        result.raw_rolls[roll] = str(raw_roll).strip() if raw_roll is not None else ""
        result.scores[roll] = {
            qno: (row[index] if index < len(row) else None)
            for qno, index in question_columns.items()
        }
    return result
