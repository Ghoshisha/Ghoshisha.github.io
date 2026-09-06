"""PDF rendering (spec §7, Appendix A.5).

Assertions are on the rendered output -- text extracted back out of the generated PDF
and the images actually embedded in it -- rather than on the code that produced it.
"""

from __future__ import annotations

import re

import pytest

from app.defaults import default_class_info
from app.pdf_generator import SignatureAssets, build_pdf, output_filename
from app.scoring import score_student

pypdf = pytest.importorskip("pypdf", reason="pypdf is only needed to inspect output")

def _png(colour: tuple[int, int, int], size: tuple[int, int] = (60, 20)) -> bytes:
    """A small distinct PNG.

    The three images must differ: ReportLab folds byte-identical images into a single
    XObject, so reusing one sample would make a three-image page look like a one-image
    page to the assertions below.
    """
    from io import BytesIO

    from PIL import Image as PILImage

    buffer = BytesIO()
    PILImage.new("RGB", size, colour).save(buffer, format="PNG")
    return buffer.getvalue()


PNG = _png((10, 20, 200))
TEACHER_PNG = _png((200, 20, 20))
STAMP_PNG = _png((20, 160, 60), size=(50, 50))

ABHISHA_PDF_SCORES = {
    "1.a": 1, "1.b": 1, "1.c": 1, "1.d": None, "1.e": 1, "1.f": None,
    "2": 2, "3": 3, "4": 3, "5": None, "6": None,
}


@pytest.fixture
def class_info():
    return default_class_info()


@pytest.fixture
def student(class_info):
    return score_student(
        "25371025001", "Abhisha Banerjee", ABHISHA_PDF_SCORES, class_info
    )


def extract_text(data: bytes) -> str:
    reader = pypdf.PdfReader(__import__("io").BytesIO(data))
    return " ".join(page.extract_text() for page in reader.pages)


def squash(text: str) -> str:
    """Collapse the whitespace ReportLab scatters through extracted text."""
    return re.sub(r"\s+", " ", text)


class TestDocumentStructure:
    def test_produces_a_single_a4_page(self, student, class_info):
        data = build_pdf(student, class_info)
        reader = pypdf.PdfReader(__import__("io").BytesIO(data))
        assert len(reader.pages) == 1
        box = reader.pages[0].mediabox
        # A4 at 595x842pt, matching the reference document.
        assert round(float(box.width)) == 595
        assert round(float(box.height)) == 842

    def test_is_a_real_pdf(self, student, class_info):
        assert build_pdf(student, class_info).startswith(b"%PDF-")

    def test_title_block(self, student, class_info):
        text = squash(extract_text(build_pdf(student, class_info)))
        assert "Maulana Abul Kalam Azad University of Technology" in text
        assert "Top Sheet for CA2 Marks Submission" in text
        assert "Written Test as a part of Continuous Assessment" in text


class TestInfoTable:
    def test_name_and_roll_are_not_swapped(self, student, class_info):
        """§9.10 / A.8 -- the reference PDF has these the wrong way round."""
        text = squash(extract_text(build_pdf(student, class_info)))
        assert "Name of the Student: Abhisha Banerjee" in text
        assert "Roll Number: 25371025001" in text
        assert "Name of the Student: 25371025001" not in text

    def test_class_fields(self, student, class_info):
        text = squash(extract_text(build_pdf(student, class_info)))
        for expected in (
            "253, Supreme Knowledge Foundation Group of Institutions",
            "Master of Computer Application",
            "Basic Data Science",
            "MCAN-E304F",
            "3887",
            "01/09/2026",
            "Isha Ghosh",
            "7439399035",
            "1 Hour",
        ):
            assert expected in text, expected

    def test_full_marks_prints_without_a_float_suffix(self, student, class_info):
        text = squash(extract_text(build_pdf(student, class_info)))
        assert "Full Marks: 25" in text
        assert "25.0" not in text


class TestMarksTable:
    def test_every_question_appears(self, student, class_info):
        text = squash(extract_text(build_pdf(student, class_info)))
        for question in class_info.questions:
            assert question.qno in text

    def test_computed_values_are_printed(self, student, class_info):
        text = squash(extract_text(build_pdf(student, class_info)))
        assert "Correct" in text
        assert "Partially Correct" in text
        assert "NA" in text

    def test_total_appears_once_as_a_merged_cell(self, student, class_info):
        """§7 item 4 -- one Total Marks cell spanning every question row."""
        text = extract_text(build_pdf(student, class_info))
        assert student.total == 12
        # "12" should show up as the total, not repeated per row.
        assert len(re.findall(r"(?<!\d)12(?!\d)", text)) == 1

    def test_headings(self, student, class_info):
        text = squash(extract_text(build_pdf(student, class_info)))
        assert "Marks Distribution & Mapping" in text
        assert "Assessment Rubrics" in text
        assert "AR Reference" in squash(text.replace("\n", " "))


class TestFeedbackBlock:
    def test_prints_the_derived_band(self, student, class_info):
        text = squash(extract_text(build_pdf(student, class_info)))
        assert "Strengths of the Student: Fair Understanding" in text
        assert "Areas for Improvement: Improve Conceptual Understanding" in text
        assert "Suggested Corrective Measures: Practice Concept Application" in text

    def test_acknowledgement_line_is_verbatim(self, student, class_info):
        text = squash(extract_text(build_pdf(student, class_info)))
        assert (
            "I have reviewed my evaluated answer script and understand the awarded "
            "marks and feedback." in text
        )

    def test_signature_captions(self, student, class_info):
        text = squash(extract_text(build_pdf(student, class_info)))
        assert "Signature of the Examiner with date" in text
        assert "Signature of the student with date" in text


class TestImages:
    def _image_count(self, data: bytes) -> int:
        reader = pypdf.PdfReader(__import__("io").BytesIO(data))
        return len(list(reader.pages[0].images))

    def test_embeds_all_three_images(self, student, class_info):
        """Appendix A.5 -- teacher signature, student signature and college stamp."""
        assets = SignatureAssets(teacher=TEACHER_PNG, stamp=STAMP_PNG, student=PNG)
        assert self._image_count(build_pdf(student, class_info, assets)) == 3

    def test_a_missing_student_signature_still_renders(self, student, class_info):
        """§7 -- never fail a student's PDF over a missing image."""
        assets = SignatureAssets(teacher=TEACHER_PNG, stamp=STAMP_PNG, student=None)
        data = build_pdf(student, class_info, assets)
        assert self._image_count(data) == 2
        assert "Signature not provided" in squash(extract_text(data))

    def test_renders_with_no_images_at_all(self, student, class_info):
        data = build_pdf(student, class_info, SignatureAssets())
        assert self._image_count(data) == 0
        assert "Abhisha Banerjee" in squash(extract_text(data))

    def test_a_corrupt_image_does_not_break_the_batch(self, student, class_info):
        assets = SignatureAssets(teacher=b"<html>not an image</html>", student=PNG)
        data = build_pdf(student, class_info, assets)
        assert data.startswith(b"%PDF-")
        assert "Signature not provided" in squash(extract_text(data))


class TestOutputFilename:
    def test_roll_and_slugified_name(self, student):
        assert output_filename(student) == "25371025001_Abhisha_Banerjee.pdf"

    def test_handles_a_missing_name(self, class_info):
        result = score_student("123", "", ABHISHA_PDF_SCORES, class_info)
        assert output_filename(result) == "123_unnamed.pdf"


class TestEdgeCases:
    def test_a_student_with_no_marks(self, class_info):
        blank = {q.qno: None for q in class_info.questions}
        result = score_student("999", "Absent Student", blank, class_info)
        text = squash(extract_text(build_pdf(result, class_info)))
        assert "Absent Student" in text
        assert "Strengths of the Student: NA" in text

    def test_a_long_student_name_does_not_break_the_layout(self, class_info):
        result = score_student(
            "1", "Bartholomew Fitzgerald Montgomery Wellington-Smythe", {}, class_info
        )
        data = build_pdf(result, class_info)
        reader = pypdf.PdfReader(__import__("io").BytesIO(data))
        assert len(reader.pages) == 1

    def test_a_paper_with_no_rubric_or_groups(self):
        from app.models import ClassInfo

        info = ClassInfo.model_validate(
            {
                "fullMarks": 10,
                "questions": [{"qno": "1", "marksAllotted": 10, "bloomLevel": "Apply"}],
                "feedbackBands": [
                    {"maxPercent": 100, "feedback": "Good", "areas": "-", "measures": "-"}
                ],
            }
        )
        result = score_student("7", "Solo Question", {"1": 8}, info)
        text = squash(extract_text(build_pdf(result, info)))
        assert "Solo Question" in text
        assert "Assessment Rubrics" not in text
