"""Batch orchestration: spreadsheets in, a ZIP of top sheets out (spec §6).

Kept separate from :mod:`app.main` so the whole pipeline can be tested without HTTP.
Nothing here raises for a single bad student; every problem becomes a manifest entry.
"""

from __future__ import annotations

import asyncio
import json
import zipfile
from dataclasses import dataclass, field
from datetime import date
from io import BytesIO

from .drive_fetch import ImageCache, fetch_signatures
from .models import ClassInfo
from .normalize import normalize_roll
from .parsing import Issue, parse_marks, parse_roster
from .pdf_generator import SignatureAssets, build_pdf, output_filename
from .scoring import StudentResult, score_student
from .signatures import ParsedSignatures, parse_signature_workbook

# Manifest outcome values.
GENERATED = "generated"
SIGNATURE_MISSING = "signature-missing"
SIGNATURE_FAILED = "signature-failed"
NO_MARKS_MATCH = "no-marks-match"


@dataclass
class StudentOutcome:
    roll: str
    name: str
    status: str
    filename: str = ""
    total: float | None = None
    percent: float | None = None
    feedback: str = ""
    signature_source: str = ""
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "roll": self.roll,
            "name": self.name,
            "status": self.status,
            "filename": self.filename,
            "total": self.total,
            "percent": self.percent,
            "feedback": self.feedback,
            "signatureSource": self.signature_source,
            "detail": self.detail,
        }


@dataclass
class BatchResult:
    zip_bytes: bytes = b""
    outcomes: list[StudentOutcome] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)

    @property
    def generated_count(self) -> int:
        return sum(1 for o in self.outcomes if o.status == GENERATED)


def _dedupe(issues: list[Issue]) -> list[Issue]:
    """Drop repeats, keeping the first of each.

    The roster and the marks sheet are often the same workbook, so a file-level
    problem like a swapped Roll/Name column is otherwise reported twice.
    """
    seen: set[tuple[str, str, str]] = set()
    unique: list[Issue] = []
    for issue in issues:
        key = (issue.roll, issue.level, issue.message)
        if key not in seen:
            seen.add(key)
            unique.append(issue)
    return unique


def read_override_zip(data: bytes | None) -> dict[str, bytes]:
    """Read the optional fallback ZIP of signature images named by roll (§4.4 item 7).

    This is the escape hatch for a student whose Drive sharing is broken: whatever is in
    here takes precedence over the Drive fetch for that roll.
    """
    if not data:
        return {}
    images: dict[str, bytes] = {}
    with zipfile.ZipFile(BytesIO(data)) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            stem = info.filename.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            roll = normalize_roll(stem)
            if roll:
                images[roll] = archive.read(info)
    return images


def build_students(
    roster_bytes: bytes,
    marks_bytes: bytes,
    class_info: ClassInfo,
    roster_name: str = "roster.xlsx",
    marks_name: str = "marks.xlsx",
) -> tuple[list[StudentResult], list[Issue]]:
    """Join the roster and marks sheet on roll number and score every student."""
    roster = parse_roster(roster_bytes, roster_name)
    marks = parse_marks(marks_bytes, class_info, marks_name)
    issues = list(roster.issues) + list(marks.issues)

    by_roll = roster.by_roll()
    students: list[StudentResult] = []

    for entry in roster.students:
        scores = marks.scores.get(entry.roll)
        if scores is None:
            issues.append(
                Issue(
                    roll=entry.raw_roll,
                    name=entry.name,
                    level="error",
                    message="No matching row in the marks sheet.",
                )
            )
            continue
        students.append(
            score_student(entry.raw_roll or entry.roll, entry.name, scores, class_info)
        )

    # A student who has marks but is absent from the roster still gets a top sheet --
    # losing them silently would be worse than printing one with a blank name.
    for roll, scores in marks.scores.items():
        if roll in by_roll:
            continue
        raw = marks.raw_rolls.get(roll, roll)
        issues.append(
            Issue(
                roll=raw,
                level="warning",
                message="In the marks sheet but not the roster; the name will be blank.",
            )
        )
        students.append(score_student(raw, "", scores, class_info))

    return students, issues


def resolve_signature_ids(
    students: list[StudentResult],
    signatures: ParsedSignatures | None,
    overrides: dict[str, bytes],
) -> tuple[dict[str, str], list[Issue]]:
    """Work out which Drive files to fetch -- only for students in this batch (§4.4)."""
    wanted: dict[str, str] = {}
    issues: list[Issue] = []
    if signatures is None:
        return wanted, issues

    for student in students:
        roll = normalize_roll(student.roll)
        if roll in overrides:
            continue  # the manual override wins; no fetch needed
        row = signatures.by_roll.get(roll)
        if row is None:
            issues.append(
                Issue(
                    roll=student.roll,
                    name=student.name,
                    level="warning",
                    message="No signature submission found for this roll number.",
                )
            )
            continue
        if row.drive_id:
            wanted[roll] = row.drive_id
    return wanted, issues


async def generate_batch(
    *,
    roster_bytes: bytes,
    marks_bytes: bytes,
    class_info: ClassInfo,
    teacher_signature: bytes | None = None,
    college_stamp: bytes | None = None,
    signature_sheet: bytes | None = None,
    student_signatures_zip: bytes | None = None,
    roster_name: str = "roster.xlsx",
    marks_name: str = "marks.xlsx",
    cache: ImageCache | None = None,
    transport=None,
) -> BatchResult:
    """Run the whole pipeline and return a ZIP plus a manifest of what happened."""
    students, issues = build_students(
        roster_bytes, marks_bytes, class_info, roster_name, marks_name
    )

    overrides = read_override_zip(student_signatures_zip)
    signatures = (
        parse_signature_workbook(signature_sheet) if signature_sheet else None
    )
    if signatures:
        # The signature workbook covers every class in the college (~760 students).
        # Only its problems with *this* batch's students belong in this manifest --
        # otherwise a class of 4 gets 30-odd warnings about people who are not in it.
        batch_rolls = {normalize_roll(student.roll) for student in students}
        issues.extend(
            issue
            for issue in signatures.issues
            if not issue.roll or normalize_roll(issue.roll) in batch_rolls
        )

    wanted, signature_issues = resolve_signature_ids(students, signatures, overrides)
    issues.extend(signature_issues)
    issues = _dedupe(issues)

    fetched = (
        await fetch_signatures(wanted, cache=cache, transport=transport)
        if wanted
        else {}
    )

    outcomes: list[StudentOutcome] = []
    buffer = BytesIO()

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for student in students:
            roll = normalize_roll(student.roll)
            signature_bytes: bytes | None = None
            source = ""
            status = GENERATED
            detail = ""

            if roll in overrides:
                signature_bytes = overrides[roll]
                source = "uploaded-zip"
            elif (result := fetched.get(roll)) is not None:
                if result.ok:
                    signature_bytes = result.data
                    source = "drive-cache" if result.from_cache else "drive"
                else:
                    status = SIGNATURE_FAILED
                    detail = result.error or "signature could not be retrieved"
            elif signatures is not None:
                status = SIGNATURE_MISSING
                detail = "No signature submission found for this roll number."

            assets = SignatureAssets(
                teacher=teacher_signature, stamp=college_stamp, student=signature_bytes
            )
            filename = output_filename(student)
            archive.writestr(filename, build_pdf(student, class_info, assets))

            outcomes.append(
                StudentOutcome(
                    roll=student.roll,
                    name=student.name,
                    status=status,
                    filename=filename,
                    total=student.total,
                    percent=student.percent,
                    feedback=student.feedback,
                    signature_source=source,
                    detail=detail,
                )
            )

        # The manifest travels inside the ZIP: a long Drive fetch makes response
        # headers an unreliable place to put it (§6).
        manifest = {
            "generatedOn": date.today().isoformat(),
            "subject": class_info.subject,
            "paperCode": class_info.paper_code,
            "studentCount": len(students),
            "generated": sum(1 for o in outcomes if o.status == GENERATED),
            "students": [o.as_dict() for o in outcomes],
            "issues": [i.as_dict() for i in issues],
        }
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))

    return BatchResult(buffer.getvalue(), outcomes, issues)


def generate_batch_sync(**kwargs) -> BatchResult:
    """Blocking wrapper, for tests and scripts."""
    return asyncio.run(generate_batch(**kwargs))
