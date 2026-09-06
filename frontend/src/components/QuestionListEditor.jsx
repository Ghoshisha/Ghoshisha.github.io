// Question rows and the "best N of M" groups (spec §4.1, Appendix A.1).
//
// The groups are the reason a 31-mark paper is out of 25: the lowest score in each
// fully-attempted group is dropped, exactly as the teacher's own sheet does.

const BLOOM_LEVELS = [
  'Remember',
  'Understand',
  'Apply',
  'Analyze',
  'Evaluate',
  'Create',
]

export default function QuestionListEditor({ classInfo, onChange }) {
  const { questions, questionGroups } = classInfo

  const setQuestions = (next) => onChange({ ...classInfo, questions: next })
  const setGroups = (next) => onChange({ ...classInfo, questionGroups: next })

  const updateQuestion = (index, key, value) => {
    const next = questions.map((question, i) =>
      i === index ? { ...question, [key]: value } : question,
    )
    // Renaming a question must follow it into any group that references it, or the
    // batch fails validation with "group names unknown questions".
    if (key === 'qno') {
      const previous = questions[index].qno
      setGroups(
        questionGroups.map((group) => ({
          ...group,
          questions: group.questions.map((q) => (q === previous ? value : q)),
        })),
      )
    }
    setQuestions(next)
  }

  const addQuestion = () =>
    setQuestions([
      ...questions,
      { qno: '', marksAllotted: 1, coMapping: '', bloomLevel: 'Remember' },
    ])

  const removeQuestion = (index) => {
    const removed = questions[index].qno
    setQuestions(questions.filter((_, i) => i !== index))
    setGroups(
      questionGroups
        .map((group) => ({
          ...group,
          questions: group.questions.filter((q) => q !== removed),
        }))
        .filter((group) => group.questions.length > 0),
    )
  }

  const updateGroup = (index, key, value) =>
    setGroups(
      questionGroups.map((group, i) =>
        i === index ? { ...group, [key]: value } : group,
      ),
    )

  return (
    <section className="card">
      <h2>2. Questions</h2>
      <p className="hint">
        AR Reference is calculated from each question’s Bloom level and the marks the
        student earned, so these levels change what prints on the top sheet.
      </p>

      <table className="editor">
        <thead>
          <tr>
            <th>Q. No.</th>
            <th>Marks Allotted</th>
            <th>CO Mapping</th>
            <th>Bloom’s Level</th>
            <th aria-label="Remove" />
          </tr>
        </thead>
        <tbody>
          {questions.map((question, index) => (
            <tr key={index}>
              <td>
                <input
                  value={question.qno}
                  onChange={(event) => updateQuestion(index, 'qno', event.target.value)}
                />
              </td>
              <td>
                <input
                  type="number"
                  step="any"
                  min="0"
                  value={question.marksAllotted}
                  onChange={(event) =>
                    updateQuestion(index, 'marksAllotted', Number(event.target.value))
                  }
                />
              </td>
              <td>
                <input
                  value={question.coMapping ?? ''}
                  onChange={(event) =>
                    updateQuestion(index, 'coMapping', event.target.value)
                  }
                />
              </td>
              <td>
                <select
                  value={question.bloomLevel ?? ''}
                  onChange={(event) =>
                    updateQuestion(index, 'bloomLevel', event.target.value)
                  }
                >
                  <option value="">—</option>
                  {BLOOM_LEVELS.map((level) => (
                    <option key={level} value={level}>
                      {level}
                    </option>
                  ))}
                </select>
              </td>
              <td>
                <button type="button" className="link" onClick={() => removeQuestion(index)}>
                  Remove
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <button type="button" onClick={addQuestion}>
        Add question
      </button>

      <h3>Scoring groups</h3>
      <p className="hint">
        Each group counts only its best scores. Leave this empty if every question
        counts in full.
      </p>

      {questionGroups.map((group, index) => (
        <div key={index} className="group-row">
          <label>
            <span>Label</span>
            <input
              value={group.label ?? ''}
              onChange={(event) => updateGroup(index, 'label', event.target.value)}
            />
          </label>
          <label>
            <span>Count best</span>
            <input
              type="number"
              min="1"
              max={group.questions.length}
              value={group.countBest}
              onChange={(event) =>
                updateGroup(index, 'countBest', Number(event.target.value))
              }
            />
          </label>
          <label className="wide">
            <span>Questions (comma separated)</span>
            <input
              value={group.questions.join(', ')}
              onChange={(event) =>
                updateGroup(
                  index,
                  'questions',
                  event.target.value
                    .split(',')
                    .map((q) => q.trim())
                    .filter(Boolean),
                )
              }
            />
          </label>
          <button
            type="button"
            className="link"
            onClick={() => setGroups(questionGroups.filter((_, i) => i !== index))}
          >
            Remove
          </button>
          <p className="hint">
            best {group.countBest} of {group.questions.length}
          </p>
        </div>
      ))}

      <button
        type="button"
        onClick={() =>
          setGroups([...questionGroups, { label: '', questions: [], countBest: 1 }])
        }
      >
        Add group
      </button>
    </section>
  )
}
