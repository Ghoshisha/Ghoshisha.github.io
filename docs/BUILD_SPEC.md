# Assessment Top-Sheet PDF Generator — Build Specification

## 1. What this is

A tool for a college subject teacher to turn two spreadsheets (a student roster and a
marks sheet) plus two signature sources into one filled, print-ready PDF per student,
matching the university's official "Top Sheet for CA2 Marks Submission" form exactly.

It replaces a manual workflow that currently takes 13 steps per class (Gmail → Google
Sheets → manual data entry → manual signature link copying → Google Docs template →
Autocrat mail-merge add-on → manual column mapping → manual per-row testing) with:
upload two files + two signatures → click Generate → download a ZIP of finished PDFs.

**Reference document:** the target PDF layout is the uploaded sample
`Abhisha_Banerjee.pdf` — a Maulana Abul Kalam Azad University of Technology (MAKAUT)
CA2 marks top sheet. All field names and table structure below are taken directly from
that document. Note: in the sample PDF itself, "Name of the Student" and "Roll Number"
are swapped (a one-off data-entry mistake by whoever filled it in) — the template
fields are correctly defined as Name = text name, Roll Number = numeric ID; do not
replicate the swap.

## 2. Architecture

```
┌─────────────────────┐        HTTPS/JSON+multipart        ┌──────────────────────┐
│   React + Vite SPA   │ ──────────────────────────────────▶│   FastAPI backend     │
│   (GitHub Pages)     │◀────────────────────────────────── │   (Render)            │
│                       │        PDF ZIP / preview JSON       │                       │
│  - class info form    │                                     │  - parse roster/marks │
│  - question editor     │                                     │  - compute scoring    │
│  - file uploads         │                                     │  - match signatures   │
│  - preview table          │                                     │  - render PDFs        │
│  - trigger download         │                                     │  - zip + stream        │
└─────────────────────┘                                     └──────────────────────┘
```

**Why this split:** all the logic that has to be *correct* (score bucketing, roll-number
matching, exact table layout) lives in one place (Python backend), tested independently
of the UI. The frontend is a thin client: collect inputs, show a preview/validation
table, call the API, download the result. No database, no auth, no persistent storage
in this version — every request is stateless (upload → process → return file). This can
be added later (see §9) without restructuring anything above.

**Hosting:**
- Frontend: GitHub Pages, built and deployed by a GitHub Actions workflow on every push
  to `main`.
- Backend: Render (free web service tier), auto-deployed from the `backend/` folder of
  the same GitHub repo. Render was chosen over Railway/Fly.io for its simplest native
  Python buildpack (no Dockerfile required) and GitHub-push auto-deploy.
- CORS: the backend must allow the GitHub Pages origin (`https://<username>.github.io`)
  in `CORSMiddleware`.
- The frontend needs the backend's Render URL at build time via `VITE_API_BASE_URL`
  (set as a GitHub Actions repo variable, injected at build).

## 3. Repository layout

```
repo-root/
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── ClassInfoForm.jsx        # university/paper/teacher fields
│   │   │   ├── RubricEditor.jsx         # 4-row rubric text, editable
│   │   │   ├── QuestionListEditor.jsx   # add/remove question rows (Q.No, allotted, CO, Bloom, AR ref)
│   │   │   ├── FeedbackBandsEditor.jsx  # editable 5-tier score bands + text
│   │   │   ├── FileUploadStep.jsx       # roster / marks / teacher sig / student sig zip
│   │   │   ├── PreviewTable.jsx         # calls /api/preview, shows per-student status
│   │   │   └── GenerateButton.jsx       # calls /api/generate, triggers ZIP download
│   │   ├── lib/
│   │   │   ├── api.js                   # fetch wrappers for the 4 backend endpoints
│   │   │   └── templateDownload.js      # generates roster.xlsx/marks.xlsx client-side (SheetJS)
│   │   ├── App.jsx
│   │   └── main.jsx
│   ├── package.json
│   └── vite.config.js
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI app, CORS, route definitions
│   │   ├── models.py             # Pydantic schemas (ClassInfo, Question, RubricRow, FeedbackBand)
│   │   ├── parsing.py            # spreadsheet reading + fuzzy header matching
│   │   ├── scoring.py            # remarks / total / feedback-band derivation
│   │   ├── signatures.py       # signature-sheet parsing, dedupe-by-latest, roll normalization
│   │   ├── drive_fetch.py      # server-side Drive image download: ID extraction, interstitial, 403 handling, cache, concurrency
│   │   ├── pdf_generator.py    # ReportLab template — one PDF per student
│   │   └── templates_xlsx.py     # generates the two downloadable template spreadsheets
│   ├── requirements.txt
│   └── render.yaml               # Render service definition (optional, for infra-as-code)
├── .github/
│   └── workflows/
│       └── deploy-frontend.yml   # build + deploy frontend to GitHub Pages
├── docs/
│   └── BUILD_SPEC.md             # this file
└── README.md
```

## 4. Data model

### 4.1 ClassInfo (submitted once per batch, entered in the frontend form)

```json
{
  "documentTitle": {
    "universityName": "Maulana Abul Kalam Azad University of Technology, West Bengal",
    "formTitle": "Top Sheet for CA2 Marks Submission",
    "formSubtitle": "(Written Test as a part of Continuous Assessment)"
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
    { "label": "A", "criteria": "Conceptual Understanding",
      "excellent": "Complete accuracy, deep insight; accurate and logical application",
      "good": "Mostly correct, minor gaps; minor errors in application",
      "satisfactory": "Basic understanding; limited application ability",
      "needsImprovement": "Poor understanding; incorrect approach" },
    { "label": "B", "criteria": "Application/Problem Solving",
      "excellent": "Complete accuracy, deep insight; accurate and logical application",
      "good": "Mostly correct, minor gaps; minor errors in application",
      "satisfactory": "Basic understanding; limited application ability",
      "needsImprovement": "Poor understanding; incorrect approach" },
    { "label": "C", "criteria": "Presentation & Clarity",
      "excellent": "Well-structured, clear steps", "good": "Mostly clear",
      "satisfactory": "Some lack of clarity", "needsImprovement": "Poor presentation" },
    { "label": "D", "criteria": "Analytical Ability",
      "excellent": "Strong reasoning and justification", "good": "Adequate reasoning",
      "satisfactory": "Limited reasoning", "needsImprovement": "No logical justification" }
  ],
  "questions": [
    { "qno": "1.a", "marksAllotted": 1, "coMapping": "CO3", "bloomLevel": "Remember", "arReference": "A1" },
    { "qno": "1.b", "marksAllotted": 1, "coMapping": "CO2", "bloomLevel": "Remember", "arReference": "C1" },
    { "qno": "1.c", "marksAllotted": 1, "coMapping": "CO2", "bloomLevel": "Understand", "arReference": "C1" },
    { "qno": "1.d", "marksAllotted": 1, "coMapping": "CO2", "bloomLevel": "Understand", "arReference": "NA" },
    { "qno": "1.e", "marksAllotted": 1, "coMapping": "CO3", "bloomLevel": "Remember", "arReference": "C1" },
    { "qno": "1.f", "marksAllotted": 1, "coMapping": "CO2", "bloomLevel": "Understand", "arReference": "NA" },
    { "qno": "2",   "marksAllotted": 5, "coMapping": "CO3", "bloomLevel": "Apply",      "arReference": "C1" },
    { "qno": "3",   "marksAllotted": 5, "coMapping": "CO3", "bloomLevel": "Understand", "arReference": "C1" },
    { "qno": "4",   "marksAllotted": 5, "coMapping": "CO1", "bloomLevel": "Understand", "arReference": "C1" },
    { "qno": "5",   "marksAllotted": 5, "coMapping": "CO3", "bloomLevel": "Apply",      "arReference": "NA" },
    { "qno": "6",   "marksAllotted": 5, "coMapping": "CO2", "bloomLevel": "Apply",      "arReference": "NA" }
  ],
  "feedbackBands": [
    { "maxPercent": 20,  "feedback": "Needs Improvement", "areas": "Improve Fundamentals",             "measures": "Revise Fundamentals" },
    { "maxPercent": 40,  "feedback": "Basic Knowledge",    "areas": "Improve Basic Concepts",            "measures": "Practice Basic Concepts" },
    { "maxPercent": 60,  "feedback": "Fair Understanding", "areas": "Improve Conceptual Understanding",  "measures": "Practice Concept Application" },
    { "maxPercent": 80,  "feedback": "Good Clarity",       "areas": "Improve Application Skills",         "measures": "Develop Analytical Skills" },
    { "maxPercent": 100, "feedback": "Excellent Clarity",  "areas": "Refine Advanced Concepts",           "measures": "Refine Advanced Skills" }
  ]
}
```

**AR Reference note:** no formula was given for this field, unlike Remarks/Feedback/
Areas/Measures. It's modeled here as a static per-question attribute (like CO Mapping
and Bloom's Level) that the teacher sets once per paper. In the sample PDF it happens to
read "NA" on rows where the score was also blank — if that turns out to be a real rule
(AR Reference → "NA" whenever that question's score is blank) rather than coincidence,
add it to `scoring.py` alongside the Remarks rule. Confirm with the teacher before
assuming either way.

### 4.2 Roster spreadsheet (uploaded per batch)

| Roll         | Name             |
|--------------|------------------|
| 25371025001  | Abhisha Banerjee |
| 25371025003  | Angira Ghosh     |

Header matching is fuzzy (case/space/punctuation-insensitive): any header containing
"roll" is treated as the roll column, any header containing "name" as the name column.

### 4.3 Marks spreadsheet (uploaded per batch)

One column per question, header text matching `question.qno` exactly (fuzzy-normalized,
so `"1.a"`, `"1a"`, `"1 a"` all match the same column). Cell values: `1`, `0.5`, `0`, or
blank (blank = not applicable / not attempted).

| Roll        | 1.a | 1.b | 1.c | 1.d | 1.e | 1.f | 2 | 3 | 4 | 5 | 6 |
|-------------|-----|-----|-----|-----|-----|-----|---|---|---|---|---|
| 25371025001 | 1   | 1   | 1   |     | 1   |     | 2 | 3 | 3 |   |   |

No Remarks, Feedback, Areas, or Measures columns — those are all computed (§5).

### 4.4 Signatures

The signature data is a real **Google Form response export** (`Signature.xlsx`), not a
clean roster. Its actual structure, confirmed by inspecting the file, drives several
non-obvious requirements:

- **Columns:** `[timestamp] | Full Name | University Roll Number | Semester |
  Department | Signature Drive Link`. The first column is an unlabeled form timestamp.
- **~19 sheets**, one per class/batch (e.g. `CSE2024-2028`, `MCA2025-2027`,
  `AIML2023-2027`). The tool must read **all sheets**, not just the first.
- **Header row is not always row 1.** Some sheets (`BCASIMT`) start data at row 1 with
  no header; others have a blank A1. Do not assume `sheet_to_json`'s default header
  detection — instead, locate the header row by scanning the first few rows for the
  cells "Full Name" / "University Roll Number" / "Signature Drive Link", and if none is
  found, fall back to fixed positional columns (name = col B, roll = col C, link =
  col F) since the layout is consistent even where the header is missing.
- **Duplicate submissions are common** — the same roll number appears multiple times
  (one student re-submitted the form up to 4 times), each with a *different* Drive link.
  **Resolution rule (confirmed): keep only the latest submission per roll number**,
  determined by the timestamp in column A. Dedupe across all sheets combined, keyed by
  normalized roll number. If a row has no timestamp, treat it as older than any
  timestamped row for the same roll.
- **Roll numbers are dirty:** stored variously as text (`"25371025001"`), as a float
  (`25300122014.0`), or with a trailing dot (`"25300124010."`). Normalize before
  matching: coerce to string, strip a trailing `.0` / `.`, strip whitespace and
  non-alphanumerics (reuse the same `normalize()` used for header matching, applied to
  the *value*).

**Matching to the marks sheet:** by **roll number only** (confirmed). The name in the
signature file is used only for display/logging, never as a match key — names are
inconsistent (casing, misspellings like "Soham Mandsl") and unreliable. When a
student's roll from the marks sheet has no row in the signature file, that's a
"signature missing" issue in the manifest, not a fatal error.

**Signature image retrieval — server-side Drive fetch (confirmed approach):** rather
than the teacher manually exporting a ZIP of ~2000 images, the FastAPI backend fetches
each needed signature from its Drive link server-side (no browser CORS constraint
applies to a server). This is the single most failure-prone part of the system and
must be built defensively:

1. **Fetch only what's needed.** Resolve the set of roll numbers present in the
   uploaded *marks* sheet first, then fetch signatures only for those rolls (typically
   30–60), never all ~2000. Fetching everything would blow Render's free-tier request
   timeout.
2. **Convert the link to a downloadable form.** The stored links look like
   `https://drive.google.com/file/d/<ID>/view`. Extract `<ID>` with a regex and request
   `https://drive.google.com/uc?export=download&id=<ID>`.
3. **Handle Drive's virus-scan interstitial.** For some files Drive returns an HTML
   confirmation page instead of image bytes; the backend must detect a non-image
   `Content-Type` / an HTML body, parse out the confirm token, and issue the follow-up
   request. If the result still isn't an image, record "roll X: could not retrieve
   signature (got HTML, not an image)" in the manifest and continue.
4. **Handle permission failures.** A link not shared as "Anyone with the link" returns
   403. Catch it and record "roll X: signature not accessible — check Drive sharing"
   rather than failing the batch. (This is the same root cause as the original
   workflow's troubleshooting slide, surfaced explicitly instead of producing a broken
   document.)
5. **Cache fetched images** keyed by Drive file ID (on-disk temp cache within the
   process/instance lifetime) so re-running a batch, or two batches sharing students,
   doesn't re-download. Note the cache does not survive a Render cold start — that's
   acceptable for this version.
6. **Run fetches concurrently** (bounded, e.g. an `asyncio`/`httpx` pool of ~10) so 50
   images take seconds, not a minute of serial requests.
7. **Fallback path.** Keep a manual override: allow uploading a ZIP of signature images
   named by roll number (the earlier approach) that takes precedence over Drive fetch
   for any roll present in the ZIP. This is the escape hatch when a student's Drive
   sharing is broken and can't be fixed quickly — the teacher drops in a manually saved
   image and re-runs.

**Teacher/examiner signature:** unchanged — one image file uploaded once per batch,
embedded on every generated PDF. Not part of the Drive-fetch flow.

## 5. Scoring logic (`backend/app/scoring.py`)

For each student, for each question in `classInfo.questions`:

**The rule has three zones based on proportion of marks allotted, not an exact-half
check.** Confirmed against a real multi-student sheet (not just the single reference
PDF): a 5-mark question scoring 2 or 3 is marked "Partially Correct" — any nonzero,
non-full score is partial credit, not just an exact half. Only a literal zero is
"Wrong."

```python
def remark_for_score(score: str | float | None, marks_allotted: float) -> str:
    if score in (None, "") or not marks_allotted:
        return "NA"
    score = float(score)
    if score == marks_allotted:
        return "Correct"
    if score == 0:
        return "Wrong"
    return "Partially Correct"
```

**Known discrepancy, resolved:** the original reference PDF (Abhisha Banerjee's) shows
Q2 (allotted 5, scored 2) as "Wrong" — that PDF was generated under the old, unfixed
formula, which compares the raw score to a literal `1`/`0.5` regardless of how many
marks the question is worth, so a 5-mark question scoring 2 falls through to "Wrong"
by accident. A separate, later screenshot of the live sheet shows the same 2-out-of-5
pattern correctly marked "Partially Correct," which is what the rule above reproduces.
**Going forward, the three-zone rule above is authoritative** — regenerating the
original reference student's PDF under this corrected rule will legitimately produce
"Partially Correct" for Q2 instead of the original PDF's "Wrong," and that's expected,
not a bug in the new system.

Total:

```python
total = sum(float(s) for s in scores.values() if s not in (None, ""))
full_marks = class_info.full_marks
percent = (total / full_marks) * 100 if full_marks else 0
```

Band lookup (feedback / areas / measures), using `percent` against
`classInfo.feedbackBands` (already sorted ascending by `maxPercent`, first band whose
`maxPercent >= percent` wins; blank total → `"NA"` for all three, matching the sheet's
own `IF(AA2="","NA",...)` guard):

```python
def band_for(percent: float, bands: list[FeedbackBand]) -> FeedbackBand:
    for band in bands:
        if percent <= band.maxPercent:
            return band
    return bands[-1]
```

**Validated against the reference PDF:** Abhisha Banerjee's raw scores
(1,1,1,blank,1,blank,2,3,3,blank,blank) sum to **12**. Full Marks 25 → **48%** →
falls in the ≤60% band → "Fair Understanding" / "Improve Conceptual Understanding" /
"Practice Concept Application" — this matches the sample PDF's printed feedback
exactly, confirming the formulas and the percent-of-full-marks generalization are
both correct for this reference document.

## 6. API contract

### `GET /api/health`
→ `{"status": "ok"}`

### `POST /api/templates/roster` and `/api/templates/marks`
No body. Returns a downloadable `.xlsx` with the correct headers and one example row,
built from the current `classInfo.questions` list (POST so the question list can be
passed in the body — templates should reflect whatever questions the teacher just
configured, not a fixed default).

### `POST /api/preview`
`multipart/form-data`:
- `roster`: file
- `marks`: file
- `class_info`: JSON string (§4.1)

Response:
```json
{
  "students": [
    {
      "roll": "25371025001",
      "name": "Abhisha Banerjee",
      "total": 12,
      "percent": 48.0,
      "feedback": "Fair Understanding",
      "areas": "Improve Conceptual Understanding",
      "measures": "Practice Concept Application",
      "hasSignature": null,
      "missingScores": ["1.d", "1.f", "5", "6"]
    }
  ],
  "issues": [
    { "roll": "25371025002", "name": "", "level": "error", "message": "No matching row in the marks sheet." }
  ]
}
```
(`hasSignature` stays `null` here — signature files aren't part of `/api/preview`;
it's filled in for real by `/api/generate`, or add a second signatures-only field to
this endpoint if the teacher wants to see missing signatures *before* generating.)

### `POST /api/generate`
`multipart/form-data`:
- `roster`, `marks`: files
- `teacher_signature`: image file
- `signature_sheet`: the Google Form export xlsx (§4.4) — backend fetches student
  signatures from its Drive links server-side
- `student_signatures_zip`: **optional** override ZIP of images named by roll number;
  takes precedence over Drive fetch for any roll it contains (the fallback path)
- `class_info`: JSON string

Response: `application/zip` stream, filename `Assessment_Reports_<date>.zip`, containing
one file per student named `<roll>_<name>.pdf` (name slugified: spaces → underscores,
non-alphanumeric stripped), plus a `manifest.json` listing every student and the
outcome (generated / signature-missing / signature-403 / no-marks-match).

Because Drive fetching can take time, prefer returning the manifest inside the ZIP over
a response header, and surface Render's cold-start / long-run caveat in the frontend
(see §10).

## 7. PDF layout (`backend/app/pdf_generator.py`)

Use **ReportLab** (`reportlab.platypus`: `SimpleDocTemplate`, `Table`, `TableStyle`,
`Paragraph`, `Image`) — vector output, crisp selectable text, not a rasterized
screenshot. Page size A4, ~40pt margins.

Build each student's PDF as one flowable story:

1. **Title block** — three centered lines from `classInfo.documentTitle` (university
   name bold 12–13pt, form title bold, subtitle regular/italic, smaller).
2. **Info table** — 4-column `Table` (label | value | label | value), label columns
   bold. Rows: College Code & Name / Year-Semester · Programme / Subject · Paper Code /
   UPID · Name of Student / Roll Number · Date of Examinations (`colspan=3` on the value
   cell via `TableStyle('SPAN', ...)`) · Subject Teacher / Mobile Number · Full Marks /
   Duration.
3. **Assessment Rubrics table** — 6 columns (Letter | Criteria | Excellent | Good |
   Satisfactory | Needs Improvement), 4 body rows from `classInfo.rubric`. Small font
   (8–9pt) since cells are text-dense; wrap with `Paragraph` objects, not raw strings,
   so long text wraps inside the cell instead of overflowing.
4. **Marks Distribution & Mapping table** — columns Q.No / Marks Allotted / Marks
   Awarded / CO Mapping / Bloom's Level / Total Marks / Remarks / AR Reference. One row
   per question. **Total Marks column is a single merged cell spanning all rows**
   (`TableStyle('SPAN', (5, 1), (5, -1))`), showing the computed total centered
   vertically.
5. **Examiner's Feedback block** — plain paragraphs: "Strengths of the Student:
   {feedback}", "Areas for Improvement: {areas}" (teacher signature `Image` +
   date placed alongside, right-aligned, via a 2-column table so text and image sit on
   the same row), "Suggested Corrective Measures: {measures}".
6. **Acknowledgement line** — fixed text: "I have reviewed my evaluated answer script
   and understand the awarded marks and feedback."
7. **Signature row** — student signature `Image` (from the matched ZIP entry) + date,
   captioned "Signature of the student with date", left-aligned; examiner signature +
   date already placed in step 5, captioned "Signature of the Examiner with date".

If a student's signature image is missing from the ZIP, leave that image slot blank
with a small placeholder note ("Signature not provided") rather than failing that
student's PDF — record it in the manifest instead (§6).

## 8. Frontend flow

1. **Class info** — form for all of §4.1's scalar fields, plus the rubric editor and
   question-list editor (add/remove rows) and feedback-bands editor, all pre-filled
   with the defaults in §4.1 so a teacher using this exact MAKAUT form can skip
   straight to uploads.
2. **Download templates** — two buttons generate `roster_template.xlsx` and
   `marks_template.xlsx` client-side (SheetJS), pre-headered from the current question
   list, so the teacher fills in real data in the right shape.
3. **Uploads** — roster file, marks file, teacher signature image, the signature-form
   export xlsx (§4.4), and an optional override ZIP of signature images named by roll
   (fallback for students whose Drive link is broken).
4. **Preview** — call `/api/preview`, render a table: Roll, Name, Total, %, Feedback,
   and a status icon per row (✅ complete / ⚠️ missing scores / ❌ no marks-sheet match).
   Let the teacher fix and re-upload before generating.
5. **Generate** — call `/api/generate`, stream the ZIP to a browser download
   (`URL.createObjectURL` + a temporary `<a download>`). Show any manifest issues
   after download completes.

## 9. Known confusion points & build risks

These are the specific places this project is easy to build subtly wrong. Each is a
real risk grounded in the actual uploaded files, with the intended handling. Read this
section before implementing.

1. **Roll number is the ONLY join key, and it's dirty.** Marks sheet, roster, and
   signature sheet all link on roll. Values appear as text, float (`25300122014.0`),
   and trailing-dot (`25300124010.`). A single shared `normalize_roll()` must be used
   at *every* comparison site — parsing, dedupe, matching, ZIP-override lookup.
   Verified rule: coerce to str → strip trailing `.0`/`.` → lowercase → strip
   non-alphanumerics. If normalization differs between two modules by even one step,
   students silently fail to match and get no PDF.

2. **The same person can have two different roll numbers.** Real example: "Anushka
   Mandal" is `2530012014` in one sheet and `25300122014` in another — these are not a
   formatting difference, they're two different numbers (likely a typo). Do **not** try
   to reconcile these by name. Surface it: if a marks-sheet roll finds no signature
   match, list it in the manifest so a human decides. Never fuzzy-match names to paper
   over it.

3. **Remarks rule already changed once — use the three-zone version.** Full marks →
   Correct, zero → Wrong, any partial → Partially Correct, blank → NA. The original
   reference PDF shows some of these as "Wrong" because it predates the fix;
   regenerating it will legitimately differ. Do not "restore" the old behavior to match
   the sample PDF.

4. **Feedback bands are percentage-of-full-marks, not fixed cutoffs.** The teacher's
   formula hardcodes ≤5/≤10/≤15/≤20, which are 20/40/60/80% of 25. Implement as percent
   so a 30- or 50-mark paper still buckets correctly. (Flag exists in §4.1 if fixed
   numeric cutoffs are ever actually wanted.)

5. **AR Reference has no formula.** It's modeled as a static per-question field. In the
   sample it reads "NA" wherever the score is blank, which *might* be a rule or might be
   coincidence. Not auto-derived unless the teacher confirms the rule. Don't invent one.

6. **Signature sheet header row is unreliable.** Not always row 1; sometimes absent.
   Detect the header by scanning for known column names; fall back to fixed positions
   (name=B, roll=C, link=F). Reading with default header assumptions will misalign
   entire sheets.

7. **Read ALL ~19 sheets of the signature workbook, deduped by latest timestamp.**
   Reading only the first sheet loses most students. Keeping all duplicate rows embeds
   the wrong (superseded) signature. Both are silent failures — the PDF generates, just
   with wrong/no signature.

8. **Drive fetch is the top runtime risk (see §4.4).** 403 on unshared links, HTML
   virus-scan interstitial instead of image bytes, and Render free-tier timeout if
   fetching too many. Fetch only the marks-sheet's rolls, handle the interstitial,
   catch 403s into the manifest, cache by file ID, bound concurrency. A signature that
   comes back as an HTML page must be rejected, not embedded as a broken image.

9. **Total is computed, never read from a column.** The sample sheet's "Total" column
   exists but the system must sum the per-question scores itself. Trusting a
   pre-typed total column would propagate any manual error and breaks if the column is
   absent.

10. **The reference PDF has Name/Roll swapped.** That's a filling mistake in the sample,
    not the template definition. Map name→name field, roll→roll field. Do not replicate
    the swap by copying the sample's visual layout literally.

11. **Render free tier sleeps.** First request after idle takes ~30s to wake, and a
    large batch + Drive fetch is a long request. Show a "waking server / this may take
    a minute" state in the UI; consider a health-check ping on page load to pre-warm.

12. **`class_info` is a JSON string inside multipart, not a JSON body.** The generate
    and preview endpoints are `multipart/form-data` (files + a JSON text field), so
    `class_info` must be `json.loads`'d server-side, not read as the request body.

## 10. Explicitly out of scope for this version

No database, no user accounts/auth, no email sending, no stored history of past
batches — every run is stateless (upload → process → download). If any of these
become priorities later, they slot into the existing split cleanly: auth sits in
FastAPI middleware, persistence adds a Postgres instance + a `batches` table keyed by
a generated batch ID, email sending adds an SMTP call after PDF generation in
`main.py`. None of it requires re-architecting the frontend/backend boundary defined
here.

## 11. Deployment checklist

- [ ] `backend/requirements.txt`: `fastapi`, `uvicorn[standard]`, `python-multipart`,
      `openpyxl`, `reportlab`, `pydantic`.
- [ ] `CORSMiddleware` in `main.py` allowing the GitHub Pages origin.
- [ ] Render web service: root directory `backend/`, build `pip install -r
      requirements.txt`, start `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
- [ ] GitHub Actions workflow (`.github/workflows/deploy-frontend.yml`): on push to
      `main`, `npm ci && npm run build` in `frontend/`, inject `VITE_API_BASE_URL`
      (repo variable pointing at the Render URL), deploy `frontend/dist` to the
      `gh-pages` branch (or native Pages Actions deployment).
- [ ] Confirm the Render free-tier cold-start delay (service sleeps after inactivity)
      is acceptable, or note it in the frontend UI ("first request may take ~30s to
      wake the server").

---

# Appendix A — Corrections confirmed against the reference files

Added after inspecting `fixtures/AIML.xlsx` (the live Autocrat working sheet, with its
original formulas intact), `fixtures/Signature.xlsx`, `fixtures/Abhisha Banerjee.pdf`
and `fixtures/Video_Tutorial_Detailed_Presentation.pptx`.

**Where this appendix contradicts §1–§11, this appendix wins.** The rules below are
recovered from the teacher's actual spreadsheet formulas, not inferred from the sample
PDF.

## A.1 Total is best-N-of-M, not a plain sum (overrides §5, §9.9)

The sheet's Total formula:

```
=IF(COUNT(E2:J2)>5, SUM(E2:J2)-SMALL(E2:J2,1), SUM(E2:J2))
+IF(COUNT(K2:O2)>4, SUM(K2:O2)-SMALL(K2:O2,1), SUM(K2:O2))
```

Best **5 of 6** one-mark questions (1.a–1.f) plus best **4 of 5** five-mark questions
(2–6). This is why the paper allots 31 marks (6x1 + 5x5) but Full Marks is 25 (5x1 + 4x5).
Only *attempted* (numeric) cells count: `COUNT` ignores blanks, and `SMALL(range,1)` is
the minimum of the numeric entries, so a group with blanks drops nothing.

Modeled as `ClassInfo.questionGroups: [{ label, questions: [qno], countBest }]`.
A question in no group is always counted. Verified totals: Abhisha 13, Angira 25,
Deep 12.5 — all match the sheet.

Note the raw per-question score is still what prints in "Marks Awarded" and what drives
Remarks and AR Reference; dropping affects the Total only.

## A.2 AR Reference is derived (overrides §4.1 "AR Reference note", §9.5)

§9.5's "no formula, don't invent one" is superseded — there is one, per question:

```
AR = bloom_letter + score_digit
  bloom_letter: Remember | Understand      -> "A"
                Apply                      -> "B"
                Analyze | Evaluate | Create -> "D"
                anything else              -> "C"
  score_digit:  frac = score / marks_allotted
                frac >= 0.8 -> "1" ; >= 0.6 -> "2" ; >= 0.4 -> "3" ; else "4"
  score blank or <= 0 -> "NA"
```

**The teacher's implementation of this is buggy and we deliberately do not reproduce
it.** Its Bloom lookup reads *across* `Sheet2!B2..L2` while `Sheet2` is laid out *down*
as `QNo | Bloom` rows, so only question 1.a resolves a real Bloom level and every other
question falls through to the `TRUE -> "C"` default. That is the sole reason the live
sheet emits `D1, C1, C1, C1, C1, NA, C3, C2, C2, NA, NA`.

Decision (confirmed): use each question's real `bloomLevel` from `ClassInfo.questions`.
Output will legitimately differ from previously issued PDFs — that is expected, the same
way §9.3's Remarks correction is.

`arReference` is therefore removed from the per-question `ClassInfo` input; it is
computed per student per question.

## A.3 Remarks — §5 confirmed

The sheet holds two hardcoded variants: 1-mark questions use `=1 -> Correct`,
`=0.5 -> Partially Correct`, else `Wrong`; 5-mark questions use `=0 -> Wrong`,
`=5 -> Correct`, else `Partially Correct`. Both are the same three-zone rule
specialized by marks-allotted, so §5's generalized `remark_for_score` reproduces both
exactly. §5 stands as written.

## A.4 Feedback bands — §9.4 confirmed, with a note

The sheet buckets on the **absolute** total (`<=5 / <=10 / <=15 / <=20`), not a
percentage. At Full Marks 25 these are exactly 20/40/60/80%, so §9.4's percent
generalization is equivalent here and is kept.

## A.5 A third image: the college stamp (adds to §7)

`Abhisha Banerjee.pdf` (A4, 596×842pt) embeds **three** images, not two:

| image   | what it is        | x     | y     | w     | h    |
|---------|-------------------|-------|-------|-------|------|
| X9.jpg  | teacher signature | 313.8 | 203.0 | 122.1 | 36.3 |
| X11.jpg | **college stamp** | 474.0 | 141.8 |  50.2 | 36.8 |
| X12.png | student signature |  42.0 | 111.0 |  75.0 | 15.0 |

(y measured from the page bottom.) The stamp reads "SUPREME KNOWLEDGE FOUNDATION GROUP
OF INSTITUTIONS / MAKAUT COLLEGE CODE 253 MANKUNDU". It is static per batch, like the
teacher signature, and needs its own optional upload field `college_stamp` on
`/api/generate`.

## A.6 Drive fetch — use the thumbnail endpoint (refines §4.4)

The sheet's own `SignURL` formula, which is what Autocrat consumed:

```
"https://docs.google.com/thumbnail?sz=w500&id=" & REGEXEXTRACT(link, "(?:id=|/d/)([a-zA-Z0-9_-]+)")
```

Both endpoints were probed live against a real file ID and both returned `image/png`
with no virus-scan interstitial:

- `https://docs.google.com/thumbnail?sz=w500&id=<ID>` -> 200, `image/png`
- `https://drive.google.com/uc?export=download&id=<ID>` -> 200, `image/png`

Use the thumbnail endpoint as primary — it is server-side size-capped, so a student who
uploaded a 4MB phone photo costs one small transfer instead of the full original — with
`uc?export=download` as fallback. Keep all of §4.4's defensive handling regardless: the
interstitial path, 403s, magic-byte validation, the ID cache and bounded concurrency.

The ID regex must accept both `/file/d/<ID>/view` and `open?id=<ID>` shapes.

## A.7 Signature workbook — what the file actually contains (refines §4.4, §9.6, §9.7)

Measured on `fixtures/Signature.xlsx`:

- **16 sheets, not ~19.** `Sheet1` is a near-superset; the other 15 are per-department
  copies. Only **3** rolls exist solely outside `Sheet1`, so reading every sheet is
  still required.
- **1794 usable rows resolve to 759 unique students.** (1812 non-blank rows, less 16
  header rows and 2 with no usable roll number.) 665 rolls appear more than once; the
  most-resubmitted roll (`36441623008`) appears **10** times -- §4.4 said up to 4. 297
  rolls carry genuinely different Drive file IDs across their duplicates, so dedupe
  decides which signature a student gets in nearly 40% of cases.
- **Latest-timestamp leaves 32 rolls undecided.** For those, the newest submission is
  itself a tie between two sheets pointing at *different* Drive files -- e.g. roll
  `25300123002` in `Sheet1` and `CSE2023-2027`. Tiebreak (confirmed): a per-department
  sheet beats `Sheet1`, and the tie is recorded as a warning in the manifest. Latest
  timestamp still wins outright wherever one exists, so a tie further down a roll's
  history (roll `25300104046`, `MD ARIF JAMIL`) is correctly *not* reported -- only a
  tie that actually decided the outcome is.
- **Header rows leak into the data.** `BCASIMT` and `BCA2025-2028` have no header row at
  the top (as §4.4 predicted) but do contain a literal `Full Name` /
  `University Roll Number` row mid-data. Drop any row whose roll cell normalizes to a
  known header label.
- **Row-level Roll/Name swap.** `Shubha Maity` appears in the roll column in both
  `Sheet1` and `CYS`. Surfaced as a student with the roll `shubhamaity`, never
  name-matched away (§9.2).
- 10 rows have no timestamp; 2 rows carry no usable roll number; every kept row has a
  parseable Drive link.

## A.8 The Roll/Name swap is systematic, not a one-off (overrides §1, §9.10)

§1 calls the swap "a one-off data-entry mistake". In `AIML.xlsx!Sheet1` the column
headed `Roll` contains **names** and the column headed `Name` contains **roll numbers**
for every row, and Autocrat's output filename pattern is `Topsheet_<<Roll>>` — so the
old workflow named files after students. Fuzzy header matching alone reproduces the swap
on this exact file.

Required: after header matching, validate by *value*. If the roll column is mostly
non-numeric while the name column is mostly digits, swap the two and record a warning in
the manifest. Never silently trust the header.

## A.9 `normalize()` must strip the float suffix from headers too (refines §9.1)

Question columns are stored as **floats** in the real sheet: the headers are `2.0`,
`3.0`, `4.0`, not `2`, `3`, `4`. §9.1's rule (strip non-alphanumerics) turns `"2.0"`
into `"20"`, which never matches question `"2"` — every five-mark score would silently
go missing.

The trailing `.0` / `.` strip must run on **headers as well as values**, before the
non-alphanumeric strip. Required equivalences:

```
"2" == "2.0" == 2.0 == " 2 "
"1.a" == "1a" == "1 A"
"25300122014" == "25300122014.0" == "25300124010." (trailing dot)
```

`Sheet2` writes question numbers without dots (`1a`), and `Sheet1` writes them with
(`1.a`), so both forms occur in real data.

## A.10 Reference values for regression tests

From `AIML.xlsx!Sheet1` (note: the sheet has been edited since the sample PDF was
generated — 1.d gained a mark, so the sheet totals 13 where the PDF shows 12; both are
correct under the same formula).

| student          | roll        | raw scores (1.a–1.f, 2–6) | total |
|------------------|-------------|---------------------------|-------|
| Abhisha Banerjee | 25371025001 | 1,1,1,1,1,_ , 2,3,3,_,_   | 13    |
| Angira Ghosh     | 25371025003 | 1,1,1,_,1,1 , _,5,5,5,5   | 25    |
| Deep Chakraborty | 25371025004 | 1,1,1,0.5,_,1 , 2,3,3,_,_ | 12.5  |

The sample PDF's own row (`1,1,1,_,1,_ , 2,3,3,_,_`) totals **12** -> 48% ->
"Fair Understanding" / "Improve Conceptual Understanding" /
"Practice Concept Application", matching the printed document.

Signature join, verified end to end: roll `25371025001` -> Drive ID
`12uZuuQ3MIeNzTPD-u41bZSrgFyLIrYOF` -> the student-signature image embedded in the
sample PDF, and identical to that row's `SignURL` in `AIML.xlsx`.

## A.11 Open questions for the teacher (not blocking)

1. `Sheet2`'s Bloom levels (`1a->Create, 1b->Remember, 1c->Apply, 1d->Understand,
   1e->Evaluate, 1f->Remember, 2->Remember, 3->Understand, 4->Apply, 5->Create,
   6->Understand`) contradict §4.1's defaults and the printed PDF. Since AR Reference is
   now derived from Bloom (A.2), this changes AR output directly. The frontend is seeded
   with §4.1's values because they match the printed document; the teacher can edit them.
2. The "Marks Allotted" column prints 31 marks of questions against Full Marks 25, with
   no printed note that two are dropped (A.1). Reproduced as-is, matching the original.

## A.12 The marks workbook's data is not on the first sheet

`AIML.xlsx` has four sheets in this order: `Form Responses 1` (a two-column form stub),
`Sheet1` (the actual roster + marks + computed columns), `Sheet2` (a QNo -> Bloom lookup
table) and `DO NOT DELETE - AutoCrat Job Se` (the add-on's config).

Reading `worksheets[0]` therefore finds a sheet with no roll or name column and reports
the whole upload as unreadable. The roster/marks reader picks the first sheet whose
header row names **both** a roll and a name column, falling back to the first non-empty
sheet. Note `DO NOT DELETE - AutoCrat Job Se` contains a `Job Name` header, which is why
the test requires two matching labels rather than one.
