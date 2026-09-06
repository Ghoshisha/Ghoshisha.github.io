"""Regression tests for the scoring rules recovered from the teacher's own sheet.

Every expected value here comes from real data: the three students in
``fixtures/AIML.xlsx!Sheet1`` and the printed ``fixtures/Abhisha Banerjee.pdf``.
These are the tests that catch the three errors in the original spec (Appendix A.1-A.3).
"""

from __future__ import annotations

import pytest

from app.defaults import default_class_info
from app.models import ClassInfo
from app.scoring import (
    NA,
    ar_reference,
    band_for,
    compute_total,
    parse_score,
    remark_for_score,
    score_student,
)

# Raw scores exactly as they sit in AIML.xlsx!Sheet1 (Appendix A.10).
ABHISHA_SHEET = {
    "1.a": 1, "1.b": 1, "1.c": 1, "1.d": 1, "1.e": 1, "1.f": None,
    "2": 2, "3": 3, "4": 3, "5": None, "6": None,
}
ANGIRA_SHEET = {
    "1.a": 1, "1.b": 1, "1.c": 1, "1.d": None, "1.e": 1, "1.f": 1,
    "2": None, "3": 5, "4": 5, "5": 5, "6": 5,
}
DEEP_SHEET = {
    "1.a": 1, "1.b": 1, "1.c": 1, "1.d": 0.5, "1.e": None, "1.f": 1,
    "2": 2, "3": 3, "4": 3, "5": None, "6": None,
}
# The row as printed in the reference PDF -- 1.d was still blank when it was generated.
ABHISHA_PDF = {**ABHISHA_SHEET, "1.d": None}


@pytest.fixture
def class_info() -> ClassInfo:
    return default_class_info()


class TestTotalIsBestNOfM:
    """Appendix A.1 -- the sheet drops the lowest score in each fully-attempted group."""

    @pytest.mark.parametrize(
        "scores, expected",
        [
            pytest.param(ABHISHA_SHEET, 13, id="abhisha-sheet"),
            pytest.param(ANGIRA_SHEET, 25, id="angira-sheet"),
            pytest.param(DEEP_SHEET, 12.5, id="deep-sheet"),
            pytest.param(ABHISHA_PDF, 12, id="abhisha-as-printed-in-pdf"),
        ],
    )
    def test_matches_the_sheet(self, class_info, scores, expected):
        assert compute_total(scores, class_info) == expected

    def test_drops_lowest_when_every_question_attempted(self, class_info):
        """The case a plain sum gets wrong: all 11 answered, two scores dropped."""
        scores = {
            "1.a": 1, "1.b": 1, "1.c": 1, "1.d": 0.5, "1.e": 1, "1.f": 1,
            "2": 5, "3": 5, "4": 5, "5": 5, "6": 1,
        }
        # Group 1: 5.5 attempted, drop the 0.5 -> 5. Group 2: 21, drop the 1 -> 20.
        assert compute_total(scores, class_info) == 25
        assert sum(v for v in scores.values() if v is not None) == 26.5

    def test_perfect_paper_cannot_exceed_full_marks(self, class_info):
        """31 marks are allotted but the paper is out of 25 -- that is the drop rule."""
        allotted = {q.qno: q.marks_allotted for q in class_info.questions}
        assert sum(allotted.values()) == 31
        assert compute_total(allotted, class_info) == class_info.full_marks == 25

    def test_group_with_a_blank_drops_nothing(self, class_info):
        """COUNT ignores blanks, so an unattempted question is itself the "drop"."""
        scores = {"1.a": 1, "1.b": 1, "1.c": 1, "1.d": 1, "1.e": 1, "1.f": None}
        assert compute_total(scores, class_info) == 5

    def test_ungrouped_questions_always_count(self):
        info = ClassInfo.model_validate(
            {
                "fullMarks": 10,
                "questions": [
                    {"qno": "1", "marksAllotted": 5},
                    {"qno": "2", "marksAllotted": 5},
                ],
                "questionGroups": [],
            }
        )
        assert compute_total({"1": 4, "2": 3}, info) == 7


class TestRemarks:
    """Spec §5 / Appendix A.3 -- one rule reproducing both of the sheet's variants."""

    @pytest.mark.parametrize(
        "score, allotted, expected",
        [
            # One-mark questions: the sheet's =1 / =0.5 / else variant.
            (1, 1, "Correct"),
            (0.5, 1, "Partially Correct"),
            (0, 1, "Wrong"),
            (None, 1, NA),
            ("", 1, NA),
            # Five-mark questions: the sheet's =0 / =5 / else variant.
            (5, 5, "Correct"),
            (3, 5, "Partially Correct"),
            (0, 5, "Wrong"),
            (None, 5, NA),
        ],
    )
    def test_three_zone_rule(self, score, allotted, expected):
        assert remark_for_score(score, allotted) == expected

    def test_partial_credit_on_a_five_mark_question(self, class_info):
        """§9.3: the reference PDF prints "Wrong" here because it predates the fix."""
        result = score_student("25371025001", "Abhisha Banerjee", ABHISHA_SHEET, class_info)
        by_qno = {q.qno: q.remark for q in result.questions}
        assert by_qno["2"] == "Partially Correct"
        assert by_qno["3"] == "Partially Correct"
        assert by_qno["4"] == "Partially Correct"

    def test_reproduces_every_remark_in_the_sheet(self, class_info):
        result = score_student("25371025004", "Deep Chakraborty", DEEP_SHEET, class_info)
        assert [q.remark for q in result.questions] == [
            "Correct", "Correct", "Correct", "Partially Correct", NA, "Correct",
            "Partially Correct", "Partially Correct", "Partially Correct", NA, NA,
        ]


class TestArReference:
    """Appendix A.2 -- Bloom letter + attainment digit, with the sheet's bug fixed."""

    def test_corrected_lookup_uses_each_questions_bloom_level(self, class_info):
        result = score_student("25371025001", "Abhisha Banerjee", ABHISHA_SHEET, class_info)
        assert [q.ar_reference for q in result.questions] == [
            "A1",  # 1.a Remember,  1/1 = 100%
            "A1",  # 1.b Remember,  1/1
            "A1",  # 1.c Understand,1/1
            "A1",  # 1.d Understand,1/1
            "A1",  # 1.e Remember,  1/1
            NA,    # 1.f blank
            "B3",  # 2   Apply,     2/5 = 40%
            "A2",  # 3   Understand,3/5 = 60%
            "A2",  # 4   Understand,3/5 = 60%
            NA,    # 5   blank
            NA,    # 6   blank
        ]

    def test_legacy_mode_reproduces_the_sheets_broken_lookup(self, class_info):
        """Every question falls through to "C" -- what the teacher's sheet emits today."""
        legacy = class_info.model_copy(update={"ar_reference_mode": "legacy"})
        result = score_student("25371025001", "Abhisha Banerjee", ABHISHA_SHEET, legacy)
        assert [q.ar_reference for q in result.questions] == [
            "C1", "C1", "C1", "C1", "C1", NA, "C3", "C2", "C2", NA, NA,
        ]

    @pytest.mark.parametrize(
        "bloom, expected_letter",
        [
            ("Remember", "A"), ("Understand", "A"),
            ("Apply", "B"),
            ("Analyze", "D"), ("Evaluate", "D"), ("Create", "D"),
            ("Something Else", "C"), ("", "C"),
        ],
    )
    def test_bloom_letter_mapping(self, bloom, expected_letter):
        from app.models import Question

        question = Question(qno="1", marks_allotted=1, bloom_level=bloom)
        assert ar_reference(1, question)[0] == expected_letter

    @pytest.mark.parametrize(
        "score, expected_digit",
        [(5, "1"), (4, "1"), (3, "2"), (2, "3"), (1, "4"), (0.5, "4")],
    )
    def test_attainment_digit_thresholds(self, score, expected_digit):
        from app.models import Question

        question = Question(qno="2", marks_allotted=5, bloom_level="Apply")
        assert ar_reference(score, question)[1] == expected_digit

    @pytest.mark.parametrize("score", [None, "", 0])
    def test_blank_or_zero_is_na(self, score):
        from app.models import Question

        question = Question(qno="2", marks_allotted=5, bloom_level="Apply")
        assert ar_reference(score, question) == NA


class TestFeedbackBands:
    def test_reference_pdf_feedback(self, class_info):
        """The printed document: 12/25 = 48% -> Fair Understanding."""
        result = score_student("25371025001", "Abhisha Banerjee", ABHISHA_PDF, class_info)
        assert result.total == 12
        assert result.percent == 48.0
        assert result.feedback == "Fair Understanding"
        assert result.areas == "Improve Conceptual Understanding"
        assert result.measures == "Practice Concept Application"

    def test_full_marks_lands_in_the_top_band(self, class_info):
        result = score_student("25371025003", "Angira Ghosh", ANGIRA_SHEET, class_info)
        assert result.total == 25
        assert result.percent == 100.0
        assert result.feedback == "Excellent Clarity"

    def test_percent_generalizes_to_a_different_full_marks(self, class_info):
        """§9.4: bands are proportional, so a 50-mark paper buckets the same way."""
        fifty = class_info.model_copy(update={"full_marks": 50})
        assert band_for(48.0, fifty.feedback_bands).feedback == "Fair Understanding"

    def test_absolute_cutoffs_agree_at_full_marks_25(self, class_info):
        """Appendix A.4 -- the sheet's <=5/<=10/<=15/<=20 equal 20/40/60/80% of 25."""
        for total, expected in [
            (5, "Needs Improvement"),
            (10, "Basic Knowledge"),
            (15, "Fair Understanding"),
            (20, "Good Clarity"),
            (25, "Excellent Clarity"),
        ]:
            percent = total / 25 * 100
            assert band_for(percent, class_info.feedback_bands).feedback == expected

    def test_a_student_with_no_marks_at_all_is_na(self, class_info):
        """The sheet guards its band lookup with IF(total="","NA",...)."""
        blank = {q.qno: None for q in class_info.questions}
        result = score_student("999", "Absent Student", blank, class_info)
        assert result.total == 0
        assert (result.feedback, result.areas, result.measures) == (NA, NA, NA)

    def test_a_genuine_zero_still_gets_banded(self, class_info):
        """Attempted everything and scored nothing is not the same as absent."""
        zeros = {q.qno: 0 for q in class_info.questions}
        result = score_student("999", "Zero Student", zeros, class_info)
        assert result.total == 0
        assert result.feedback == "Needs Improvement"


class TestParseScore:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (1, 1.0), (0.5, 0.5), (0, 0.0),
            ("1", 1.0), ("0.5", 0.5), (" 2 ", 2.0),
            (None, None), ("", None), ("   ", None), ("absent", None),
            (True, None),  # a stray checkbox is not a score
        ],
    )
    def test_parses(self, raw, expected):
        assert parse_score(raw) == expected

    def test_blank_is_not_zero(self):
        """The distinction the whole NA/Wrong split depends on."""
        assert parse_score(None) is None
        assert parse_score(0) == 0.0


class TestStudentResult:
    def test_missing_scores_are_listed_for_the_preview_table(self, class_info):
        result = score_student("25371025001", "Abhisha Banerjee", ABHISHA_PDF, class_info)
        assert result.missing_scores == ["1.d", "1.f", "5", "6"]

    def test_awarded_marks_print_without_a_float_suffix(self, class_info):
        result = score_student("25371025004", "Deep Chakraborty", DEEP_SHEET, class_info)
        awarded = {q.qno: q.marks_awarded for q in result.questions}
        assert awarded["1.a"] == "1"
        assert awarded["1.d"] == "0.5"
        assert awarded["2"] == "2"
        assert awarded["5"] == ""
