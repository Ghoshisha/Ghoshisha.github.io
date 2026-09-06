"""The shared normalizer (spec §9.1, Appendix A.9).

Roll number is the only join key across three files and it arrives dirty from all three.
Question numbers arrive equally dirty as spreadsheet headers. Every equivalence asserted
here is one observed in the real reference files.
"""

from __future__ import annotations

import pytest

from app.normalize import (
    is_numeric_id,
    looks_like_header_label,
    normalize,
    normalize_roll,
    slugify_name,
    strip_float_suffix,
)


class TestQuestionNumbers:
    """Appendix A.9 -- headers arrive as floats; "2.0" must not become "20"."""

    def test_float_header_matches_its_question(self):
        assert normalize(2.0) == normalize("2") == normalize("2.0") == "2"

    def test_dotted_and_undotted_forms_agree(self):
        # Sheet1 writes "1.a", Sheet2 writes "1a".
        assert normalize("1.a") == normalize("1a") == normalize(" 1 A ") == "1a"

    def test_the_bug_this_guards(self):
        """Stripping punctuation first would turn "2.0" into "20"."""
        assert normalize("2.0") != "20"

    @pytest.mark.parametrize("header", ["3.0", 3.0, "3", 3, " 3 "])
    def test_every_form_of_question_three(self, header):
        assert normalize(header) == "3"


class TestRollNumbers:
    @pytest.mark.parametrize(
        "raw",
        ["25300122014", "25300122014.0", 25300122014, 25300122014.0, " 25300122014 "],
    )
    def test_all_spellings_of_one_roll_agree(self, raw):
        assert normalize_roll(raw) == "25300122014"

    def test_trailing_dot(self):
        """Observed verbatim in Signature.xlsx."""
        assert normalize_roll("25300124010.") == "25300124010"

    def test_large_ids_do_not_go_scientific(self):
        """str(2.5300122014e10) would be a disaster for a join key."""
        assert normalize_roll(364404025013.0) == "364404025013"

    def test_distinct_rolls_stay_distinct(self):
        """§9.2: two rolls for one person are two rolls; never reconcile them."""
        assert normalize_roll("2530012014") != normalize_roll("25300122014")

    def test_none_and_blank(self):
        assert normalize_roll(None) == ""
        assert normalize_roll("") == ""
        assert normalize_roll("   ") == ""


class TestStripFloatSuffix:
    @pytest.mark.parametrize(
        "raw, expected",
        [("2.0", "2"), ("2.", "2"), ("2", "2"), ("0.5", "0.5"), ("1.a", "1.a")],
    )
    def test_only_strips_a_trailing_zero_decimal(self, raw, expected):
        assert strip_float_suffix(raw) == expected


class TestHeaderLabels:
    @pytest.mark.parametrize(
        "cell", ["Full Name", "University Roll Number", "  Roll  ", "Signature Drive Link"]
    )
    def test_detects_leaked_header_rows(self, cell):
        """Appendix A.7 -- BCASIMT and BCA2025-2028 carry a header row mid-data."""
        assert looks_like_header_label(cell)

    @pytest.mark.parametrize("cell", ["Abhisha Banerjee", "25371025001", "", None])
    def test_leaves_real_data_alone(self, cell):
        assert not looks_like_header_label(cell)


class TestIsNumericId:
    @pytest.mark.parametrize("cell", ["25371025001", 25371025001, 25371025001.0, "25300124010."])
    def test_roll_numbers(self, cell):
        assert is_numeric_id(cell)

    @pytest.mark.parametrize("cell", ["Abhisha Banerjee", "Shubha Maity", "", None, "MCA-2025"])
    def test_names(self, cell):
        assert not is_numeric_id(cell)


class TestSlugifyName:
    @pytest.mark.parametrize(
        "name, expected",
        [
            ("Abhisha Banerjee", "Abhisha_Banerjee"),
            ("MD ARIF JAMIL", "MD_ARIF_JAMIL"),
            ("Riddhima  Singh   Rajput", "Riddhima_Singh_Rajput"),
            ("O'Brien, Sean", "OBrien_Sean"),
            ("", "unnamed"),
        ],
    )
    def test_filename_safe(self, name, expected):
        assert slugify_name(name) == expected
