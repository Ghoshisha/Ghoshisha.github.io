// Paper settings remembered between visits.
//
// The spec keeps the *server* stateless (§4, "no database, no persistent storage"),
// so this is browser-local only: the teacher's own paper settings, in their own
// browser, never leaving it. Marks and uploads are still per-session.

const KEY = 'topsheet.classInfo.v1'

// A stored object is only trusted as far as its shape. Anything else -- an older
// format, a half-written value, something else entirely on this key -- is dropped in
// favour of the server defaults rather than posted to an endpoint that would reject it.
function plausible(value) {
  return (
    value &&
    typeof value === 'object' &&
    !Array.isArray(value) &&
    Array.isArray(value.questions) &&
    Array.isArray(value.rubric) &&
    Array.isArray(value.feedbackBands)
  )
}

// Fields the backend has gained since the copy was stored must still arrive, so the
// stored settings are laid over the fresh defaults rather than used on their own.
function mergeOntoDefaults(defaults, stored) {
  return {
    ...defaults,
    ...stored,
    documentTitle: { ...defaults.documentTitle, ...stored.documentTitle },
  }
}

export function loadStoredClassInfo(defaults) {
  try {
    const raw = window.localStorage.getItem(KEY)
    if (!raw) return null
    const stored = JSON.parse(raw)
    return plausible(stored) ? mergeOntoDefaults(defaults, stored) : null
  } catch {
    // Unparseable, or storage unavailable (private mode, site data blocked).
    return null
  }
}

export function storeClassInfo(classInfo) {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(classInfo))
  } catch {
    /* Storage unavailable or full -- settings simply do not outlive the tab. */
  }
}

export function clearStoredClassInfo() {
  try {
    window.localStorage.removeItem(KEY)
  } catch {
    /* Nothing to clear if storage is unavailable. */
  }
}
