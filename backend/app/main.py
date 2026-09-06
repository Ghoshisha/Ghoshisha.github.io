"""FastAPI application (spec §6).

Stateless by design: upload, process, return a file. No database, no auth, no stored
history (§10).

The primary workflow is per student: the teacher uploads the sheets once, pulls up one
student at a time, corrects anything wrong, and generates that student's top sheet.
``/api/preview`` loads everyone, ``/api/score`` re-derives one student as marks are
edited, and ``/api/generate-one`` renders a single PDF. ``/api/generate`` still produces
the whole batch as a ZIP for when the class is known to be correct.

Scoring never happens in the browser: the rules that must be right (best-N-of-M totals,
the three-zone remark, derived AR references) live here and are reached over HTTP, so
there is only one implementation of them.

Note ``class_info`` arrives as a JSON *string* inside multipart form data on the
file-upload endpoints, never as a JSON request body (§9.12).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from .batch import generate_batch
from .defaults import DEFAULT_CLASS_INFO
from .drive_fetch import ImageCache, fetch_signatures
from .models import ClassInfo
from .normalize import normalize_roll
from .parsing import SpreadsheetError, parse_marks, parse_roster
from .pdf_generator import SignatureAssets, build_pdf, output_filename
from .scoring import StudentResult, parse_score, score_student
from .signatures import ParsedSignatures, parse_signature_workbook
from .templates_xlsx import build_marks_template, build_roster_template

logger = logging.getLogger(__name__)

XLSX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

app = FastAPI(
    title="Assessment Top-Sheet PDF Generator",
    version="1.1.0",
    description="Review and generate MAKAUT CA2 top sheets, one student at a time.",
)


def _allowed_origins() -> list[str]:
    """CORS origins for the GitHub Pages frontend (spec §2, §11).

    ``ALLOWED_ORIGINS`` is a comma-separated list set on the Render service. The
    localhost defaults keep `npm run dev` working without configuration.
    """
    configured = os.environ.get("ALLOWED_ORIGINS", "").strip()
    if configured:
        return [origin.strip() for origin in configured.split(",") if origin.strip()]
    return [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-Generated-Count"],
)

#: Process-lifetime cache of fetched signatures, keyed by Drive file ID (§4.4 item 5).
#: In the per-student flow the same signature is often fetched twice -- once to show the
#: teacher, once to embed -- so this matters more here than in the batch flow.
_image_cache = ImageCache()


def _parse_class_info(raw: str) -> ClassInfo:
    """Decode the multipart ``class_info`` field, reporting bad input as a 422."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(422, f"class_info is not valid JSON: {exc}")
    try:
        return ClassInfo.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(422, f"class_info is not valid: {exc.errors()}")


def _validate(payload: dict, field: str = "classInfo") -> ClassInfo:
    try:
        return ClassInfo.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(422, f"{field} is not valid: {exc.errors()}")


async def _read(upload: UploadFile | None) -> bytes | None:
    return await upload.read() if upload is not None else None


def _student_payload(result: StudentResult, scores: dict) -> dict:
    """Everything the dashboard needs to show and edit one student.

    ``scores`` is echoed back as parsed numbers so the editor starts from what the
    scoring rules actually saw, not from whatever the spreadsheet cell happened to hold.
    """
    return {
        "roll": result.roll,
        "name": result.name,
        "total": result.total,
        "percent": result.percent,
        "feedback": result.feedback,
        "areas": result.areas,
        "measures": result.measures,
        "missingScores": result.missing_scores,
        "scores": {qno: parse_score(value) for qno, value in scores.items()},
        "questions": [
            {
                "qno": q.qno,
                "marksAllotted": q.marks_allotted,
                "marksAwarded": q.marks_awarded,
                "coMapping": q.co_mapping,
                "bloomLevel": q.bloom_level,
                "remark": q.remark,
                "arReference": q.ar_reference,
            }
            for q in result.questions
        ],
    }


def _signature_payload(roll: str, signatures: ParsedSignatures | None) -> dict:
    """What is known about a student's signature, before fetching the image itself."""
    if signatures is None:
        return {"hasSignature": None, "driveId": None, "signatureName": ""}
    row = signatures.by_roll.get(normalize_roll(roll))
    if row is None:
        return {"hasSignature": False, "driveId": None, "signatureName": ""}
    return {
        "hasSignature": bool(row.drive_id),
        "driveId": row.drive_id,
        "signatureName": row.name,
        "submittedAt": row.timestamp.isoformat() if row.timestamp else None,
    }


@app.get("/api/health")
async def health() -> dict:
    """Also used by the frontend to pre-warm a sleeping Render instance (§9.11)."""
    return {"status": "ok"}


@app.get("/api/defaults")
async def defaults() -> dict:
    """The §4.1 MAKAUT defaults, so the frontend form arrives pre-filled."""
    return DEFAULT_CLASS_INFO


@app.post("/api/templates/roster")
async def roster_template() -> Response:
    return Response(
        content=build_roster_template(),
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="roster_template.xlsx"'},
    )


@app.post("/api/templates/marks")
async def marks_template(class_info: dict = Body(default=None)) -> Response:
    """Built from the posted question list so the columns match this batch (§6)."""
    info = _validate(class_info) if class_info else ClassInfo.model_validate(DEFAULT_CLASS_INFO)
    return Response(
        content=build_marks_template(info),
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="marks_template.xlsx"'},
    )


@app.post("/api/preview")
async def preview(
    roster: UploadFile = File(...),
    marks: UploadFile = File(...),
    class_info: str = Form(...),
    signature_sheet: UploadFile | None = File(None),
) -> JSONResponse:
    """Load the whole class: every student, their marks, and their signature status.

    This is what fills the dashboard's student list. ``signature_sheet`` is optional --
    supplying it fills in ``hasSignature`` so missing signatures are visible *before*
    anything is generated, rather than turning up in the manifest afterwards (§6).
    """
    info = _parse_class_info(class_info)
    try:
        parsed_roster = parse_roster(await roster.read(), roster.filename or "roster")
        parsed_marks = parse_marks(await marks.read(), info, marks.filename or "marks")
        signature_bytes = await _read(signature_sheet)
        signatures = (
            parse_signature_workbook(signature_bytes, signature_sheet.filename or "signatures")
            if signature_bytes
            else None
        )
    except SpreadsheetError as exc:
        raise HTTPException(422, str(exc))

    issues = [i.as_dict() for i in parsed_roster.issues + parsed_marks.issues]
    students: list[dict] = []
    seen: set[str] = set()

    for entry in parsed_roster.students:
        scores = parsed_marks.scores.get(entry.roll)
        if scores is None:
            issues.append(
                {
                    "roll": entry.raw_roll,
                    "name": entry.name,
                    "level": "error",
                    "message": "No matching row in the marks sheet.",
                }
            )
            continue
        seen.add(entry.roll)
        result = score_student(entry.raw_roll, entry.name, scores, info)
        students.append(
            {**_student_payload(result, scores), **_signature_payload(entry.roll, signatures)}
        )

    for roll, scores in parsed_marks.scores.items():
        if roll in seen:
            continue
        raw = parsed_marks.raw_rolls.get(roll, roll)
        issues.append(
            {
                "roll": raw,
                "name": "",
                "level": "warning",
                "message": "In the marks sheet but not the roster; the name will be blank.",
            }
        )
        result = score_student(raw, "", scores, info)
        students.append(
            {**_student_payload(result, scores), **_signature_payload(roll, signatures)}
        )

    if signatures is not None:
        # Only signature problems concerning students in this class -- the workbook
        # covers the whole college (Appendix A.7).
        rolls = {normalize_roll(s["roll"]) for s in students}
        issues.extend(
            i.as_dict()
            for i in signatures.issues
            if not i.roll or normalize_roll(i.roll) in rolls
        )

    return JSONResponse({"students": students, "issues": issues})


@app.post("/api/score")
async def score(payload: dict = Body(...)) -> JSONResponse:
    """Re-derive one student from edited marks.

    Called as the teacher types in the dashboard, so Remarks, AR Reference, the total
    and the feedback band update from the same code that renders the PDF. The browser
    never computes any of it.

    Body: ``{classInfo, roll, name, scores: {qno: number|null}}``
    """
    info = _validate(payload.get("classInfo") or {})
    scores = payload.get("scores") or {}
    if not isinstance(scores, dict):
        raise HTTPException(422, "scores must be an object of {questionNumber: mark}")

    result = score_student(
        str(payload.get("roll") or ""), str(payload.get("name") or ""), scores, info
    )
    return JSONResponse(_student_payload(result, scores))


@app.post("/api/signature")
async def signature_image(payload: dict = Body(...)) -> Response:
    """Fetch one signature so the dashboard can show it before generating.

    Body: ``{driveId}``. Cached, so showing it and then embedding it costs one fetch.
    """
    drive_id = str(payload.get("driveId") or "").strip()
    if not drive_id:
        raise HTTPException(422, "driveId is required")

    results = await fetch_signatures({"one": drive_id}, cache=_image_cache)
    result = results["one"]
    if not result.ok:
        raise HTTPException(404, result.error or "signature could not be retrieved")
    return Response(
        content=result.data,
        media_type=result.media_type or "image/png",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@app.post("/api/generate-one")
async def generate_one(
    class_info: str = Form(...),
    student: str = Form(...),
    drive_id: str | None = Form(None),
    teacher_signature: UploadFile | None = File(None),
    college_stamp: UploadFile | None = File(None),
    student_signature: UploadFile | None = File(None),
) -> Response:
    """Render one student's top sheet from marks the teacher has just confirmed.

    ``student`` is a JSON string ``{roll, name, scores}``. An uploaded
    ``student_signature`` wins over ``drive_id``, which is the per-student version of
    the batch flow's override ZIP (§4.4 item 7).
    """
    info = _parse_class_info(class_info)
    try:
        student_data = json.loads(student)
    except json.JSONDecodeError as exc:
        raise HTTPException(422, f"student is not valid JSON: {exc}")
    if not isinstance(student_data, dict):
        raise HTTPException(422, "student must be a JSON object")

    roll = str(student_data.get("roll") or "").strip()
    if not roll:
        raise HTTPException(422, "student.roll is required")
    scores = student_data.get("scores") or {}
    if not isinstance(scores, dict):
        raise HTTPException(422, "student.scores must be an object")

    result = score_student(roll, str(student_data.get("name") or ""), scores, info)

    signature_bytes = await _read(student_signature)
    if signature_bytes is None and drive_id:
        fetched = await fetch_signatures({roll: drive_id.strip()}, cache=_image_cache)
        outcome = fetched[roll]
        # A signature that cannot be fetched must not cost the student their top sheet
        # (§7) -- the PDF is produced with a placeholder and the reason is returned in
        # a header the dashboard surfaces.
        signature_bytes = outcome.data if outcome.ok else None
        signature_note = "" if outcome.ok else (outcome.error or "signature unavailable")
    else:
        signature_note = "" if signature_bytes else "no signature supplied"

    assets = SignatureAssets(
        teacher=await _read(teacher_signature),
        stamp=await _read(college_stamp),
        student=signature_bytes,
    )
    filename = output_filename(result)
    return Response(
        content=build_pdf(result, info, assets),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Signature-Status": signature_note or "embedded",
            "X-Student-Total": str(result.total),
            "Access-Control-Expose-Headers": (
                "Content-Disposition, X-Signature-Status, X-Student-Total"
            ),
        },
    )


@app.post("/api/generate")
async def generate(
    roster: UploadFile = File(...),
    marks: UploadFile = File(...),
    class_info: str = Form(...),
    teacher_signature: UploadFile | None = File(None),
    college_stamp: UploadFile | None = File(None),
    signature_sheet: UploadFile | None = File(None),
    student_signatures_zip: UploadFile | None = File(None),
) -> Response:
    """Render every student's top sheet and stream back a ZIP (§6)."""
    info = _parse_class_info(class_info)
    try:
        result = await generate_batch(
            roster_bytes=await roster.read(),
            marks_bytes=await marks.read(),
            class_info=info,
            teacher_signature=await _read(teacher_signature),
            college_stamp=await _read(college_stamp),
            signature_sheet=await _read(signature_sheet),
            student_signatures_zip=await _read(student_signatures_zip),
            roster_name=roster.filename or "roster",
            marks_name=marks.filename or "marks",
            cache=_image_cache,
        )
    except SpreadsheetError as exc:
        raise HTTPException(422, str(exc))

    if not result.outcomes:
        raise HTTPException(
            422,
            "No students could be generated. Check that the roster and marks sheet "
            "share the same roll numbers.",
        )

    filename = f"Assessment_Reports_{date.today().isoformat()}.zip"
    return Response(
        content=result.zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Generated-Count": str(result.generated_count),
        },
    )
