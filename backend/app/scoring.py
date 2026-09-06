"""Derived per-student values: remarks, total, feedback band, AR reference.

Spec §5, corrected by Appendix A.1 (best-N-of-M total) and A.2 (derived AR reference).
Every rule here was recovered from the formulas in the teacher's own working sheet
(``fixtures/AIML.xlsx``) and is regression-tested against three real students.

Pure functions only -- no I/O, no framework types. This is the part that has to be
correct, and it is tested without HTTP or files.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import ClassInfo, FeedbackBand, Question

NA = "NA"

# Appendix A.2 -- Bloom's taxonomy level to AR letter.
_BLOOM_LETTERS: dict[str, str] = {
    "remember": "A",
    "understand": "A",
    "apply": "B",
    "analyze": "D",
    "analyse": "D",
    "evaluate": "D",
    "create": "D",
}
_BLOOM_FALLBACK_LETTER = "C"

# Appendix A.2 -- proportion of marks earned to AR digit, highest band first.
_AR_DIGIT_THRESHOLDS: tuple[tuple[float, str], ...] = (
    (0.8, "1"),
    (0.6, "2"),
    (0.4, "3"),
)
_AR_FALLBACK_DIGIT = "4"


def parse_score(value: object) -> float | None:
    """A blank cell means "not attempted", which is distinct from a zero.

    Blank propagates to ``NA`` in Remarks and AR Reference and contributes nothing to
    the total; a literal ``0`` means the student attempted and got it wrong.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return None if value != value else float(value)  # NaN guard
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def remark_for_score(score: object, marks_allotted: float) -> str:
    """Three-zone rule (§5): full marks Correct, zero Wrong, anything between partial.

    The teacher's sheet hardcodes this twice -- once comparing against 1/0.5 for the
    one-mark questions, once against 0/5 for the five-mark ones. Both are this same rule
    specialized by ``marks_allotted``; this generalization reproduces both exactly.
    """
    value = parse_score(score)
    if value is None or not marks_allotted:
        return NA
    if value >= marks_allotted:
        return "Correct"
    if value == 0:
        return "Wrong"
    return "Partially Correct"


def ar_reference(score: object, question: Question, mode: str = "corrected") -> str:
    """AR Reference: Bloom letter + attainment digit (Appendix A.2).

    ``mode="legacy"`` reproduces the broken row-wise Bloom lookup in the teacher's
    sheet, where every question but the first resolves an empty cell and so falls
    through to the ``C`` default. Only for reissuing an already-distributed document.
    """
    value = parse_score(score)
    if value is None or value <= 0 or not question.marks_allotted:
        return NA

    if mode == "legacy":
        letter = _BLOOM_FALLBACK_LETTER
    else:
        letter = _BLOOM_LETTERS.get(
            question.bloom_level.strip().lower(), _BLOOM_FALLBACK_LETTER
        )

    fraction = value / question.marks_allotted
    digit = _AR_FALLBACK_DIGIT
    for threshold, candidate in _AR_DIGIT_THRESHOLDS:
        if fraction >= threshold:
            digit = candidate
            break
    return letter + digit


def compute_total(scores: dict[str, object], class_info: ClassInfo) -> float:
    """Total marks, dropping the lowest score in each fully-attempted group (A.1).

    Mirrors ``IF(COUNT(range) > countBest, SUM(range) - SMALL(range, 1), SUM(range))``
    per group: blanks are not counted, so a group with an unattempted question drops
    nothing. Questions in no group always count in full.
    """
    grouped: set[str] = {qno for g in class_info.question_groups for qno in g.questions}
    total = 0.0

    for group in class_info.question_groups:
        attempted = [
            v
            for qno in group.questions
            if (v := parse_score(scores.get(qno))) is not None
        ]
        subtotal = sum(attempted)
        # Drop lowest scores only once the whole group has been attempted, matching the
        # sheet's COUNT guard. Guards against a negative count_best difference too.
        drop = len(attempted) - group.count_best
        if drop > 0:
            subtotal -= sum(sorted(attempted)[:drop])
        total += subtotal

    for question in class_info.questions:
        if question.qno in grouped:
            continue
        value = parse_score(scores.get(question.qno))
        if value is not None:
            total += value

    return total


def band_for(percent: float, bands: list[FeedbackBand]) -> FeedbackBand | None:
    """First band whose ceiling clears the score (§5). Bands arrive sorted ascending."""
    if not bands:
        return None
    for band in bands:
        if percent <= band.max_percent:
            return band
    return bands[-1]


@dataclass
class QuestionResult:
    qno: str
    marks_allotted: float
    marks_awarded: str
    co_mapping: str
    bloom_level: str
    remark: str
    ar_reference: str


@dataclass
class StudentResult:
    roll: str
    name: str
    total: float
    percent: float
    feedback: str
    areas: str
    measures: str
    questions: list[QuestionResult] = field(default_factory=list)
    missing_scores: list[str] = field(default_factory=list)

    @property
    def has_any_score(self) -> bool:
        return len(self.missing_scores) < len(self.questions)


def _format_awarded(score: object) -> str:
    """Print 3 not 3.0, and 0.5 as 0.5. A blank cell prints as an empty cell."""
    value = parse_score(score)
    if value is None:
        return ""
    return str(int(value)) if float(value).is_integer() else str(value)


def score_student(
    roll: str, name: str, scores: dict[str, object], class_info: ClassInfo
) -> StudentResult:
    """Compute every derived value for one student."""
    total = compute_total(scores, class_info)
    percent = (total / class_info.full_marks * 100) if class_info.full_marks else 0.0

    questions: list[QuestionResult] = []
    missing: list[str] = []
    for question in class_info.questions:
        raw = scores.get(question.qno)
        if parse_score(raw) is None:
            missing.append(question.qno)
        questions.append(
            QuestionResult(
                qno=question.qno,
                marks_allotted=question.marks_allotted,
                marks_awarded=_format_awarded(raw),
                co_mapping=question.co_mapping,
                bloom_level=question.bloom_level,
                remark=remark_for_score(raw, question.marks_allotted),
                ar_reference=ar_reference(
                    raw, question, class_info.ar_reference_mode
                ),
            )
        )

    # The sheet guards its band lookup with IF(total="","NA",...) -- a student with no
    # marks at all gets NA rather than being bucketed into the lowest band.
    if len(missing) == len(class_info.questions):
        feedback = areas = measures = NA
    else:
        band = band_for(percent, class_info.feedback_bands)
        if band is None:
            feedback = areas = measures = NA
        else:
            feedback, areas, measures = band.feedback, band.areas, band.measures

    return StudentResult(
        roll=roll,
        name=name,
        total=total,
        percent=round(percent, 2),
        feedback=feedback,
        areas=areas,
        measures=measures,
        questions=questions,
        missing_scores=missing,
    )
