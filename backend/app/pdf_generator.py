"""Render one filled top sheet per student with ReportLab (spec §7, Appendix A.5).

Vector output with selectable text, not a rasterized screenshot. The layout follows the
reference document ``fixtures/Abhisha Banerjee.pdf`` -- A4, roughly 40pt margins, the
same seven blocks in the same order.

A missing signature never fails a student's PDF; the slot carries a short placeholder
note and the omission is recorded in the manifest instead (§7).
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .models import ClassInfo
from .scoring import StudentResult

PAGE_SIZE = A4
MARGIN = 40
CONTENT_WIDTH = PAGE_SIZE[0] - 2 * MARGIN

GRID_COLOR = colors.black
HEADER_BG = colors.Color(0.91, 0.91, 0.91)

#: Rubric column headings, including the score bands printed in the reference document.
RUBRIC_HEADINGS = (
    "",
    "Criteria",
    "Excellent\n(80–100%)\n(1)",
    "Good\n(60–79%)\n(2)",
    "Satisfactory\n(40–59%)\n(3)",
    "Needs Improvement\n(<40%)\n(4)",
)

MARKS_HEADINGS = (
    "Q. No.",
    "Marks\nAllotted",
    "Marks\nAwarded",
    "CO\nMapping",
    "Bloom’s\nLevel",
    "Total\nMarks",
    "Remarks",
    "AR\nReference",
)

ACKNOWLEDGEMENT = (
    "I have reviewed my evaluated answer script and understand the awarded marks "
    "and feedback."
)


def _styles() -> dict[str, ParagraphStyle]:
    base = ParagraphStyle(
        "base", fontName="Helvetica", fontSize=9, leading=11, alignment=TA_LEFT
    )
    return {
        "university": ParagraphStyle(
            "university", parent=base, fontName="Helvetica-Bold",
            fontSize=12.5, leading=15, alignment=TA_CENTER,
        ),
        "formTitle": ParagraphStyle(
            "formTitle", parent=base, fontName="Helvetica-Bold",
            fontSize=11, leading=14, alignment=TA_CENTER,
        ),
        "formSubtitle": ParagraphStyle(
            "formSubtitle", parent=base, fontName="Helvetica-Oblique",
            fontSize=9, leading=12, alignment=TA_CENTER,
        ),
        "sectionHeading": ParagraphStyle(
            "sectionHeading", parent=base, fontName="Helvetica-Bold",
            fontSize=10, leading=13, spaceBefore=6, spaceAfter=3,
        ),
        "label": ParagraphStyle("label", parent=base, fontName="Helvetica-Bold"),
        "value": base,
        # The rubric cells are text-dense; Paragraph wrapping keeps them inside the
        # cell instead of overflowing it (§7 item 3).
        "cell": ParagraphStyle("cell", parent=base, fontSize=7.5, leading=9),
        "cellHeader": ParagraphStyle(
            "cellHeader", parent=base, fontName="Helvetica-Bold",
            fontSize=7.5, leading=9, alignment=TA_CENTER,
        ),
        "cellCentred": ParagraphStyle(
            "cellCentred", parent=base, fontSize=8, leading=10, alignment=TA_CENTER
        ),
        "body": ParagraphStyle("body", parent=base, fontSize=9.5, leading=13),
        "caption": ParagraphStyle(
            "caption", parent=base, fontSize=8, leading=10, alignment=TA_CENTER
        ),
    }


@dataclass
class SignatureAssets:
    """Images shared by every PDF in a batch, plus this student's own signature."""

    teacher: bytes | None = None
    #: Appendix A.5 -- the reference document carries a college stamp the spec omitted.
    stamp: bytes | None = None
    student: bytes | None = None


def _image(data: bytes | None, max_width: float, max_height: float) -> Image | None:
    """Scale an image into a box, preserving aspect ratio."""
    if not data:
        return None
    try:
        image = Image(io.BytesIO(data))
        width, height = image.imageWidth, image.imageHeight
        if not width or not height:
            return None
        scale = min(max_width / width, max_height / height)
        image.drawWidth = width * scale
        image.drawHeight = height * scale
        return image
    except Exception:
        # A corrupt image must never take a whole batch down (§7).
        return None


def _title_block(class_info: ClassInfo, style: dict) -> list:
    title = class_info.document_title
    return [
        Paragraph(title.university_name, style["university"]),
        Paragraph(title.form_title, style["formTitle"]),
        Paragraph(title.form_subtitle, style["formSubtitle"]),
        Spacer(1, 8),
    ]


def _info_table(class_info: ClassInfo, student: StudentResult, style: dict) -> Table:
    """Four-column label/value grid (§7 item 2).

    Row pairing follows the reference document's reading order: three rows carry a
    single value spanning the remaining three columns, the rest pair two fields.
    """
    label = style["label"]
    value = style["value"]

    def L(text: str) -> Paragraph:
        return Paragraph(text, label)

    def V(text: object) -> Paragraph:
        return Paragraph("" if text is None else str(text), value)

    rows = [
        [L("College Code &amp; Name:"), V(class_info.college_code_name), "", ""],
        [L("Year/Semester:"), V(class_info.year_semester), "", ""],
        [L("Programme:"), V(class_info.programme), L("Subject:"), V(class_info.subject)],
        [L("Paper Code:"), V(class_info.paper_code), L("UPID:"), V(class_info.upid)],
        # §9.10 / A.8: name goes in the name field, roll in the roll field. The
        # reference PDF has these swapped; that is a filling mistake, not the template.
        [
            L("Name of the Student:"),
            V(student.name),
            L("Roll Number:"),
            V(student.roll),
        ],
        [L("Date of Examinations:"), V(class_info.date_of_exam), "", ""],
        [
            L("Subject Teacher:"),
            V(class_info.subject_teacher),
            L("Mobile Number:"),
            V(class_info.mobile_number),
        ],
        [
            L("Full Marks:"),
            V(_number(class_info.full_marks)),
            L("Duration:"),
            V(class_info.duration),
        ],
    ]

    widths = [CONTENT_WIDTH * f for f in (0.22, 0.32, 0.18, 0.28)]
    table = Table(rows, colWidths=widths, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, GRID_COLOR),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                # The three single-value rows span the remaining columns (§7 item 2).
                ("SPAN", (1, 0), (3, 0)),
                ("SPAN", (1, 1), (3, 1)),
                ("SPAN", (1, 5), (3, 5)),
            ]
        )
    )
    return table


def _rubric_table(class_info: ClassInfo, style: dict) -> list:
    if not class_info.rubric:
        return []
    header = [Paragraph(text, style["cellHeader"]) for text in RUBRIC_HEADINGS]
    rows = [header]
    for row in class_info.rubric:
        rows.append(
            [
                Paragraph(row.label, style["cellCentred"]),
                Paragraph(row.criteria, style["cell"]),
                Paragraph(row.excellent, style["cell"]),
                Paragraph(row.good, style["cell"]),
                Paragraph(row.satisfactory, style["cell"]),
                Paragraph(row.needs_improvement, style["cell"]),
            ]
        )
    widths = [CONTENT_WIDTH * f for f in (0.05, 0.19, 0.19, 0.19, 0.19, 0.19)]
    table = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, GRID_COLOR),
                ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return [Paragraph("Assessment Rubrics:", style["sectionHeading"]), table]


def _number(value: float) -> str:
    """Print 25 rather than 25.0, and 12.5 as 12.5."""
    return str(int(value)) if float(value).is_integer() else str(value)


def _marks_table(student: StudentResult, style: dict) -> list:
    header = [Paragraph(text, style["cellHeader"]) for text in MARKS_HEADINGS]
    rows = [header]
    for index, question in enumerate(student.questions):
        rows.append(
            [
                Paragraph(question.qno, style["cellCentred"]),
                Paragraph(_number(question.marks_allotted), style["cellCentred"]),
                Paragraph(question.marks_awarded, style["cellCentred"]),
                Paragraph(question.co_mapping, style["cellCentred"]),
                Paragraph(question.bloom_level, style["cellCentred"]),
                # Only the first row carries the total; the rest are merged into it.
                Paragraph(_number(student.total), style["cellCentred"])
                if index == 0
                else "",
                Paragraph(question.remark, style["cellCentred"]),
                Paragraph(question.ar_reference, style["cellCentred"]),
            ]
        )

    widths = [CONTENT_WIDTH * f for f in (0.09, 0.11, 0.11, 0.11, 0.13, 0.10, 0.20, 0.15)]
    table = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
    style_commands = [
        ("GRID", (0, 0), (-1, -1), 0.5, GRID_COLOR),
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]
    if student.questions:
        # §7 item 4 -- one merged Total Marks cell spanning every question row.
        style_commands.append(("SPAN", (5, 1), (5, -1)))
    table.setStyle(TableStyle(style_commands))
    return [
        Paragraph("Marks Distribution &amp; Mapping (As Applicable)", style["sectionHeading"]),
        table,
    ]


def _signature_cell(
    data: bytes | None, caption: str, style: dict, width: float, date: str
) -> Table:
    """A signature image (or a placeholder), the date, and its caption."""
    image = _image(data, max_width=width * 0.75, max_height=34)
    if image is None:
        top = Paragraph(
            "<i>Signature not provided</i>",
            ParagraphStyle("missing", parent=style["caption"], textColor=colors.grey),
        )
    else:
        top = image
    rows = [[top], [Paragraph(date, style["caption"])], [Paragraph(caption, style["caption"])]]
    table = Table(rows, colWidths=[width], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ]
        )
    )
    return table


def _feedback_block(
    class_info: ClassInfo, student: StudentResult, assets: SignatureAssets, style: dict
) -> list:
    """Examiner's feedback with the teacher signature alongside (§7 item 5)."""
    text_width = CONTENT_WIDTH * 0.62
    sign_width = CONTENT_WIDTH * 0.38

    feedback_text = [
        Paragraph("<b>Examiner’s Feedback:</b>", style["body"]),
        Spacer(1, 3),
        Paragraph(f"<b>Strengths of the Student:</b> {student.feedback}", style["body"]),
        Spacer(1, 3),
        Paragraph(f"<b>Areas for Improvement:</b> {student.areas}", style["body"]),
        Spacer(1, 3),
        Paragraph(
            f"<b>Suggested Corrective Measures:</b> {student.measures}", style["body"]
        ),
    ]
    examiner = _signature_cell(
        assets.teacher,
        "Signature of the Examiner with date",
        style,
        sign_width,
        class_info.date_of_exam,
    )
    table = Table(
        [[feedback_text, examiner]], colWidths=[text_width, sign_width], hAlign="LEFT"
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (0, 0), "TOP"),
                ("VALIGN", (1, 0), (1, 0), "BOTTOM"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return [Spacer(1, 8), table]


def _acknowledgement_block(
    class_info: ClassInfo, assets: SignatureAssets, style: dict
) -> list:
    """Acknowledgement line, student signature left, college stamp right (§7, A.5)."""
    sign_width = CONTENT_WIDTH * 0.34
    stamp_width = CONTENT_WIDTH * 0.24
    spacer_width = CONTENT_WIDTH - sign_width - stamp_width

    student_sign = _signature_cell(
        assets.student,
        "Signature of the student with date",
        style,
        sign_width,
        class_info.date_of_exam,
    )
    stamp = _image(assets.stamp, max_width=stamp_width * 0.8, max_height=48) or ""

    row = Table(
        [[student_sign, "", stamp]],
        colWidths=[sign_width, spacer_width, stamp_width],
        hAlign="LEFT",
    )
    row.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                ("ALIGN", (2, 0), (2, 0), "CENTER"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return [
        Spacer(1, 10),
        Paragraph(ACKNOWLEDGEMENT, style["body"]),
        Spacer(1, 6),
        row,
    ]


def build_pdf(
    student: StudentResult,
    class_info: ClassInfo,
    assets: SignatureAssets | None = None,
) -> bytes:
    """Render one student's top sheet and return the PDF bytes."""
    assets = assets or SignatureAssets()
    style = _styles()
    buffer = io.BytesIO()

    document = SimpleDocTemplate(
        buffer,
        pagesize=PAGE_SIZE,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN * 0.6,
        title=f"Top Sheet - {student.name or student.roll}",
        author=class_info.subject_teacher or "Examiner",
        subject=class_info.document_title.form_title,
    )

    story: list = []
    story += _title_block(class_info, style)
    story.append(_info_table(class_info, student, style))
    story += _rubric_table(class_info, style)
    story += _marks_table(student, style)
    story += _feedback_block(class_info, student, assets, style)
    # The acknowledgement and the signatures below it must not be split across pages.
    story.append(KeepTogether(_acknowledgement_block(class_info, assets, style)))

    document.build(story)
    return buffer.getvalue()


def output_filename(student: StudentResult) -> str:
    """``<roll>_<name>.pdf`` with the name slugified (spec §6)."""
    from .normalize import slugify_name

    roll = student.roll or "unknown"
    return f"{roll}_{slugify_name(student.name)}.pdf"
