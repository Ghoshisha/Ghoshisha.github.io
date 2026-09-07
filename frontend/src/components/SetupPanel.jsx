// Everything the teacher does once per class: the uploads and the paper settings.
// Collapses out of the way as soon as the class is loaded.

import { useState } from 'react'

import ClassInfoForm from './ClassInfoForm'
import FeedbackBandsEditor from './FeedbackBandsEditor'
import QuestionListEditor from './QuestionListEditor'
import RubricEditor from './RubricEditor'
import { downloadTemplate } from '../lib/api'

const UPLOADS = [
  {
    key: 'roster',
    label: 'Student roster',
    accept: '.xlsx,.csv',
    required: true,
    hint: 'Roll and Name.',
  },
  {
    key: 'marks',
    label: 'Marks sheet',
    accept: '.xlsx,.csv',
    required: true,
    hint: 'One column per question. Can be the same workbook as the roster.',
  },
  {
    key: 'signatureSheet',
    label: 'Signature form export',
    accept: '.xlsx',
    hint: 'Student signatures are pulled from its Drive links, one student at a time.',
  },
  {
    key: 'teacherSignature',
    label: 'Examiner signature',
    accept: 'image/*',
    hint: 'Goes on every top sheet.',
  },
  {
    key: 'collegeStamp',
    label: 'College stamp',
    accept: 'image/*',
    hint: 'Optional. Printed bottom-right.',
  },
]

export default function SetupPanel({
  classInfo,
  onClassInfo,
  onResetSettings,
  files,
  onFiles,
  onLoad,
  loading,
  loaded,
  collapsed,
  onToggle,
}) {
  const [showSettings, setShowSettings] = useState(false)
  // Resetting throws away everything the teacher typed, so it takes two clicks
  // rather than a browser confirm dialog.
  const [confirmReset, setConfirmReset] = useState(false)
  const ready = Boolean(files.roster && files.marks)

  const toggleSettings = () => {
    setShowSettings((v) => !v)
    setConfirmReset(false)
  }

  if (collapsed) {
    return (
      <section className="card setup collapsed">
        <div className="setup-summary">
          <strong>{classInfo.subject || 'Class'}</strong>
          <span className="muted">
            {classInfo.paperCode} · {classInfo.programme} · full marks{' '}
            {classInfo.fullMarks}
          </span>
          <span className="muted">
            {files.roster?.name}
            {files.signatureSheet ? ` · ${files.signatureSheet.name}` : ' · no signature form'}
          </span>
          <button type="button" onClick={onToggle}>
            Change files or settings
          </button>
        </div>
      </section>
    )
  }

  return (
    <section className="card setup">
      <div className="setup-header">
        <h2>Set up the class</h2>
        {loaded && (
          <button type="button" className="link" onClick={onToggle}>
            Close
          </button>
        )}
      </div>

      <div className="uploads">
        {UPLOADS.map((upload) => (
          <label key={upload.key} className="upload">
            <span>
              {upload.label}
              {upload.required && <strong className="required"> *</strong>}
            </span>
            <input
              type="file"
              accept={upload.accept}
              onChange={(event) =>
                onFiles({ ...files, [upload.key]: event.target.files?.[0] ?? null })
              }
            />
            <em className="hint">
              {files[upload.key] ? files[upload.key].name : upload.hint}
            </em>
          </label>
        ))}
      </div>

      <div className="setup-actions">
        <button type="button" className="primary" onClick={onLoad} disabled={!ready || loading}>
          {loading ? 'Loading the class…' : loaded ? 'Reload the class' : 'Load the class'}
        </button>
        <button type="button" onClick={() => downloadTemplate('roster', classInfo)}>
          Roster template
        </button>
        <button type="button" onClick={() => downloadTemplate('marks', classInfo)}>
          Marks template
        </button>
        <button type="button" className="link" onClick={toggleSettings}>
          {showSettings ? 'Hide paper settings' : 'Paper settings, questions & rubric'}
        </button>
      </div>

      {!ready && <p className="hint">A roster and a marks sheet are required.</p>}
      {loaded && (
        <p className="hint">
          Reloading re-reads the spreadsheets and <strong>discards any edits</strong> you
          have made on screen.
        </p>
      )}

      {showSettings && (
        <div className="settings">
          <ClassInfoForm classInfo={classInfo} onChange={onClassInfo} />
          <QuestionListEditor classInfo={classInfo} onChange={onClassInfo} />
          <RubricEditor classInfo={classInfo} onChange={onClassInfo} />
          <FeedbackBandsEditor classInfo={classInfo} onChange={onClassInfo} />

          <div className="settings-footer">
            <p className="hint">
              These settings are saved in this browser as you edit them, and come back
              the next time you open the app. Nothing is sent to the server.
            </p>
            <button
              type="button"
              className={confirmReset ? 'danger' : undefined}
              onClick={() => {
                if (!confirmReset) {
                  setConfirmReset(true)
                  return
                }
                setConfirmReset(false)
                onResetSettings()
              }}
            >
              {confirmReset ? 'Really reset — discard my settings' : 'Reset to defaults'}
            </button>
            {confirmReset && (
              <button type="button" className="link" onClick={() => setConfirmReset(false)}>
                Cancel
              </button>
            )}
          </div>
        </div>
      )}
    </section>
  )
}
