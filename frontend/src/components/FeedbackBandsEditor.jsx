// Score bands driving Strengths / Areas / Measures (spec §4.1, §9.4).
//
// Bands are a percentage of Full Marks, not fixed mark cutoffs, so the same bands work
// for a 25-, 30- or 50-mark paper.

export default function FeedbackBandsEditor({ classInfo, onChange }) {
  const { feedbackBands, fullMarks } = classInfo

  const update = (index, key, value) =>
    onChange({
      ...classInfo,
      feedbackBands: feedbackBands.map((band, i) =>
        i === index ? { ...band, [key]: value } : band,
      ),
    })

  return (
    <section className="card">
      <h2>4. Feedback bands</h2>
      <p className="hint">
        Bands are percentages of Full Marks ({fullMarks}), so the first band whose
        ceiling clears the student’s percentage wins.
      </p>
      <table className="editor">
        <thead>
          <tr>
            <th>Up to %</th>
            <th>Equivalent marks</th>
            <th>Strengths of the Student</th>
            <th>Areas for Improvement</th>
            <th>Suggested Corrective Measures</th>
            <th aria-label="Remove" />
          </tr>
        </thead>
        <tbody>
          {feedbackBands.map((band, index) => (
            <tr key={index}>
              <td className="narrow">
                <input
                  type="number"
                  min="0"
                  max="100"
                  value={band.maxPercent}
                  onChange={(event) =>
                    update(index, 'maxPercent', Number(event.target.value))
                  }
                />
              </td>
              <td className="narrow muted">
                ≤ {((band.maxPercent / 100) * fullMarks).toFixed(1).replace(/\.0$/, '')}
              </td>
              {['feedback', 'areas', 'measures'].map((key) => (
                <td key={key}>
                  <input
                    value={band[key] ?? ''}
                    onChange={(event) => update(index, key, event.target.value)}
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
                      feedbackBands: feedbackBands.filter((_, i) => i !== index),
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
            feedbackBands: [
              ...feedbackBands,
              { maxPercent: 100, feedback: '', areas: '', measures: '' },
            ],
          })
        }
      >
        Add band
      </button>
    </section>
  )
}
