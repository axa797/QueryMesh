/** Local display names for chat threads (browser-only; not synced to server). */

const STORAGE_KEY = "querymesh_session_titles";

export function loadSessionTitles(): Record<string, string> {
  if (typeof window === "undefined") return {};
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const o = JSON.parse(raw) as unknown;
    if (typeof o !== "object" || o === null) return {};
    const out: Record<string, string> = {};
    for (const [k, v] of Object.entries(o)) {
      if (typeof v === "string") {
        const t = v.trim();
        if (t) out[k] = t.slice(0, 160);
      }
    }
    return out;
  } catch {
    return {};
  }
}

export function saveSessionTitle(sessionId: string, title: string): Record<string, string> {
  const trimmed = title.trim().slice(0, 160);
  const prev = loadSessionTitles();
  const next = { ...prev };
  if (!trimmed) {
    delete next[sessionId];
  } else {
    next[sessionId] = trimmed;
  }
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    /* quota / private mode */
  }
  return next;
}
