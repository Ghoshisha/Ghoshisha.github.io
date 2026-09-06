// The working area: one student's marks, editable, with everything derived from them
// recomputed on the server as the teacher types.

import { useEffect, useRef, useState } from 'react'

import { fetchSignatureImage } from '../lib/api'

function MarkInput({ question, value, onChange }) {
  // Kept as a string while focused so a half-typed "0." is not swallowed.
  const [draft, setDraft] = useState(value === null ? '' : String(value))
  const editing = useRef(false)

  useEffect(() => {
    if (!editing.current) setDraft(value === null ? '' : String(value))
  }, [value])

  const commit = (raw) => {
    const trimmed = raw.trim()
    if (trimmed === '') return onChange(null)
    const parsed = Number(trimmed)
    if (Number.isNaN(parsed)) return
    onChange(parsed)
  }

  const tooHigh = value !== null && value > question.marksAllotted

  return (
    <input
      className={`mark ${tooHigh ? 'invalid' : ''}`}
      inputMode="decimal"
      value={draft}
      placeholder="—"
      title={tooHigh ? `More than the ${question.marksAllotted} allotted` : undefined}
      onFocus={() => {
        editing.current = true
      }}
      onBlur={() => {
        editing.current = false
        commit(draft)
      }}
      onChange={(event) => {
        setDraft(event.target.value)
        commit(event.target.value)
      }}
    />
  )
}

function SignaturePanel({ student, override, onOverride }) {
  const [image, setImage] = useState({ url: null, error: null, loading: false })

  useEffect(() => {
    let revoked = null
    setImage({ url: null, error: null, loading: false })
    if (override) {
      const url = URL.createObjectURL(override)
      revoked = url
      setImage({ url, error: null, loading: false })
    } else if (student.driveId) {
      setImage({ url: null, error: null, loading: true })
      fetchSignatureImage(student.driveId).then((result) => {
        revoked = result.url
        setImage({ ...result, loading: false })
      })
    }
    return () => {
      if (revoked) URL.revokeObjectURL(revoked)
    }
  }, [student.driveId, student.roll, override])

  return (
    <div className="signature-panel">
      <h4>Student signature</h4>

      {image.loading && <p className="hint">Fetching from Google Drive…</p>}

      {image.url && (
        <>
          <img src={image.url} alt={`Signature of ${student.name}`} />
          <p className="hint">
            {override
              ? 'Using the image you uploaded.'
              : `From the signature form${
                  student.signatureName ? ` — submitted as “${student.signatureName}”` : ''
                }.`}
          </p>
        </>
      )}

      {!image.loading && !image.url && (
        <p className={image.error ? 'warn-text' : 'hint'}>
          {image.error ||
            (student.hasSignature === false
              ? 'This student has not submitted the signature form.'
              : 'No signature source loaded.')}
        </p>
      )}

      <label className="replace">
        <span>{image.url ? 'Replace with a file' : 'Upload a signature'}</span>
        <input
          type="file"
          accept="image/*"
          onChange={(event) => onOverride(event.target.files?.[0] ?? null)}
        />
      </label>
      {override && (
        <button type="button" className="link" onClick={() => onOverride(null)}>
          Undo — use the form signature
        </button>
      )}
    </div>
  )
}

export default function StudentSheet({
  student,
  derived,
  scoring,
  onScoreChange,
  onReset,
  onGenerate,
  generating,
  generated,
  isEdited,
  signatureOverride,
  onSignatureOverride,
  lastResult,
}) {
  // While a recompute is in flight the previous derived values stay on screen, so the
  // table does not flash empty on every keystroke.
  const view = derived ?? student

  return (
    <section className="student-sheet">
      <header>
        <div>
          <h2>{student.name || <em>Not in the roster</em>}</h2>
          <p className="roll">{student.roll}</p>
        </div>
        <div className="totals">
          <div>
            <span className="figure">{view.total}</span>
            <span className="unit">total</span>
          </div>
          <div>
            <span className="figure">{view.percent}%</span>
            <span className="unit">of full marks</span>
          </div>
          <div className="band">
            <span className="figure small">{view.feedback}</span>
            <span className="unit">band</span>
          </div>
        </div>
      </header>

      {isEdited && (
        <p className="banner edited-banner">
          Marks edited on screen. The top sheet uses what you see here, not the
          spreadsheet.{' '}
          <button type="button" className="link" onClick={onReset}>
            Undo all edits
          </button>
        </p>
      )}

      <table className="marks-grid">
        <thead>
          <tr>
            <th>Q. No.</th>
            <th>Allotted</th>
            <th>Awarded</th>
            <th>CO</th>
            <th>Bloom’s</th>
            <th>Remarks</th>
            <th>AR Ref.</th>
          </tr>
        </thead>
        <tbody>
          {view.questions.map((question) => (
            <tr key={question.qno}>
              <td className="qno">{question.qno}</td>
              <td className="num">{question.marksAllotted}</td>
              <td className="num">
                <MarkInput
                  question={question}
                  value={student.scores[question.qno] ?? null}
                  onChange={(value) => onScoreChange(question.qno, value)}
                />
              </td>
              <td>{question.coMapping}</td>
              <td>{question.bloomLevel}</td>
              <td className={`remark ${question.remark.replace(/\s+/g, '-').toLowerCase()}`}>
                {question.remark}
              </td>
              <td className="num">{question.arReference}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="hint">
        Leave a box empty for “not attempted” — it prints as NA. A 0 prints as Wrong.
        {scoring && <em> Recalculating…</em>}
      </p>

      <div className="derived">
        <h4>Examiner’s feedback (calculated)</h4>
        <dl>
          <dt>Strengths of the Student</dt>
          <dd>{view.feedback}</dd>
          <dt>Areas for Improvement</dt>
          <dd>{view.areas}</dd>
          <dt>Suggested Corrective Measures</dt>
          <dd>{view.measures}</dd>
        </dl>
      </div>

      <SignaturePanel
        student={student}
        override={signatureOverride}
        onOverride={onSignatureOverride}
      />

      <footer className="actions">
        <button
          type="button"
          className="primary"
          onClick={onGenerate}
          disabled={generating}
        >
          {generating
            ? 'Generating…'
            : generated
              ? 'Generate again'
              : 'Generate this top sheet'}
        </button>
        {generated && !generating && (
          <span className="done-note">
            ✓ Downloaded {lastResult?.filename}
            {lastResult?.signatureStatus &&
              lastResult.signatureStatus !== 'embedded' &&
              ` — ${lastResult.signatureStatus}`}
          </span>
        )}
      </footer>
    </section>
  )
}
