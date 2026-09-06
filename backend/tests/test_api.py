"""API contract tests (spec §6) and the full batch pipeline (§6, §4.4 item 7).

Drive is stubbed throughout -- these never touch the network.
"""

from __future__ import annotations

import io
import json
import zipfile

import httpx
import pytest

from app.batch import (
    GENERATED,
    NO_MARKS_MATCH,
    SIGNATURE_FAILED,
    SIGNATURE_MISSING,
    generate_batch_sync,
    read_override_zip,
)
from app.defaults import DEFAULT_CLASS_INFO, default_class_info
from app.templates_xlsx import build_marks_template, build_roster_template

fastapi_testclient = pytest.importorskip("fastapi.testclient")
openpyxl = pytest.importorskip("openpyxl")

from app.main import app  # noqa: E402  (imported after the availability check)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128


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
    [
        ["Roll", "Name"],
        ["25371025001", "Abhisha Banerjee"],
        ["25371025003", "Angira Ghosh"],
    ]
)
# Question columns deliberately written as numbers, so "2" is stored as 2.0 -- the
# real-world header shape from Appendix A.9.
MARKS = make_xlsx(
    [
        ["Roll", "Name", "1.a", "1.b", "1.c", "1.d", "1.e", "1.f", 2, 3, 4, 5, 6],
        ["25371025001", "Abhisha Banerjee", 1, 1, 1, None, 1, None, 2, 3, 3, None, None],
        ["25371025003", "Angira Ghosh", 1, 1, 1, None, 1, 1, None, 5, 5, 5, 5],
    ]
)
CLASS_INFO_JSON = json.dumps(DEFAULT_CLASS_INFO)


class TestHealthAndDefaults:
    def test_health(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_defaults_are_valid_class_info(self, client):
        from app.models import ClassInfo

        payload = client.get("/api/defaults").json()
        assert ClassInfo.model_validate(payload).full_marks == 25


class TestTemplates:
    def test_roster_template(self, client):
        response = client.post("/api/templates/roster")
        assert response.status_code == 200
        assert "roster_template.xlsx" in response.headers["content-disposition"]
        sheet = openpyxl.load_workbook(io.BytesIO(response.content)).active
        assert [c.value for c in sheet[1]] == ["Roll", "Name"]

    def test_marks_template_columns_follow_the_question_list(self, client):
        response = client.post("/api/templates/marks", json=DEFAULT_CLASS_INFO)
        assert response.status_code == 200
        sheet = openpyxl.load_workbook(io.BytesIO(response.content))["Marks"]
        headers = [c.value for c in sheet[1]]
        assert headers[:2] == ["Roll", "Name"]
        assert headers[2:] == [q["qno"] for q in DEFAULT_CLASS_INFO["questions"]]

    def test_question_headers_are_text_not_floats(self):
        """Appendix A.9 -- a numeric header would round-trip as 2.0 and stop matching."""
        sheet = openpyxl.load_workbook(io.BytesIO(build_marks_template(default_class_info())))["Marks"]
        assert sheet.cell(row=1, column=9).value == "2"
        assert isinstance(sheet.cell(row=1, column=9).value, str)

    def test_a_custom_question_list_is_respected(self, client):
        payload = {
            **DEFAULT_CLASS_INFO,
            "questions": [{"qno": "Q1", "marksAllotted": 10, "bloomLevel": "Apply"}],
            "questionGroups": [],
        }
        response = client.post("/api/templates/marks", json=payload)
        sheet = openpyxl.load_workbook(io.BytesIO(response.content))["Marks"]
        assert [c.value for c in sheet[1]] == ["Roll", "Name", "Q1"]

    def test_roster_template_round_trips_through_the_parser(self):
        from app.parsing import parse_roster

        roster = parse_roster(build_roster_template(), "roster_template.xlsx")
        assert len(roster.students) == 2
        assert roster.by_roll()["25371025001"].name == "Abhisha Banerjee"


class TestPreview:
    def test_scores_every_student(self, client):
        response = client.post(
            "/api/preview",
            files={"roster": ("roster.xlsx", ROSTER), "marks": ("marks.xlsx", MARKS)},
            data={"class_info": CLASS_INFO_JSON},
        )
        assert response.status_code == 200
        body = response.json()
        by_roll = {s["roll"]: s for s in body["students"]}
        assert by_roll["25371025001"]["total"] == 12
        assert by_roll["25371025001"]["percent"] == 48.0
        assert by_roll["25371025001"]["feedback"] == "Fair Understanding"
        assert by_roll["25371025003"]["total"] == 25

    def test_reports_missing_scores(self, client):
        response = client.post(
            "/api/preview",
            files={"roster": ("roster.xlsx", ROSTER), "marks": ("marks.xlsx", MARKS)},
            data={"class_info": CLASS_INFO_JSON},
        )
        student = next(
            s for s in response.json()["students"] if s["roll"] == "25371025001"
        )
        assert student["missingScores"] == ["1.d", "1.f", "5", "6"]
        assert student["hasSignature"] is None

    def test_a_roster_student_with_no_marks_is_an_error(self, client):
        roster = make_xlsx(
            [["Roll", "Name"], ["25371025001", "Abhisha"], ["99999", "Ghost Student"]]
        )
        response = client.post(
            "/api/preview",
            files={"roster": ("roster.xlsx", roster), "marks": ("marks.xlsx", MARKS)},
            data={"class_info": CLASS_INFO_JSON},
        )
        issues = response.json()["issues"]
        assert any(
            i["roll"] == "99999" and i["level"] == "error" for i in issues
        ), issues

    def test_bad_class_info_is_a_422_not_a_500(self, client):
        response = client.post(
            "/api/preview",
            files={"roster": ("roster.xlsx", ROSTER), "marks": ("marks.xlsx", MARKS)},
            data={"class_info": "{not json"},
        )
        assert response.status_code == 422

    def test_a_legacy_xls_upload_is_rejected_with_advice(self, client):
        response = client.post(
            "/api/preview",
            files={"roster": ("roster.xls", b"\xd0\xcf\x11\xe0"), "marks": ("marks.xlsx", MARKS)},
            data={"class_info": CLASS_INFO_JSON},
        )
        assert response.status_code == 422
        assert "Save As" in response.json()["detail"]


class TestGenerate:
    def test_returns_a_zip_of_pdfs_with_a_manifest(self, client):
        response = client.post(
            "/api/generate",
            files={
                "roster": ("roster.xlsx", ROSTER),
                "marks": ("marks.xlsx", MARKS),
                "teacher_signature": ("sig.png", PNG, "image/png"),
            },
            data={"class_info": CLASS_INFO_JSON},
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"
        assert "Assessment_Reports_" in response.headers["content-disposition"]

        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names = archive.namelist()
            assert "manifest.json" in names
            assert "25371025001_Abhisha_Banerjee.pdf" in names
            assert "25371025003_Angira_Ghosh.pdf" in names
            assert archive.read("25371025001_Abhisha_Banerjee.pdf").startswith(b"%PDF-")

            manifest = json.loads(archive.read("manifest.json"))
            assert manifest["studentCount"] == 2
            assert manifest["generated"] == 2
            assert {s["roll"] for s in manifest["students"]} == {
                "25371025001",
                "25371025003",
            }

    def test_manifest_carries_the_computed_totals(self, client):
        response = client.post(
            "/api/generate",
            files={"roster": ("roster.xlsx", ROSTER), "marks": ("marks.xlsx", MARKS)},
            data={"class_info": CLASS_INFO_JSON},
        )
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
        totals = {s["roll"]: s["total"] for s in manifest["students"]}
        assert totals == {"25371025001": 12, "25371025003": 25}


class TestBatchPipeline:
    """The parts that need a stubbed Drive, driven through generate_batch directly."""

    def _signature_sheet(self, rows: list[list]) -> bytes:
        return make_xlsx(
            [["", "Full Name", "University Roll Number", "Semester", "Department", "Signature Drive Link"]]
            + rows
        )

    def test_fetches_only_the_rolls_in_this_batch(self, tmp_path):
        """§4.4 item 1 -- never fetch all ~760 known students."""
        requested: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested.append(request.url.params.get("id"))
            return httpx.Response(200, content=PNG)

        sheet = self._signature_sheet(
            [
                ["2026-08-30 22:28:33", "Abhisha Banerjee", "25371025001", "Sem 3", "MCA",
                 "https://drive.google.com/file/d/FILE_A/view"],
                ["2026-08-30 22:28:33", "Angira Ghosh", "25371025003", "Sem 3", "MCA",
                 "https://drive.google.com/file/d/FILE_B/view"],
                ["2026-08-30 22:28:33", "Someone Else", "99999999999", "Sem 3", "MCA",
                 "https://drive.google.com/file/d/FILE_C/view"],
            ]
        )
        result = generate_batch_sync(
            roster_bytes=ROSTER,
            marks_bytes=MARKS,
            class_info=default_class_info(),
            signature_sheet=sheet,
            transport=httpx.MockTransport(handler),
            cache=None,
        )
        assert set(requested) == {"FILE_A", "FILE_B"}
        assert "FILE_C" not in requested
        assert all(o.status == GENERATED for o in result.outcomes)
        assert all(o.signature_source == "drive" for o in result.outcomes)

    def test_a_403_is_recorded_and_the_pdf_still_generates(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.params.get("id") == "FILE_B":
                return httpx.Response(403)
            return httpx.Response(200, content=PNG)

        sheet = self._signature_sheet(
            [
                ["2026-08-30 22:28:33", "Abhisha Banerjee", "25371025001", "Sem 3", "MCA",
                 "https://drive.google.com/file/d/FILE_A/view"],
                ["2026-08-30 22:28:33", "Angira Ghosh", "25371025003", "Sem 3", "MCA",
                 "https://drive.google.com/file/d/FILE_B/view"],
            ]
        )
        result = generate_batch_sync(
            roster_bytes=ROSTER,
            marks_bytes=MARKS,
            class_info=default_class_info(),
            signature_sheet=sheet,
            transport=httpx.MockTransport(handler),
            cache=None,
        )
        by_roll = {o.roll: o for o in result.outcomes}
        assert by_roll["25371025003"].status == SIGNATURE_FAILED
        assert "Anyone with the link" in by_roll["25371025003"].detail
        # Still produced -- one broken link must not cost a student their top sheet.
        with zipfile.ZipFile(io.BytesIO(result.zip_bytes)) as archive:
            assert "25371025003_Angira_Ghosh.pdf" in archive.namelist()

    def test_a_student_absent_from_the_signature_form_is_flagged(self):
        sheet = self._signature_sheet(
            [
                ["2026-08-30 22:28:33", "Abhisha Banerjee", "25371025001", "Sem 3", "MCA",
                 "https://drive.google.com/file/d/FILE_A/view"],
            ]
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=PNG)

        result = generate_batch_sync(
            roster_bytes=ROSTER,
            marks_bytes=MARKS,
            class_info=default_class_info(),
            signature_sheet=sheet,
            transport=httpx.MockTransport(handler),
            cache=None,
        )
        by_roll = {o.roll: o for o in result.outcomes}
        assert by_roll["25371025003"].status == SIGNATURE_MISSING

    def test_the_override_zip_wins_over_drive(self):
        """§4.4 item 7 -- the escape hatch for a broken Drive link."""
        fetched: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            fetched.append(request.url.params.get("id"))
            return httpx.Response(200, content=PNG)

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("25371025003.png", PNG)

        sheet = self._signature_sheet(
            [
                ["2026-08-30 22:28:33", "Abhisha Banerjee", "25371025001", "Sem 3", "MCA",
                 "https://drive.google.com/file/d/FILE_A/view"],
                ["2026-08-30 22:28:33", "Angira Ghosh", "25371025003", "Sem 3", "MCA",
                 "https://drive.google.com/file/d/FILE_B/view"],
            ]
        )
        result = generate_batch_sync(
            roster_bytes=ROSTER,
            marks_bytes=MARKS,
            class_info=default_class_info(),
            signature_sheet=sheet,
            student_signatures_zip=buffer.getvalue(),
            transport=httpx.MockTransport(handler),
            cache=None,
        )
        by_roll = {o.roll: o for o in result.outcomes}
        assert by_roll["25371025003"].signature_source == "uploaded-zip"
        # The overridden roll was never fetched from Drive.
        assert fetched == ["FILE_A"]

    def test_manifest_only_reports_issues_about_this_batch(self):
        """The signature workbook covers the whole college; the manifest must not."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=PNG)

        # Two submissions for a student in another class, tied on timestamp with
        # different links -- a real warning, but irrelevant to this batch.
        sheet = self._signature_sheet(
            [
                ["2026-08-30 22:28:33", "Abhisha Banerjee", "25371025001", "Sem 3", "MCA",
                 "https://drive.google.com/file/d/FILE_A/view"],
                ["2026-08-30 22:28:33", "Angira Ghosh", "25371025003", "Sem 3", "MCA",
                 "https://drive.google.com/file/d/FILE_B/view"],
                ["2026-09-01 10:00:00", "Other Person", "88888888888", "Sem 5", "CSE",
                 "https://drive.google.com/file/d/FILE_X/view"],
                ["2026-09-01 10:00:00", "Other Person", "88888888888", "Sem 5", "CSE",
                 "https://drive.google.com/file/d/FILE_Y/view"],
            ]
        )
        result = generate_batch_sync(
            roster_bytes=ROSTER,
            marks_bytes=MARKS,
            class_info=default_class_info(),
            signature_sheet=sheet,
            transport=httpx.MockTransport(handler),
            cache=None,
        )
        assert not any("88888888888" in i.roll for i in result.issues), result.issues

    def test_identical_issues_are_reported_once(self):
        """One workbook uploaded as both the roster and the marks sheet (§A.8).

        Two genuinely different files that each have the swap still report twice --
        the messages are filename-prefixed, so they are not identical.
        """
        swapped = make_xlsx(
            [
                ["Roll", "Name", "1.a", "2"],
                ["Abhisha Banerjee", "25371025001", 1, 5],
                ["Angira Ghosh", "25371025003", 1, 5],
            ]
        )
        result = generate_batch_sync(
            roster_bytes=swapped,
            marks_bytes=swapped,
            class_info=default_class_info(),
            roster_name="AIML.xlsx",
            marks_name="AIML.xlsx",
        )
        swaps = [i for i in result.issues if "swapped" in i.message]
        assert len(swaps) == 1, swaps
        # Both students still resolved, despite the swapped columns.
        assert len(result.outcomes) == 2

    def test_generates_with_no_signature_sources_at_all(self):
        result = generate_batch_sync(
            roster_bytes=ROSTER, marks_bytes=MARKS, class_info=default_class_info()
        )
        assert len(result.outcomes) == 2
        assert all(o.status == GENERATED for o in result.outcomes)


class TestOverrideZip:
    def test_names_are_normalized_to_roll_numbers(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("25371025001.png", b"a")
            archive.writestr("signatures/25371025003.jpg", b"b")
            archive.writestr("25300122014.0.png", b"c")
        images = read_override_zip(buffer.getvalue())
        assert set(images) == {"25371025001", "25371025003", "25300122014"}

    def test_empty_input(self):
        assert read_override_zip(None) == {}
