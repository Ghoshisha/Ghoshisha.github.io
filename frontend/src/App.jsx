import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import SetupPanel from './components/SetupPanel'
import StudentList from './components/StudentList'
import StudentSheet from './components/StudentSheet'
import {
  fetchDefaults,
  generateOne,
  pingHealth,
  readManifest,
  requestGenerate,
  requestPreview,
  scoreStudent,
} from './lib/api'
import {
  clearStoredClassInfo,
  loadStoredClassInfo,
  storeClassInfo,
} from './lib/settings'

const EMPTY_FILES = {
  roster: null,
  marks: null,
  signatureSheet: null,
  teacherSignature: null,
  collegeStamp: null,
}

export default function App() {
  const [classInfo, setClassInfo] = useState(null)
  const [files, setFiles] = useState(EMPTY_FILES)
  const [setupOpen, setSetupOpen] = useState(true)

  // The class as loaded from the spreadsheets, keyed by roll.
  const [students, setStudents] = useState([])
  const [issues, setIssues] = useState([])
  const [selectedRoll, setSelectedRoll] = useState(null)
  const [query, setQuery] = useState('')

  // Marks the teacher has changed on screen, and the server's re-derived view of them.
  const [edits, setEdits] = useState({})
  const [derived, setDerived] = useState({})
  const [signatureOverrides, setSignatureOverrides] = useState({})
  const [generatedResults, setGeneratedResults] = useState({})

  const [busy, setBusy] = useState(null)
  const [scoring, setScoring] = useState(false)
  const [error, setError] = useState(null)
  const [batchResult, setBatchResult] = useState(null)
  const [server, setServer] = useState('waking')

  // The untouched server defaults, kept so "reset" needs no second round trip -- and
  // so the autosave below can tell "never edited" from "edited back to the defaults".
  const pristine = useRef(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      const awake = await pingHealth()
      if (cancelled) return
      setServer(awake ? 'ready' : 'unreachable')
      if (!awake) return
      try {
        const payload = await fetchDefaults()
        if (cancelled) return
        pristine.current = payload
        // Paper settings from a previous visit win over the defaults they were
        // derived from; anything unrecognisable falls back to the defaults.
        setClassInfo(loadStoredClassInfo(payload) ?? payload)
      } catch (exc) {
        if (!cancelled) setError(exc.message)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  // Paper settings survive a reload; marks and uploads deliberately do not. Untouched
  // defaults are not written, so a future change to them is not shadowed by a stale copy.
  useEffect(() => {
    if (!classInfo || classInfo === pristine.current) return
    storeClassInfo(classInfo)
  }, [classInfo])

  const onResetSettings = useCallback(() => {
    if (!pristine.current) return
    clearStoredClassInfo()
    setClassInfo(pristine.current)
  }, [])

  // Students carrying whatever marks are currently on screen.
  const merged = useMemo(
    () =>
      students.map((student) =>
        edits[student.roll] ? { ...student, scores: edits[student.roll] } : student,
      ),
    [students, edits],
  )

  const selected = merged.find((student) => student.roll === selectedRoll) ?? null
  const editedRolls = useMemo(() => new Set(Object.keys(edits)), [edits])
  const generatedRolls = useMemo(
    () => new Set(Object.keys(generatedResults)),
    [generatedResults],
  )

  const loadClass = useCallback(async () => {
    setBusy('load')
    setError(null)
    try {
      const payload = await requestPreview({ ...files, classInfo })
      setStudents(payload.students)
      setIssues(payload.issues)
      // A reload re-reads the spreadsheets, so on-screen edits no longer apply.
      setEdits({})
      setDerived({})
      setSignatureOverrides({})
      setGeneratedResults({})
      setSelectedRoll(payload.students[0]?.roll ?? null)
      setSetupOpen(payload.students.length === 0)
    } catch (exc) {
      setError(exc.message)
    } finally {
      setBusy(null)
    }
  }, [files, classInfo])

  // Recompute on the server, debounced so typing does not fire a request per keystroke.
  const timer = useRef(null)
  const requestRecompute = useCallback(
    (roll, name, scores) => {
      if (timer.current) clearTimeout(timer.current)
      setScoring(true)
      timer.current = setTimeout(async () => {
        try {
          const payload = await scoreStudent({ classInfo, roll, name, scores })
          setDerived((current) => ({ ...current, [roll]: payload }))
        } catch (exc) {
          setError(exc.message)
        } finally {
          setScoring(false)
        }
      }, 250)
    },
    [classInfo],
  )

  const onScoreChange = useCallback(
    (qno, value) => {
      if (!selected) return
      const scores = { ...selected.scores, [qno]: value }
      setEdits((current) => ({ ...current, [selected.roll]: scores }))
      requestRecompute(selected.roll, selected.name, scores)
    },
    [selected, requestRecompute],
  )

  const onReset = useCallback(() => {
    if (!selected) return
    setEdits((current) => {
      const next = { ...current }
      delete next[selected.roll]
      return next
    })
    setDerived((current) => {
      const next = { ...current }
      delete next[selected.roll]
      return next
    })
  }, [selected])

  const onGenerate = useCallback(async () => {
    if (!selected) return
    setBusy('one')
    setError(null)
    try {
      const result = await generateOne({
        classInfo,
        student: {
          roll: selected.roll,
          name: selected.name,
          scores: selected.scores,
        },
        driveId: signatureOverrides[selected.roll] ? null : selected.driveId,
        teacherSignature: files.teacherSignature,
        collegeStamp: files.collegeStamp,
        studentSignature: signatureOverrides[selected.roll] ?? null,
      })
      setGeneratedResults((current) => ({ ...current, [selected.roll]: result }))
    } catch (exc) {
      setError(exc.message)
    } finally {
      setBusy(null)
    }
  }, [selected, classInfo, files, signatureOverrides])

  const onGenerateAll = useCallback(async () => {
    setBusy('batch')
    setError(null)
    try {
      const response = await requestGenerate({ ...files, classInfo })
      setBatchResult({ ...response, manifest: await readManifest(response.blob) })
    } catch (exc) {
      setError(exc.message)
    } finally {
      setBusy(null)
    }
  }, [files, classInfo])

  const fileIssues = issues.filter((issue) => !issue.roll)

  return (
    <main>
      <header className="app-header">
        <div>
          <h1>Assessment Top-Sheet Generator</h1>
          <p>
            Load the class once, then check each student’s marks and generate their top
            sheet.
          </p>
        </div>
        {students.length > 0 && (
          <button
            type="button"
            onClick={onGenerateAll}
            disabled={busy === 'batch'}
            title="Generate every student at once, as a ZIP"
          >
            {busy === 'batch' ? 'Generating all…' : 'Generate all as ZIP'}
          </button>
        )}
      </header>

      {server === 'waking' && (
        <p className="banner">Waking the server — this can take about 30 seconds…</p>
      )}
      {server === 'unreachable' && (
        <p className="banner error">
          Cannot reach the server. Check it is running, then reload.
        </p>
      )}
      {error && <p className="banner error">{error}</p>}

      {classInfo && (
        <SetupPanel
          classInfo={classInfo}
          onClassInfo={setClassInfo}
          onResetSettings={onResetSettings}
          files={files}
          onFiles={setFiles}
          onLoad={loadClass}
          loading={busy === 'load'}
          loaded={students.length > 0}
          collapsed={!setupOpen && students.length > 0}
          onToggle={() => setSetupOpen((open) => !open)}
        />
      )}

      {fileIssues.length > 0 && (
        <ul className="issues">
          {fileIssues.map((issue, index) => (
            <li key={index} className={issue.level}>
              {issue.message}
            </li>
          ))}
        </ul>
      )}

      {batchResult && (
        <p className="banner">
          Downloaded <strong>{batchResult.filename}</strong>
          {batchResult.manifest &&
            ` — ${batchResult.manifest.generated} of ${batchResult.manifest.studentCount} with a signature embedded.`}
        </p>
      )}

      {students.length > 0 && (
        <div className="dashboard">
          <StudentList
            students={merged}
            selectedRoll={selectedRoll}
            onSelect={setSelectedRoll}
            query={query}
            onQuery={setQuery}
            editedRolls={editedRolls}
            generatedRolls={generatedRolls}
          />

          {selected ? (
            <StudentSheet
              key={selected.roll}
              student={selected}
              derived={derived[selected.roll]}
              scoring={scoring}
              onScoreChange={onScoreChange}
              onReset={onReset}
              onGenerate={onGenerate}
              generating={busy === 'one'}
              generated={Boolean(generatedResults[selected.roll])}
              lastResult={generatedResults[selected.roll]}
              isEdited={editedRolls.has(selected.roll)}
              signatureOverride={signatureOverrides[selected.roll] ?? null}
              onSignatureOverride={(file) =>
                setSignatureOverrides((current) => ({
                  ...current,
                  [selected.roll]: file,
                }))
              }
            />
          ) : (
            <section className="student-sheet empty">
              <p>Pick a student from the list.</p>
            </section>
          )}
        </div>
      )}

      {students.length === 0 && classInfo && !busy && (
        <p className="hint centered">
          Upload a roster and a marks sheet above, then choose “Load the class”.
        </p>
      )}

      <footer>
        <p>
          Nothing is stored on the server. Paper settings are remembered in this
          browser; marks you edit here live in this tab until you generate.
        </p>
      </footer>
    </main>
  )
}
