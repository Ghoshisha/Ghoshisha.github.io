"""The MAKAUT CA2 top-sheet defaults from spec §4.1.

Seeds the frontend form so a teacher using this exact form can skip straight to
uploads, and gives the tests a realistic ClassInfo.

Bloom levels follow §4.1 and the printed reference PDF, not ``AIML.xlsx!Sheet2`` --
the two disagree, and since AR Reference is now derived from Bloom (Appendix A.2) the
choice is visible in the output. Appendix A.11 flags this for the teacher to confirm.
"""

from __future__ import annotations

from .models import ClassInfo

DEFAULT_CLASS_INFO: dict = {
    "documentTitle": {
        "universityName": "Maulana Abul Kalam Azad University of Technology, West Bengal",
        "formTitle": "Top Sheet for CA2 Marks Submission",
        "formSubtitle": "(Written Test as a part of Continuous Assessment)",
    },
    "collegeCodeName": "253, Supreme Knowledge Foundation Group of Institutions",
    "yearSemester": "3rd",
    "programme": "Master of Computer Application",
    "subject": "Basic Data Science",
    "paperCode": "MCAN-E304F",
    "upid": "3887",
    "dateOfExam": "01/09/2026",
    "subjectTeacher": "Isha Ghosh",
    "mobileNumber": "7439399035",
    "fullMarks": 25,
    "duration": "1 Hour",
    "rubric": [
        {
            "label": "A",
            "criteria": "Conceptual Understanding",
            "excellent": "Complete accuracy, deep insight; accurate and logical application",
            "good": "Mostly correct, minor gaps; minor errors in application",
            "satisfactory": "Basic understanding; limited application ability",
            "needsImprovement": "Poor understanding; incorrect approach",
        },
        {
            "label": "B",
            "criteria": "Application/Problem Solving",
            "excellent": "Complete accuracy, deep insight; accurate and logical application",
            "good": "Mostly correct, minor gaps; minor errors in application",
            "satisfactory": "Basic understanding; limited application ability",
            "needsImprovement": "Poor understanding; incorrect approach",
        },
        {
            "label": "C",
            "criteria": "Presentation & Clarity",
            "excellent": "Well-structured, clear steps",
            "good": "Mostly clear",
            "satisfactory": "Some lack of clarity",
            "needsImprovement": "Poor presentation",
        },
        {
            "label": "D",
            "criteria": "Analytical Ability",
            "excellent": "Strong reasoning and justification",
            "good": "Adequate reasoning",
            "satisfactory": "Limited reasoning",
            "needsImprovement": "No logical justification",
        },
    ],
    "questions": [
        {"qno": "1.a", "marksAllotted": 1, "coMapping": "CO3", "bloomLevel": "Remember"},
        {"qno": "1.b", "marksAllotted": 1, "coMapping": "CO2", "bloomLevel": "Remember"},
        {"qno": "1.c", "marksAllotted": 1, "coMapping": "CO2", "bloomLevel": "Understand"},
        {"qno": "1.d", "marksAllotted": 1, "coMapping": "CO2", "bloomLevel": "Understand"},
        {"qno": "1.e", "marksAllotted": 1, "coMapping": "CO3", "bloomLevel": "Remember"},
        {"qno": "1.f", "marksAllotted": 1, "coMapping": "CO2", "bloomLevel": "Understand"},
        {"qno": "2", "marksAllotted": 5, "coMapping": "CO3", "bloomLevel": "Apply"},
        {"qno": "3", "marksAllotted": 5, "coMapping": "CO3", "bloomLevel": "Understand"},
        {"qno": "4", "marksAllotted": 5, "coMapping": "CO1", "bloomLevel": "Understand"},
        {"qno": "5", "marksAllotted": 5, "coMapping": "CO3", "bloomLevel": "Apply"},
        {"qno": "6", "marksAllotted": 5, "coMapping": "CO2", "bloomLevel": "Apply"},
    ],
    # Appendix A.1 -- recovered from the sheet's Total formula. 5x1 + 4x5 = 25 = Full
    # Marks, which is why the paper allots 30 marks but is out of 25.
    "questionGroups": [
        {
            "label": "Section 1 (best 5 of 6)",
            "questions": ["1.a", "1.b", "1.c", "1.d", "1.e", "1.f"],
            "countBest": 5,
        },
        {
            "label": "Section 2 (best 4 of 5)",
            "questions": ["2", "3", "4", "5", "6"],
            "countBest": 4,
        },
    ],
    "feedbackBands": [
        {
            "maxPercent": 20,
            "feedback": "Needs Improvement",
            "areas": "Improve Fundamentals",
            "measures": "Revise Fundamentals",
        },
        {
            "maxPercent": 40,
            "feedback": "Basic Knowledge",
            "areas": "Improve Basic Concepts",
            "measures": "Practice Basic Concepts",
        },
        {
            "maxPercent": 60,
            "feedback": "Fair Understanding",
            "areas": "Improve Conceptual Understanding",
            "measures": "Practice Concept Application",
        },
        {
            "maxPercent": 80,
            "feedback": "Good Clarity",
            "areas": "Improve Application Skills",
            "measures": "Develop Analytical Skills",
        },
        {
            "maxPercent": 100,
            "feedback": "Excellent Clarity",
            "areas": "Refine Advanced Concepts",
            "measures": "Refine Advanced Skills",
        },
    ],
    "arReferenceMode": "corrected",
}


def default_class_info() -> ClassInfo:
    return ClassInfo.model_validate(DEFAULT_CLASS_INFO)
