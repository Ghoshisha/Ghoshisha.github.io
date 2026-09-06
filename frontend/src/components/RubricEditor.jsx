// The four rubric rows printed above the marks table (spec §4.1, §7 item 3).

const COLUMNS = [
  { key: 'criteria', label: 'Criteria' },
  { key: 'excellent', label: 'Excellent (80–100%)' },
  { key: 'good', label: 'Good (60–79%)' },
  { key: 'satisfactory', label: 'Satisfactory (40–59%)' },
  { key: 'needsImprovement', label: 'Needs Improvement (<40%)' },
]

export default function RubricEditor({ classInfo, onChange }) {
  const { rubric } = classInfo

  const update = (index, key, value) =>
    onChange({
      ...classInfo,
      rubric: rubric.map((row, i) => (i === index ? { ...row, [key]: value } : row)),
    })

  return (
    <section className="card">
      <h2>3. Assessment rubrics</h2>
      <table className="editor">
        <thead>
          <tr>
            <th />
            {COLUMNS.map((column) => (
              <th key={column.key}>{column.label}</th>
            ))}
            <th aria-label="Remove" />
          </tr>
        </thead>
        <tbody>
          {rubric.map((row, index) => (
            <tr key={index}>
              <td className="narrow">
                <input
                  value={row.label}
                  onChange={(event) => update(index, 'label', event.target.value)}
                />
              </td>
              {COLUMNS.map((column) => (
                <td key={column.key}>
                  <textarea
                    rows={2}
                    value={row[column.key] ?? ''}
                    onChange={(event) => update(index, column.key, event.target.value)}
                  />
                </td>
              ))}
              <td>
                <button
                  type="button"
                  className="link"
                  onClick={() =>
                    onChange({
                      ...classInfo,
                      rubric: rubric.filter((_, i) => i !== index),
                    })
                  }
                >
                  Remove
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button
        type="button"
        onClick={() =>
          onChange({
            ...classInfo,
            rubric: [
              ...rubric,
              {
                label: '',
                criteria: '',
                excellent: '',
                good: '',
                satisfactory: '',
                needsImprovement: '',
              },
            ],
          })
        }
      >
        Add rubric row
      </button>
    </section>
  )
}
