"""End-to-end assertions against the real reference files.

These are the tests that would have caught the spec's three errors on real data rather
than on hand-written examples. They skip when the gitignored fixtures are absent.
"""

from __future__ import annotations

import pytest

from app.defaults import default_class_info
from app.parsing import parse_marks, parse_roster
from app.scoring import score_student
from app.signatures import extract_drive_id, parse_signature_workbook

ABHISHA_ROLL = "25371025001"
ABHISHA_DRIVE_ID = "12uZuuQ3MIeNzTPD-u41bZSrgFyLIrYOF"


@pytest.fixture(scope="module")
def marks(aiml_bytes):
    return parse_marks(aiml_bytes, default_class_info(), "AIML.xlsx")


@pytest.fixture(scope="module")
def signatures(signature_bytes):
    return parse_signature_workbook(signature_bytes, "Signature.xlsx")


class TestMarksSheet:
    """AIML.xlsx!Sheet1 is the live Autocrat working sheet."""

    def test_reads_all_four_students(self, marks):
        assert len(marks.scores) == 4

    def test_float_headers_matched_every_question(self, marks):
        """The five-mark columns are headed 2.0/3.0/4.0/5.0/6.0 (Appendix A.9)."""
        assert marks.unmatched_questions == []
        assert set(marks.scores[ABHISHA_ROLL]) == {
            "1.a", "1.b", "1.c", "1.d", "1.e", "1.f", "2", "3", "4", "5", "6",
        }

    def test_five_mark_scores_are_not_silently_missing(self, marks):
        """The failure §9.1/A.9 describes: every Q2-Q6 score going blank."""
        scores = marks.scores[ABHISHA_ROLL]
        assert scores["2"] == 2
        assert scores["3"] == 3
        assert scores["4"] == 3

    def test_swapped_roll_and_name_columns_are_corrected(self, marks):
        """Appendix A.8 -- the column headed 'Roll' holds names for every row."""
        assert ABHISHA_ROLL in marks.scores
        assert any(
            "swapped" in issue.message and issue.level == "warning"
            for issue in marks.issues
        ), "the swap should be reported, not silently corrected"

    def test_roster_reads_the_same_file(self, aiml_bytes):
        roster = parse_roster(aiml_bytes, "AIML.xlsx")
        by_roll = roster.by_roll()
        assert by_roll[ABHISHA_ROLL].name == "Abhisha Banerjee"

    @pytest.mark.parametrize(
        "roll, name, expected_total",
        [
            ("25371025001", "Abhisha Banerjee", 13),
            ("25371025003", "ANGIRA GHOSH", 25),
            ("25371025004", "Deep Chakraborty", 12.5),
        ],
    )
    def test_totals_match_the_sheets_own_total_column(
        self, marks, roll, name, expected_total
    ):
        """Appendix A.1 -- computed with the drop-lowest rule, never read from a column."""
        result = score_student(roll, name, marks.scores[roll], default_class_info())
        assert result.total == expected_total

    def test_no_student_exceeds_full_marks(self, marks):
        info = default_class_info()
        for roll, scores in marks.scores.items():
            result = score_student(roll, "", scores, info)
            assert result.total <= info.full_marks, roll


class TestSignatureWorkbook:
    """Appendix A.7 -- measured against the real 16-sheet export."""

    def test_reads_every_sheet(self, signatures):
        assert signatures.sheets_read == 16

    def test_reduces_1794_rows_to_759_students(self, signatures):
        """1812 non-blank rows, less 16 header rows and 2 with no usable roll."""
        assert signatures.rows_read == 1794
        assert len(signatures.by_roll) == 759

    def test_the_reference_student_resolves_to_the_pdfs_signature(self, signatures):
        """The join the whole system rests on, verified end to end."""
        row = signatures.get(ABHISHA_ROLL)
        assert row is not None
        assert row.name == "Abhisha Banerjee"
        assert row.drive_id == ABHISHA_DRIVE_ID

    def test_keeps_the_latest_of_ten_resubmissions(self, signatures):
        """Roll 36441623008 submitted the form ten times."""
        row = signatures.get("36441623008")
        assert row is not None
        assert row.drive_id

    def test_exact_timestamp_tie_prefers_the_department_sheet(self, signatures):
        """MD ARIF JAMIL: same timestamp, different links, Sheet1 vs CSE2024-2028."""
        row = signatures.get("25300104046")
        assert row is not None
        # A later submission exists, so that is what should actually win.
        assert row.timestamp is not None
        assert row.drive_id

    def test_reports_ambiguous_ties_rather_than_hiding_them(self, signatures):
        """32 rolls have their winner decided by an exact-timestamp tie (A.7)."""
        ties = [i for i in signatures.issues if "share timestamp" in i.message]
        assert len(ties) == 32
        assert all(i.level == "warning" for i in ties)

    def test_a_tie_that_did_not_decide_anything_is_not_reported(self, signatures):
        """MD ARIF JAMIL ties in two sheets, but a later submission wins outright."""
        row = signatures.get("25300104046")
        assert row is not None and row.sheet == "Sheet1"
        assert not any(i.roll == "25300104046" for i in signatures.issues)

    def test_leaked_header_rows_are_not_imported_as_students(self, signatures):
        """BCASIMT and BCA2025-2028 carry a literal header row mid-data."""
        assert "universityrollnumber" not in signatures.by_roll
        assert "fullname" not in signatures.by_roll

    def test_the_row_with_a_name_in_the_roll_column_is_visible(self, signatures):
        """§9.2 -- surfaced, never name-matched away. 'Shubha Maity' in the roll column."""
        assert "shubhamaity" in signatures.by_roll

    def test_every_kept_row_has_a_normalized_numeric_roll_or_is_flagged(self, signatures):
        odd = [r for r in signatures.by_roll if not r.isdigit()]
        assert odd == ["shubhamaity"], odd

    def test_dirty_roll_spellings_collapse_onto_one_student(self, signatures):
        """25300122014.0 (float) and 25300124010. (trailing dot) both normalize."""
        assert signatures.get("25300122014") is not None
        assert signatures.get("25300124010") is not None


class TestDriveLinks:
    @pytest.mark.parametrize(
        "link, expected",
        [
            (
                f"https://drive.google.com/file/d/{ABHISHA_DRIVE_ID}/view?usp=drivesdk",
                ABHISHA_DRIVE_ID,
            ),
            (
                f"https://drive.google.com/open?id={ABHISHA_DRIVE_ID}",
                ABHISHA_DRIVE_ID,
            ),
            (
                f"https://docs.google.com/thumbnail?sz=w500&id={ABHISHA_DRIVE_ID}",
                ABHISHA_DRIVE_ID,
            ),
            ("not a link at all", None),
            ("", None),
            (None, None),
        ],
    )
    def test_extracts_the_file_id_from_every_link_shape(self, link, expected):
        assert extract_drive_id(link) == expected

    def test_every_signature_link_in_the_file_yields_an_id(self, signatures):
        missing = [r.raw_roll for r in signatures.by_roll.values() if not r.drive_id]
        # Appendix A.7: exactly two rows in the real file have no usable link.
        assert len(missing) <= 2, missing
