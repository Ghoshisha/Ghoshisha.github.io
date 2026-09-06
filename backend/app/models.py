"""Pydantic schemas for the batch request payload (spec §4.1, Appendix A.1/A.2).

The frontend posts one ``ClassInfo`` per batch as a JSON *string* inside multipart form
data (§9.12), never as a JSON body.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CamelModel(BaseModel):
    """Base model accepting the camelCase keys the frontend sends."""

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.title() for part in rest)


class DocumentTitle(CamelModel):
    model_config = ConfigDict(
        populate_by_name=True, str_strip_whitespace=True, alias_generator=_camel
    )

    university_name: str = (
        "Maulana Abul Kalam Azad University of Technology, West Bengal"
    )
    form_title: str = "Top Sheet for CA2 Marks Submission"
    form_subtitle: str = "(Written Test as a part of Continuous Assessment)"


class RubricRow(CamelModel):
    model_config = ConfigDict(
        populate_by_name=True, str_strip_whitespace=True, alias_generator=_camel
    )

    label: str
    criteria: str
    excellent: str = ""
    good: str = ""
    satisfactory: str = ""
    needs_improvement: str = ""


class Question(CamelModel):
    """One row of the Marks Distribution & Mapping table.

    ``ar_reference`` is deliberately absent -- it is derived per student from the score
    and this question's Bloom level (Appendix A.2), not supplied by the teacher.
    """

    model_config = ConfigDict(
        populate_by_name=True, str_strip_whitespace=True, alias_generator=_camel
    )

    qno: str
    marks_allotted: float = Field(gt=0)
    co_mapping: str = ""
    bloom_level: str = ""

    @field_validator("qno", mode="before")
    @classmethod
    def _qno_to_text(cls, value: object) -> str:
        """Accept ``2`` and ``2.0`` for question "2" -- headers arrive as floats (A.9)."""
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value).strip()


class QuestionGroup(CamelModel):
    """A set of questions scored "best N of M" (Appendix A.1).

    The teacher's sheet drops the lowest score in each group, but only once every
    question in the group has been attempted -- ``SUM - SMALL(range,1)`` guarded by
    ``COUNT(range) > count_best``. A question named in no group always counts.
    """

    model_config = ConfigDict(
        populate_by_name=True, str_strip_whitespace=True, alias_generator=_camel
    )

    label: str = ""
    questions: list[str]
    count_best: int = Field(gt=0)

    @field_validator("questions", mode="before")
    @classmethod
    def _qnos_to_text(cls, value: object) -> object:
        if isinstance(value, list):
            return [
                str(int(v)) if isinstance(v, float) and v.is_integer() else str(v).strip()
                for v in value
            ]
        return value

    @model_validator(mode="after")
    def _count_best_fits(self) -> "QuestionGroup":
        if self.count_best > len(self.questions):
            raise ValueError(
                f"questionGroup {self.label or self.questions!r}: countBest "
                f"({self.count_best}) exceeds its {len(self.questions)} questions"
            )
        return self


class FeedbackBand(CamelModel):
    model_config = ConfigDict(
        populate_by_name=True, str_strip_whitespace=True, alias_generator=_camel
    )

    max_percent: float
    feedback: str
    areas: str
    measures: str


class ClassInfo(CamelModel):
    model_config = ConfigDict(
        populate_by_name=True, str_strip_whitespace=True, alias_generator=_camel
    )

    document_title: DocumentTitle = Field(default_factory=DocumentTitle)
    college_code_name: str = ""
    year_semester: str = ""
    programme: str = ""
    subject: str = ""
    paper_code: str = ""
    upid: str = ""
    date_of_exam: str = ""
    subject_teacher: str = ""
    mobile_number: str = ""
    full_marks: float = Field(default=25, gt=0)
    duration: str = ""
    rubric: list[RubricRow] = Field(default_factory=list)
    questions: list[Question]
    question_groups: list[QuestionGroup] = Field(default_factory=list)
    feedback_bands: list[FeedbackBand] = Field(default_factory=list)

    # Appendix A.2: the teacher's own sheet computes AR Reference through a broken
    # row-wise Bloom lookup that yields "C" for every question but the first. "corrected"
    # uses each question's real Bloom level. "legacy" is kept only as an escape hatch for
    # reissuing a document that must match one already handed to a student.
    ar_reference_mode: Literal["corrected", "legacy"] = "corrected"

    @model_validator(mode="after")
    def _groups_reference_real_questions(self) -> "ClassInfo":
        known = {q.qno for q in self.questions}
        for group in self.question_groups:
            unknown = [q for q in group.questions if q not in known]
            if unknown:
                raise ValueError(
                    f"questionGroup {group.label or ''!r} names unknown questions: "
                    f"{unknown}"
                )
        seen: dict[str, str] = {}
        for group in self.question_groups:
            for qno in group.questions:
                if qno in seen:
                    raise ValueError(
                        f"question {qno!r} appears in two groups "
                        f"({seen[qno]!r} and {group.label!r})"
                    )
                seen[qno] = group.label
        return self

    @field_validator("feedback_bands")
    @classmethod
    def _bands_sorted(cls, bands: list[FeedbackBand]) -> list[FeedbackBand]:
        """Band lookup takes the first band whose ceiling clears the score (§5)."""
        return sorted(bands, key=lambda b: b.max_percent)
