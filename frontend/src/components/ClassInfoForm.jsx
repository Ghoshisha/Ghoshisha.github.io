// Scalar fields of ClassInfo (spec §4.1, §8 item 1), pre-filled with the MAKAUT
// defaults so a teacher using this exact form can go straight to uploads.

const FIELDS = [
  { key: 'collegeCodeName', label: 'College Code & Name', wide: true },
  { key: 'yearSemester', label: 'Year / Semester' },
  { key: 'programme', label: 'Programme' },
  { key: 'subject', label: 'Subject' },
  { key: 'paperCode', label: 'Paper Code' },
  { key: 'upid', label: 'UPID' },
  { key: 'dateOfExam', label: 'Date of Examination' },
  { key: 'subjectTeacher', label: 'Subject Teacher' },
  { key: 'mobileNumber', label: 'Mobile Number' },
  { key: 'fullMarks', label: 'Full Marks', type: 'number' },
  { key: 'duration', label: 'Duration' },
]

const TITLE_FIELDS = [
  { key: 'universityName', label: 'University Name' },
  { key: 'formTitle', label: 'Form Title' },
  { key: 'formSubtitle', label: 'Form Subtitle' },
]

export default function ClassInfoForm({ classInfo, onChange }) {
  const set = (key, value) => onChange({ ...classInfo, [key]: value })
  const setTitle = (key, value) =>
    onChange({
      ...classInfo,
      documentTitle: { ...classInfo.documentTitle, [key]: value },
    })

  const allotted = classInfo.questions.reduce(
    (sum, q) => sum + (Number(q.marksAllotted) || 0),
    0,
  )
  const droppedNote =
    allotted !== Number(classInfo.fullMarks)
      ? `The questions allot ${allotted} marks against Full Marks of ${classInfo.fullMarks}. ` +
        'That is expected when the lowest scores are dropped — check the question groups below.'
      : null

  return (
    <section className="card">
      <h2>1. Class &amp; paper details</h2>

      <div className="grid">
        {TITLE_FIELDS.map((field) => (
          <label key={field.key} className="wide">
            <span>{field.label}</span>
            <input
              value={classInfo.documentTitle[field.key] ?? ''}
              onChange={(event) => setTitle(field.key, event.target.value)}
            />
          </label>
        ))}

        {FIELDS.map((field) => (
          <label key={field.key} className={field.wide ? 'wide' : undefined}>
            <span>{field.label}</span>
            <input
              type={field.type || 'text'}
              step={field.type === 'number' ? 'any' : undefined}
              value={classInfo[field.key] ?? ''}
              onChange={(event) =>
                set(
                  field.key,
                  field.type === 'number'
                    ? Number(event.target.value)
                    : event.target.value,
                )
              }
            />
          </label>
        ))}
      </div>

      {droppedNote && <p className="hint">{droppedNote}</p>}

      <label className="inline">
        <input
          type="checkbox"
          checked={classInfo.arReferenceMode === 'legacy'}
          onChange={(event) =>
            set('arReferenceMode', event.target.checked ? 'legacy' : 'corrected')
          }
        />
        <span>
          Use the old spreadsheet’s AR Reference behaviour
          <em>
            {' '}
            — only for reissuing a document that must match one already given to a
            student. The old formula’s Bloom lookup was broken and prints “C” for every
            question but the first.
          </em>
        </span>
      </label>
    </section>
  )
}
