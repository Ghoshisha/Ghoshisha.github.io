# Assessment Top-Sheet PDF Generator

Turns a student roster and a marks sheet into one filled, print-ready
**MAKAUT CA2 Top Sheet** PDF per student — with each student's signature fetched
automatically from the Google Form they submitted it to.

It replaces a 13-step manual workflow (Gmail → Sheets → manual data entry → manual
signature link copying → Docs template → Autocrat mail-merge → per-row testing) with a
single dashboard: upload the sheets once, pull up each student, correct anything wrong,
and generate their top sheet.

```
React + Vite SPA  ──── multipart ────▶  FastAPI backend  ────▶  Google Drive
 (GitHub Pages)   ◀──── PDF / ZIP ────   (Render)                (signatures)
```

No database, no accounts, no stored history — every request is upload → process →
download.

## Quick start

```bash
# backend
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload            # http://127.0.0.1:8000

# frontend, in a second terminal
cd frontend
npm install
npm run dev                              # http://127.0.0.1:5173
```

The frontend talks to `http://127.0.0.1:8000` by default; set `VITE_API_BASE_URL` to
point it elsewhere.

Run the tests:

```bash
cd backend && python -m pytest -q
```

`TOPSHEET_NETWORK_TESTS=1` additionally runs one test against real Google Drive.

## How it works

A single dashboard. Load the class once, then work through it one student at a time.

1. **Set up the class** — upload the roster, the marks sheet, the signature form export,
   the examiner signature and the college stamp. Paper settings, questions, rubric and
   feedback bands live behind one toggle, pre-filled with the MAKAUT defaults. The panel
   collapses once the class is loaded.
2. **Pick a student** from the list on the left. It shows every student's total and a
   status dot: ready, missing marks, no signature on file, edited, or generated.
3. **Check their marks.** The grid shows every question with its awarded mark editable.
   Remarks, AR References, the total and the feedback band recompute as you type — on
   the server, by the same code that renders the PDF, so what you see cannot disagree
   with the document.
4. **Check their signature.** It is fetched from their Drive link and shown inline. If
   it is wrong or their sharing is broken, upload a replacement for that one student.
5. **Generate this top sheet** — one PDF, downloaded immediately, using the marks on
   screen rather than what the spreadsheet said.

Edits live in the browser tab only; nothing is written back to your spreadsheet. A
**Generate all as ZIP** button still produces the whole class in one go once you are
happy with it.

## What is computed, not typed

Only the raw per-question marks are entered. Everything else is derived:

| Field | Rule |
|---|---|
| **Remarks** | full marks → Correct · zero → Wrong · anything between → Partially Correct · blank → NA |
| **Total** | best 5 of 6 one-mark questions + best 4 of 5 five-mark questions (configurable) |
| **Strengths / Areas / Measures** | percentage of Full Marks against the feedback bands |
| **AR Reference** | Bloom's level letter + attainment digit, e.g. `A1`, `B3` |

A blank cell is **not** a zero. Blank means "not attempted" and prints as `NA`; a
literal `0` prints as `Wrong`.

## Signatures

Students submit signatures through a Google Form, which produces a workbook of Drive
links. The backend reads **every sheet** of that workbook, keeps the **latest**
submission per roll number, and fetches only the signatures for the students in the
uploaded marks sheet — never all ~760 on file.

Fetching is defensive by necessity. A link that was never shared publicly, a Drive
virus-scan interstitial served instead of image bytes, a timeout, an oversized upload —
each is recorded against that student in `manifest.json` and their top sheet is still
generated, with a "Signature not provided" placeholder. A response that is not really
an image is rejected rather than embedded.

If a student's Drive sharing is broken and cannot be fixed quickly, upload a ZIP of
images named by roll number (`25371025001.png`). Anything in that ZIP wins.

## Documentation

[`docs/BUILD_SPEC.md`](docs/BUILD_SPEC.md) is the full specification. **Appendix A** is
the important part: it records the rules recovered from the teacher's own spreadsheet
formulas, several of which contradict the original spec. Where they disagree, Appendix A
wins.

Three corrections there change every generated document:

- **The total drops the lowest score in each group** (A.1). The paper allots 31 marks
  but is out of 25 — best 5 of 6, plus best 4 of 5. A plain sum is wrong.
- **AR Reference is derived, and the original formula was buggy** (A.2). Its Bloom
  lookup read across an empty row, so every question but the first printed `C`. The
  corrected lookup is used by default; a "legacy" toggle reproduces the old output for
  reissuing a document a student already has.
- **The Roll/Name swap is systematic, not a one-off** (A.8). In the real working sheet
  the column headed `Roll` contains names for every row. Columns are matched by header
  *and* validated by value, and a swap is corrected and reported.

## Repository layout

```
backend/
  app/
    normalize.py       # the shared roll/header normalizer — every join goes through it
    models.py          # ClassInfo, Question, QuestionGroup, FeedbackBand
    parsing.py         # roster + marks reading, value-based swap detection
    scoring.py         # remarks, best-N-of-M total, feedback bands, AR reference
    signatures.py      # all-sheets read, dedupe by latest submission
    drive_fetch.py     # concurrent Drive fetch, cached, with every failure path handled
    pdf_generator.py   # ReportLab layout
    templates_xlsx.py  # the downloadable roster/marks templates
    batch.py           # whole-class orchestration + manifest
    main.py            # FastAPI routes and CORS
  tests/               # 213 tests, including assertions against the real files
frontend/
  src/components/      # setup panel, student list, per-student mark sheet, editors
  src/lib/api.js       # endpoint wrappers
docs/BUILD_SPEC.md     # specification + Appendix A
fixtures/              # reference files — gitignored, real student data
```

`fixtures/` holds the real reference spreadsheets and PDF. They contain student names,
roll numbers and Drive links, so they are **gitignored and must not be committed**.
Tests that need them skip themselves when they are absent.

## Deployment

**Backend (Render, free tier)** — root directory `backend/`, build
`pip install -r requirements.txt`, start
`uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Set `ALLOWED_ORIGINS` to your
GitHub Pages origin (`https://<username>.github.io`). See `backend/render.yaml`.

**Frontend (GitHub Pages)** — `.github/workflows/deploy-frontend.yml` builds and
publishes on every push to `main`. Set repository variable `VITE_API_BASE_URL` to the
Render URL, and set Pages' source to "GitHub Actions".

The free Render tier sleeps after inactivity, so the first request takes about 30
seconds to wake it. The UI pings `/api/health` on load to get that out of the way and
shows a "waking the server" banner meanwhile.

## Known limitations

- Legacy `.xls` files are not readable; `.xlsx` and `.csv` are. The error says so.
- The signature cache does not survive a Render cold start.
- No database, accounts, email sending or batch history — see §10 of the spec for where
  each would slot in.
- `Sheet2` of the reference workbook lists different Bloom levels than the printed PDF.
  The form is seeded with the printed document's values; since AR Reference is derived
  from Bloom, this is worth confirming with the teacher (Appendix A.11).
