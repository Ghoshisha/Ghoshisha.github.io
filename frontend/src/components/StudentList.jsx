// The class roll-call down the left of the dashboard.
//
// Status is at a glance: whether the marks are complete, whether a signature is on
// file, and whether this student's top sheet has already been generated.

export function studentStatus(student, { edited, generated }) {
  if (generated) return { icon: '✓', tone: 'done', label: 'Top sheet generated' }
  if (edited) return { icon: '●', tone: 'edited', label: 'Marks edited, not yet generated' }
  if (student.hasSignature === false) {
    return { icon: '✍', tone: 'warn', label: 'No signature on file' }
  }
  if (student.missingScores.length > 0) {
    return {
      icon: '!',
      tone: 'warn',
      label: `No mark for ${student.missingScores.join(', ')}`,
    }
  }
  return { icon: '○', tone: 'ok', label: 'Ready' }
}

export default function StudentList({
  students,
  selectedRoll,
  onSelect,
  query,
  onQuery,
  editedRolls,
  generatedRolls,
}) {
  const needle = query.trim().toLowerCase()
  const shown = needle
    ? students.filter(
        (student) =>
          student.roll.toLowerCase().includes(needle) ||
          (student.name || '').toLowerCase().includes(needle),
      )
    : students

  return (
    <aside className="student-list">
      <div className="list-head">
        <input
          type="search"
          placeholder="Search roll or name…"
          value={query}
          onChange={(event) => onQuery(event.target.value)}
        />
        <p className="hint">
          {generatedRolls.size} of {students.length} generated
        </p>
      </div>

      <ul>
        {shown.map((student) => {
          const status = studentStatus(student, {
            edited: editedRolls.has(student.roll),
            generated: generatedRolls.has(student.roll),
          })
          return (
            <li key={student.roll}>
              <button
                type="button"
                className={student.roll === selectedRoll ? 'selected' : undefined}
                onClick={() => onSelect(student.roll)}
              >
                <span className={`dot ${status.tone}`} title={status.label}>
                  {status.icon}
                </span>
                <span className="who">
                  <strong>{student.name || 'Unnamed'}</strong>
                  <em>{student.roll}</em>
                </span>
                <span className="score">{student.total}</span>
              </button>
            </li>
          )
        })}
        {shown.length === 0 && <li className="empty">No student matches “{query}”.</li>}
      </ul>
    </aside>
  )
}
