"""The per-student dashboard flow: load the class, edit one student, generate one PDF.

The point of /api/score is that the browser never re-implements the scoring rules, so
these tests check that an edit made in the dashboard produces exactly what the PDF does.
"""

from __future__ import annotations

import io
import json

import httpx
import pytest

from app.defaults import DEFAULT_CLASS_INFO

fastapi_testclient = pytest.importorskip("fastapi.testclient")
openpyxl = pytest.importorskip("openpyxl")
pypdf = pytest.importorskip("pypdf")

from app.main import app  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128
CLASS_INFO_JSON = json.dumps(DEFAULT_CLASS_INFO)


@pytest.fixture(scope="module")
def client():
    with fastapi_testclient.TestClient(app) as test_client:
        yield test_client


def make_xlsx(rows: list[list]) -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


ROSTER = make_xlsx(
    [["Roll", "Name"], ["25371025001", "Abhisha Banerjee"], ["25371025003", "Angira Ghosh"]]
)
MARKS = make_xlsx(
    [
        ["Roll", "Name", "1.a", "1.b", "1.c", "1.d", "1.e", "1.f", 2, 3, 4, 5, 6],
        ["25371025001", "Abhisha Banerjee", 1, 1, 1, None, 1, None, 2, 3, 3, None, None],
        ["25371025003", "Angira Ghosh", 1, 1, 1, None, 1, 1, None, 5, 5, 5, 5],
    ]
)
SIGNATURES = make_xlsx(
    [
        ["", "Full Name", "University Roll Number", "Semester", "Department", "Signature Drive Link"],
        ["2026-08-30 22:28:33", "Abhisha Banerjee", "25371025001", "Sem 3", "MCA",
         "https://drive.google.com/file/d/FILE_A/view"],
    ]
)


def extract_text(data: bytes) -> str:
    reader = pypdf.PdfReader(io.BytesIO(data))
    return " ".join(page.extract_text() for page in reader.pages)


class TestPreviewFeedsTheDashboard:
    def test_returns_editable_scores_per_student(self, client):
        response = client.post(
            "/api/preview",
            files={"roster": ("roster.xlsx", ROSTER), "marks": ("marks.xlsx", MARKS)},
            data={"class_info": CLASS_INFO_JSON},
        )
        assert response.status_code == 200
        student = next(
            s for s in response.json()["students"] if s["roll"] == "25371025001"
        )
        # The marks the teacher will edit, as the scoring rules parsed them.
        assert student["scores"] == {
            "1.a": 1, "1.b": 1, "1.c": 1, "1.d": None, "1.e": 1, "1.f": None,
            "2": 2, "3": 3, "4": 3, "5": None, "6": None,
        }

    def test_returns_derived_rows_so_the_grid_renders_immediately(self, client):
        response = client.post(
            "/api/preview",
            files={"roster": ("roster.xlsx", ROSTER), "marks": ("marks.xlsx", MARKS)},
            data={"class_info": CLASS_INFO_JSON},
        )
        student = next(
            s for s in response.json()["students"] if s["roll"] == "25371025001"
        )
        by_qno = {q["qno"]: q for q in student["questions"]}
        assert by_qno["2"]["remark"] == "Partially Correct"
        assert by_qno["2"]["arReference"] == "B3"
        assert student["total"] == 12

    def test_signature_status_is_known_before_generating(self, client):
        response = client.post(
            "/api/preview",
            files={
                "roster": ("roster.xlsx", ROSTER),
                "marks": ("marks.xlsx", MARKS),
                "signature_sheet": ("Signature.xlsx", SIGNATURES),
            },
            data={"class_info": CLASS_INFO_JSON},
        )
        by_roll = {s["roll"]: s for s in response.json()["students"]}
        assert by_roll["25371025001"]["hasSignature"] is True
        assert by_roll["25371025001"]["driveId"] == "FILE_A"
        # Angira never submitted the form -- visible now, not after the batch runs.
        assert by_roll["25371025003"]["hasSignature"] is False
        assert by_roll["25371025003"]["driveId"] is None

    def test_without_a_signature_sheet_the_status_is_unknown(self, client):
        response = client.post(
            "/api/preview",
            files={"roster": ("roster.xlsx", ROSTER), "marks": ("marks.xlsx", MARKS)},
            data={"class_info": CLASS_INFO_JSON},
        )
        assert all(s["hasSignature"] is None for s in response.json()["students"])


class TestScoreEndpoint:
    def test_recomputes_an_edited_mark(self, client):
        """Raising Q2 from 2 to 5 changes its remark, its AR digit and the total."""
        response = client.post(
            "/api/score",
            json={
                "classInfo": DEFAULT_CLASS_INFO,
                "roll": "25371025001",
                "name": "Abhisha Banerjee",
                "scores": {
                    "1.a": 1, "1.b": 1, "1.c": 1, "1.d": None, "1.e": 1, "1.f": None,
                    "2": 5, "3": 3, "4": 3, "5": None, "6": None,
                },
            },
        )
        assert response.status_code == 200
        body = response.json()
        by_qno = {q["qno"]: q for q in body["questions"]}
        assert by_qno["2"]["remark"] == "Correct"
        assert by_qno["2"]["arReference"] == "B1"
        assert body["total"] == 15
        assert body["feedback"] == "Fair Understanding"

    def test_an_edit_can_move_the_feedback_band(self, client):
        response = client.post(
            "/api/score",
            json={
                "classInfo": DEFAULT_CLASS_INFO,
                "roll": "1",
                "name": "Test",
                "scores": {
                    "1.a": 1, "1.b": 1, "1.c": 1, "1.d": 1, "1.e": 1, "1.f": 1,
                    "2": 5, "3": 5, "4": 5, "5": 5, "6": 5,
                },
            },
        )
        body = response.json()
        # Best 5 of 6 plus best 4 of 5 -- a perfect paper is exactly full marks.
        assert body["total"] == 25
        assert body["feedback"] == "Excellent Clarity"

    def test_clearing_a_mark_makes_it_na_not_zero(self, client):
        response = client.post(
            "/api/score",
            json={
                "classInfo": DEFAULT_CLASS_INFO,
                "roll": "1",
                "name": "Test",
                "scores": {"1.a": None, "2": 0},
            },
        )
        by_qno = {q["qno"]: q for q in response.json()["questions"]}
        assert by_qno["1.a"]["remark"] == "NA"
        assert by_qno["2"]["remark"] == "Wrong"

    def test_rejects_a_bad_body(self, client):
        assert client.post("/api/score", json={"classInfo": {}, "scores": []}).status_code == 422

    def test_matches_what_the_pdf_renders(self, client):
        """The reason scoring is not reimplemented in the browser."""
        scores = {
            "1.a": 1, "1.b": 1, "1.c": 1, "1.d": 0.5, "1.e": 1, "1.f": None,
            "2": 4, "3": 3, "4": 3, "5": None, "6": None,
        }
        scored = client.post(
            "/api/score",
            json={"classInfo": DEFAULT_CLASS_INFO, "roll": "1", "name": "T", "scores": scores},
        ).json()

        pdf = client.post(
            "/api/generate-one",
            data={
                "class_info": CLASS_INFO_JSON,
                "student": json.dumps({"roll": "1", "name": "T", "scores": scores}),
            },
        )
        text = " ".join(extract_text(pdf.content).split())
        assert f"Strengths of the Student: {scored['feedback']}" in text
        assert pdf.headers["x-student-total"] == str(scored["total"])


class TestGenerateOne:
    def test_returns_a_single_pdf(self, client):
        response = client.post(
            "/api/generate-one",
            data={
                "class_info": CLASS_INFO_JSON,
                "student": json.dumps(
                    {
                        "roll": "25371025001",
                        "name": "Abhisha Banerjee",
                        "scores": {"1.a": 1, "2": 5},
                    }
                ),
            },
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert (
            "25371025001_Abhisha_Banerjee.pdf" in response.headers["content-disposition"]
        )
        assert response.content.startswith(b"%PDF-")

    def test_uses_the_marks_the_teacher_corrected(self, client):
        """The whole point: what is generated is what was on screen, not the file."""
        response = client.post(
            "/api/generate-one",
            data={
                "class_info": CLASS_INFO_JSON,
                "student": json.dumps(
                    {
                        "roll": "25371025001",
                        "name": "Abhisha Banerjee",
                        # Q2 corrected upward from the 2 in the spreadsheet.
                        "scores": {
                            "1.a": 1, "1.b": 1, "1.c": 1, "1.d": None, "1.e": 1,
                            "1.f": None, "2": 5, "3": 3, "4": 3, "5": None, "6": None,
                        },
                    }
                ),
            },
        )
        assert response.headers["x-student-total"] == "15.0"
        text = " ".join(extract_text(response.content).split())
        assert "Abhisha Banerjee" in text

    def test_embeds_a_manually_uploaded_signature(self, client):
        response = client.post(
            "/api/generate-one",
            data={
                "class_info": CLASS_INFO_JSON,
                "student": json.dumps({"roll": "7", "name": "Manual", "scores": {"1.a": 1}}),
            },
            files={"student_signature": ("sig.png", PNG, "image/png")},
        )
        assert response.status_code == 200
        assert response.headers["x-signature-status"] == "embedded"

    def test_no_signature_still_produces_a_pdf(self, client):
        response = client.post(
            "/api/generate-one",
            data={
                "class_info": CLASS_INFO_JSON,
                "student": json.dumps({"roll": "7", "name": "Nobody", "scores": {"1.a": 1}}),
            },
        )
        assert response.status_code == 200
        assert response.headers["x-signature-status"] == "no signature supplied"
        assert "Signature not provided" in " ".join(extract_text(response.content).split())

    def test_a_missing_roll_is_rejected(self, client):
        response = client.post(
            "/api/generate-one",
            data={
                "class_info": CLASS_INFO_JSON,
                "student": json.dumps({"name": "No Roll", "scores": {}}),
            },
        )
        assert response.status_code == 422

    def test_bad_student_json_is_a_422(self, client):
        response = client.post(
            "/api/generate-one",
            data={"class_info": CLASS_INFO_JSON, "student": "{nope"},
        )
        assert response.status_code == 422


class TestSignaturePreviewEndpoint:
    def test_serves_the_image_for_the_dashboard(self, client, monkeypatch):
        import app.main as main

        async def fake_fetch(wanted, **kwargs):
            from app.drive_fetch import FetchResult

            return {"one": FetchResult("one", "FILE_A", PNG, "image/png")}

        monkeypatch.setattr(main, "fetch_signatures", fake_fetch)
        response = client.post("/api/signature", json={"driveId": "FILE_A"})
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content == PNG

    def test_an_unshared_link_reports_why(self, client, monkeypatch):
        import app.main as main

        async def fake_fetch(wanted, **kwargs):
            from app.drive_fetch import FetchResult

            return {
                "one": FetchResult(
                    "one", "FILE_B", error="signature not accessible - check sharing"
                )
            }

        monkeypatch.setattr(main, "fetch_signatures", fake_fetch)
        response = client.post("/api/signature", json={"driveId": "FILE_B"})
        assert response.status_code == 404
        assert "sharing" in response.json()["detail"]

    def test_requires_a_drive_id(self, client):
        assert client.post("/api/signature", json={}).status_code == 422
