"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  clearSession,
  getPortalJwt,
  getStoredApiKey,
  SESSION_STORAGE_KEY,
  setStoredApiKey,
} from "@/lib/auth-storage";
import {
  loadSessionTitles,
  saveSessionTitle,
} from "@/lib/chat-session-titles";
import {
  ApiError,
  fetchQueryHistory,
  fetchQuerySessions,
  formatQueryReply,
  postJson,
  postQueryStream,
  type ApiKeyCreateResponse,
  type HistoryMessageRow,
  type QueryMeshSuccess,
  type QuerySessionItem,
  type SourceCard,
} from "@/lib/querymesh";

const STREAM_PREF_KEY = "querymesh_stream_mode";

type Turn = {
  id: string;
  role: "user" | "assistant" | "tool";
  content: string;
  latencyMs?: number;
  sourceCards?: SourceCard[];
  phases?: string[];
};

function historyToTurns(rows: HistoryMessageRow[]): Turn[] {
  return rows
    .filter((r) => r.role !== "tool")
    .map((r, idx) => ({
      id: `h-${idx}-${r.role}`,
      role: r.role as "user" | "assistant",
      content: r.content,
      sourceCards:
        r.role === "assistant" && Array.isArray(r.source_cards)
          ? r.source_cards
          : undefined,
    }));
}

function defaultSessionTitle(sid: string): string {
  const t = sid.replace(/-/g, "");
  return t.length >= 8 ? `Chat · ${t.slice(0, 8)}` : `Chat · ${sid.slice(0, 8)}`;
}

export default function ChatPage() {
  const [apiKey, setApiKey] = useState("");
  const [query, setQuery] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [sessions, setSessions] = useState<QuerySessionItem[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [streamMode, setStreamMode] = useState(false);
  const [streamingPhases, setStreamingPhases] = useState<string[]>([]);
  const [assistantDraft, setAssistantDraft] = useState("");
  const [sessionTitles, setSessionTitles] = useState<Record<string, string>>({});
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const renameInputRef = useRef<HTMLInputElement>(null);
  const transcriptPanelRef = useRef<HTMLDivElement>(null);
  const router = useRouter();

  useEffect(() => {
    const jwt = getPortalJwt();
    if (!jwt) {
      router.replace("/register");
      return;
    }
    const k = getStoredApiKey();
    if (k) setApiKey(k);
    if (typeof window !== "undefined") {
      setSessionId(sessionStorage.getItem(SESSION_STORAGE_KEY));
      const s = localStorage.getItem(STREAM_PREF_KEY);
      if (s === "1" || s === "true") setStreamMode(true);
      setSessionTitles(loadSessionTitles());
    }
  }, [router]);

  useEffect(() => {
    if (editingSessionId && renameInputRef.current) {
      renameInputRef.current.focus();
      renameInputRef.current.select();
    }
  }, [editingSessionId]);

  useEffect(() => {
    const panel = transcriptPanelRef.current;
    if (!panel) return;
    panel.scrollTo({ top: panel.scrollHeight, behavior: "smooth" });
  }, [turns, loading, streamingPhases, assistantDraft]);

  const hydrateFromServer = useCallback(async (sid: string, key: string) => {
    try {
      const rows = await fetchQueryHistory(sid, {
        Authorization: `Bearer ${key}`,
      });
      setTurns(historyToTurns(rows));
    } catch {
      setTurns([]);
    }
  }, []);

  const loadSessions = useCallback(async (key: string) => {
    setSessionsLoading(true);
    try {
      const items = await fetchQuerySessions({
        Authorization: `Bearer ${key}`,
      });
      setSessions(items);
    } catch {
      setSessions([]);
    } finally {
      setSessionsLoading(false);
    }
  }, []);

  function labelForSession(sid: string): string {
    const custom = sessionTitles[sid]?.trim();
    if (custom) return custom;
    return defaultSessionTitle(sid);
  }

  function beginRename(sid: string) {
    setEditingSessionId(sid);
    setRenameDraft(labelForSession(sid));
  }

  function commitRename() {
    if (!editingSessionId) return;
    const next = saveSessionTitle(editingSessionId, renameDraft);
    setSessionTitles(next);
    setEditingSessionId(null);
    setRenameDraft("");
  }

  function cancelRename() {
    setEditingSessionId(null);
    setRenameDraft("");
  }

  useEffect(() => {
    const key = apiKey.trim();
    const sid = sessionId?.trim();
    if (!key || !sid) return;
    void hydrateFromServer(sid, key);
  }, [apiKey, sessionId, hydrateFromServer]);

  useEffect(() => {
    const key = apiKey.trim();
    if (!key) return;
    void loadSessions(key);
  }, [apiKey, loadSessions]);

  function setStreamModePersist(next: boolean) {
    setStreamMode(next);
    if (typeof window !== "undefined") {
      localStorage.setItem(STREAM_PREF_KEY, next ? "1" : "0");
    }
  }

  async function remintKey(): Promise<string | null> {
    const jwt = getPortalJwt();
    if (!jwt) return null;
    try {
      const res = await postJson<ApiKeyCreateResponse>(
        "/account/api-keys",
        {},
        {
          Authorization: `Bearer ${jwt}`,
        },
      );
      setStoredApiKey(res.api_key);
      setApiKey(res.api_key);
      return res.api_key;
    } catch {
      return null;
    }
  }

  function newConversation() {
    clearSession();
    setSessionId(null);
    setTurns([]);
    setStreamingPhases([]);
    setAssistantDraft("");
    setErr(null);
    const key = apiKey.trim();
    if (key) void loadSessions(key);
    textareaRef.current?.focus();
  }

  function selectConversation(sid: string) {
    setErr(null);
    setSessionId(sid);
    if (typeof window !== "undefined")
      sessionStorage.setItem(SESSION_STORAGE_KEY, sid);
    const key = apiKey.trim();
    if (key) void hydrateFromServer(sid, key);
  }

  async function send() {
    setErr(null);
    const q = query.trim();
    if (!q) return;

    let key = apiKey.trim();
    if (!key) {
      router.push("/login");
      return;
    }

    const userTurn: Turn = {
      id: `u-${Date.now()}`,
      role: "user",
      content: q,
    };
    setTurns((prev) => [...prev, userTurn]);
    setStreamingPhases([]);
    setAssistantDraft("");
    setLoading(true);

    const body: { query: string; session_id?: string } = { query: q };
    const sid = sessionId?.trim();
    if (sid) body.session_id = sid;

    const authHeader = (k: string) => ({ Authorization: `Bearer ${k}` });

    let data: QueryMeshSuccess | null = null;
    let phasesSeen: string[] = [];

    async function consumeStream(hdr: Record<string, string>): Promise<void> {
      await postQueryStream(body, hdr, (ev) => {
        if (ev.type === "phase") {
          phasesSeen = phasesSeen.includes(ev.node)
            ? phasesSeen
            : [...phasesSeen, ev.node];
          setStreamingPhases(phasesSeen);
        } else if (ev.type === "assistant_partial") {
          setAssistantDraft(ev.message);
        } else if (ev.type === "done") {
          data = ev.payload;
        } else if (ev.type === "error") {
          throw new Error(ev.message);
        }
      });
    }

    try {
      if (streamMode) {
        try {
          await consumeStream(authHeader(key));
        } catch (ex) {
          if (ex instanceof ApiError && ex.status === 401) {
            const fresh = await remintKey();
            if (!fresh) {
              router.push("/login");
              setTurns((prev) => prev.filter((t) => t.id !== userTurn.id));
              return;
            }
            key = fresh;
            phasesSeen = [];
            setAssistantDraft("");
            await consumeStream(authHeader(key));
          } else {
            throw ex;
          }
        }
      } else {
        try {
          data = await postJson<QueryMeshSuccess>(
            "/query",
            body,
            authHeader(key),
          );
        } catch (ex) {
          if (ex instanceof ApiError && ex.status === 401) {
            const fresh = await remintKey();
            if (!fresh) {
              router.push("/login");
              setTurns((prev) => prev.filter((t) => t.id !== userTurn.id));
              return;
            }
            key = fresh;
            data = await postJson<QueryMeshSuccess>(
              "/query",
              body,
              authHeader(key),
            );
          } else {
            throw ex;
          }
        }
      }

      setStreamingPhases([]);
      setAssistantDraft("");

      if (!data) {
        setErr(
          streamMode ? "Stream ended without a result" : "No response",
        );
        setTurns((prev) => prev.filter((t) => t.id !== userTurn.id));
        return;
      }

      const answer = formatQueryReply(data);
      const cards = Array.isArray(data.response?.source_cards)
        ? (data.response!.source_cards as SourceCard[])
        : undefined;

      const assistantTurn: Turn = {
        id: `a-${Date.now()}`,
        role: "assistant",
        content: answer,
        latencyMs: data.latency_ms,
        sourceCards: cards,
        phases: phasesSeen.length ? phasesSeen : undefined,
      };

      setTurns((prev) => [...prev, assistantTurn]);

      if (data.session_id && typeof window !== "undefined") {
        sessionStorage.setItem(SESSION_STORAGE_KEY, data.session_id);
        setSessionId(data.session_id);
      }

      if (key) void loadSessions(key);

      setQuery("");
      textareaRef.current?.focus();
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : "Query failed");
      setTurns((prev) => prev.filter((t) => t.id !== userTurn.id));
    } finally {
      setStreamingPhases([]);
      setAssistantDraft("");
      setLoading(false);
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      void send();
    }
  }

  return (
    <div className="relative flex h-full min-h-0 min-w-0 flex-1 overflow-hidden rounded-2xl border border-zinc-800/80 bg-gradient-to-br from-zinc-950 via-zinc-900/40 to-zinc-950 shadow-[0_0_0_1px_rgba(255,255,255,0.03),0_0_60px_-12px_rgba(56,189,248,0.12),0_25px_80px_-20px_rgba(0,0,0,0.65)] ring-1 ring-white/5">
      {/* Sidebar */}
      <aside className="flex w-[min(100%,17rem)] shrink-0 flex-col border-r border-zinc-800/80 bg-zinc-950/75 backdrop-blur-md">
        <div className="border-b border-zinc-800/70 bg-gradient-to-b from-white/[0.05] to-transparent px-3 py-3">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-sky-400/90">
            Conversations
          </h2>
          <button
            type="button"
            onClick={newConversation}
            className="mt-2 flex w-full items-center justify-center gap-2 rounded-xl border border-sky-500/30 bg-sky-500/10 py-2 text-sm font-medium text-sky-200 transition hover:border-sky-400/50 hover:bg-sky-500/20"
          >
            New chat
          </button>
        </div>
        <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-2 py-2">
          {sessionsLoading && (
            <p className="px-2 py-2 text-xs text-zinc-500">Loading…</p>
          )}
          {!sessionsLoading && sessions.length === 0 && (
            <p className="px-2 py-3 text-xs leading-relaxed text-zinc-500">
              Past chats appear here after you send a message.
            </p>
          )}
          {sessions.map((s) => {
            const active = sessionId?.trim() === s.session_id;
            const editing = editingSessionId === s.session_id;
            return (
              <div
                key={s.session_id}
                className={`group flex items-stretch gap-0.5 rounded-lg border border-transparent text-sm transition ${
                  active
                    ? "border-sky-500/35 bg-sky-500/15 text-zinc-100 shadow-inner"
                    : "text-zinc-400 hover:border-zinc-800 hover:bg-zinc-800/50 hover:text-zinc-200"
                }`}
              >
                {editing ? (
                  <input
                    ref={renameInputRef}
                    type="text"
                    value={renameDraft}
                    onChange={(e) => setRenameDraft(e.target.value)}
                    onBlur={() => {
                      commitRename();
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        commitRename();
                      }
                      if (e.key === "Escape") {
                        e.preventDefault();
                        cancelRename();
                      }
                    }}
                    className="min-w-0 flex-1 rounded-md border border-zinc-600 bg-zinc-950 px-2 py-2 text-sm text-zinc-100 outline-none ring-sky-500/40 focus:ring-2"
                    aria-label="Chat name"
                  />
                ) : (
                  <>
                    <button
                      type="button"
                      onClick={() => selectConversation(s.session_id)}
                      className="min-w-0 flex-1 px-2.5 py-2.5 text-left"
                    >
                      <span className="block truncate font-medium">
                        {labelForSession(s.session_id)}
                      </span>
                      {s.last_checkpoint_id ? (
                        <span className="mt-0.5 block truncate font-mono text-[10px] text-zinc-600">
                          {s.session_id.slice(0, 8)}…
                        </span>
                      ) : null}
                    </button>
                    <button
                      type="button"
                      title="Rename chat"
                      aria-label={`Rename ${labelForSession(s.session_id)}`}
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        beginRename(s.session_id);
                      }}
                      className="shrink-0 self-stretch rounded-md px-1.5 text-zinc-500 transition hover:text-sky-300 sm:opacity-0 sm:group-hover:opacity-100"
                    >
                      <svg
                        xmlns="http://www.w3.org/2000/svg"
                        viewBox="0 0 20 20"
                        fill="currentColor"
                        className="size-4"
                        aria-hidden
                      >
                        <path d="M2.695 14.295a2.5 2.5 0 0 0-.64 1.11l-.375 1.498a.5.5 0 0 0 .61.61l1.499-.375a2.5 2.5 0 0 0 1.11-.64l8.8-8.8-2.47-2.47-8.534 8.467Z" />
                        <path d="M14.03 4.03a1.5 1.5 0 0 1 2.122 0l.818.818a1.5 1.5 0 0 1 0 2.122l-1.06 1.06-2.94-2.94 1.06-1.06Z" />
                      </svg>
                    </button>
                  </>
                )}
              </div>
            );
          })}
        </div>
      </aside>

      {/* Main column */}
      <div className="relative flex min-w-0 flex-1 flex-col bg-zinc-950/10">
        <div className="pointer-events-none absolute inset-x-0 top-0 z-0 h-px bg-gradient-to-r from-transparent via-sky-500/20 to-transparent" />
        <div
          ref={transcriptPanelRef}
          className="relative z-10 min-h-0 flex-1 overflow-y-auto px-3 py-4 sm:px-5"
        >
          <div className="mx-auto max-w-3xl min-w-0 space-y-4">
            {turns.length === 0 && !loading && (
              <div className="rounded-2xl border border-dashed border-zinc-700/60 bg-zinc-900/30 px-6 py-12 text-center">
                <p className="text-sm font-medium text-zinc-300">
                  Search the loaded knowledge base
                </p>
                <p className="mt-2 text-xs text-zinc-500">
                  Grounded retrieval (no open web), optional code execution in a
                  sandbox. Docs skew Cloud Next 2026. Use the composer below — ⌘↵
                  to send.
                </p>
              </div>
            )}
            {turns.map((t) =>
              t.role === "user" ? (
                <div key={t.id} className="flex min-w-0 justify-end">
                  <div className="max-w-[min(100%,28rem)] min-w-0 rounded-2xl rounded-br-md border border-sky-500/25 bg-sky-500/15 px-4 py-3 shadow-lg shadow-sky-950/20">
                    <div className="text-[10px] font-medium uppercase tracking-wide text-sky-400/90">
                      You
                    </div>
                    <pre className="mt-1 min-w-0 max-w-full overflow-x-auto whitespace-pre-wrap break-words font-sans text-sm leading-relaxed text-zinc-100">
                      {t.content}
                    </pre>
                  </div>
                </div>
              ) : (
                <div key={t.id} className="flex min-w-0 justify-start">
                  <div className="max-w-[min(100%,36rem)] min-w-0 rounded-2xl rounded-bl-md border border-zinc-700/50 bg-zinc-900/80 px-4 py-3 shadow-inner backdrop-blur-sm">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-[10px] font-semibold uppercase tracking-wide text-zinc-500">
                        Assistant
                      </span>
                      {t.latencyMs != null && (
                        <span className="rounded-md bg-zinc-800/80 px-1.5 py-0.5 text-[10px] text-zinc-500">
                          {t.latencyMs} ms
                        </span>
                      )}
                    </div>
                    {t.phases && t.phases.length > 0 && (
                      <details className="mt-2 text-[11px] text-zinc-500">
                        <summary className="cursor-pointer select-none hover:text-zinc-400">
                          Pipeline trace
                        </summary>
                        <p className="mt-1 font-mono text-[10px] text-zinc-600">
                          {t.phases.join(" → ")}
                        </p>
                      </details>
                    )}
                    <pre className="mt-2 min-w-0 max-w-full overflow-x-auto whitespace-pre-wrap break-words font-sans text-sm leading-relaxed text-zinc-100">
                      {t.content}
                    </pre>
                    {t.sourceCards && t.sourceCards.length > 0 && (
                      <details className="mt-3 border-t border-zinc-800 pt-3 [&_summary::-webkit-details-marker]:hidden">
                        <summary className="cursor-pointer select-none text-[10px] font-semibold uppercase tracking-wide text-zinc-500 hover:text-zinc-400">
                          Sources ({t.sourceCards.length})
                        </summary>
                        <ul className="mt-3 space-y-2">
                          {t.sourceCards.map((s, idx) => (
                            <li
                              key={`${s.point_id || "np"}-${idx}-${t.id}`}
                              className="rounded-lg border border-zinc-800/80 bg-zinc-950/50 px-3 py-2"
                            >
                              <div className="text-xs font-medium text-sky-400">
                                {(s.source_doc || "unknown").slice(0, 120)}
                                {s.section ? (
                                  <span className="text-zinc-500">
                                    {" "}
                                    · {String(s.section).slice(0, 120)}
                                  </span>
                                ) : null}
                              </div>
                              {s.excerpt ? (
                                <p className="mt-1 text-xs leading-relaxed text-zinc-400">
                                  {String(s.excerpt).slice(0, 500)}
                                  {String(s.excerpt).length >= 500 ? "…" : ""}
                                </p>
                              ) : null}
                            </li>
                          ))}
                        </ul>
                      </details>
                    )}
                  </div>
                </div>
              ),
            )}
            {loading && streamMode && assistantDraft.trim() !== "" && (
              <div className="flex min-w-0 justify-start">
                <div className="max-w-[min(100%,36rem)] min-w-0 rounded-2xl border border-amber-500/25 bg-amber-500/10 px-4 py-3">
                  <div className="text-[10px] font-medium uppercase tracking-wide text-amber-400/90">
                    Generating
                  </div>
                  <pre className="mt-1 min-w-0 max-w-full overflow-x-auto whitespace-pre-wrap break-words font-sans text-sm leading-relaxed text-zinc-100">
                    {assistantDraft}
                  </pre>
                </div>
              </div>
            )}
            {loading && streamingPhases.length > 0 && (
              <p className="text-center text-[11px] text-zinc-500">
                {streamingPhases.join(" · ")}
              </p>
            )}
            {loading && !streamMode && (
              <p className="text-center text-sm text-zinc-500">
                Working on your answer…
              </p>
            )}
          </div>
        </div>

        {/* Composer dock */}
        <div className="shrink-0 border-t border-zinc-800/80 bg-gradient-to-t from-zinc-950/95 to-zinc-950/80 px-3 py-3 backdrop-blur-md sm:px-5">
          <div className="mx-auto max-w-3xl">
            {err && (
              <p className="mb-2 rounded-lg border border-red-900/40 bg-red-950/30 px-3 py-2 text-sm text-red-300">
                {err}
              </p>
            )}
            <textarea
              ref={textareaRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={onKeyDown}
              rows={3}
              disabled={loading}
              className="w-full resize-none rounded-xl border border-zinc-700/80 bg-zinc-900/80 px-4 py-3 text-sm text-zinc-100 outline-none ring-0 transition placeholder:text-zinc-600 focus:border-sky-500/50 focus:shadow-[0_0_0_3px_rgba(56,189,248,0.12)] disabled:opacity-50"
              placeholder="Message QueryMesh… (⌘↵ to send)"
            />
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  role="switch"
                  aria-checked={streamMode}
                  aria-label="Stream responses as they generate"
                  title="Shows live progress and partial text while the reply is built"
                  onClick={() => setStreamModePersist(!streamMode)}
                  className={`relative inline-flex h-7 w-12 shrink-0 items-center rounded-full border transition ${
                    streamMode
                      ? "border-sky-500/50 bg-sky-500/25"
                      : "border-zinc-600 bg-zinc-800"
                  }`}
                >
                  <span
                    className={`ml-0.5 inline-block size-5 rounded-full bg-white shadow transition ${
                      streamMode ? "translate-x-5" : "translate-x-0"
                    }`}
                  />
                </button>
                <span className="text-xs text-zinc-400">
                  Stream responses
                </span>
              </div>
              <button
                type="button"
                onClick={() => void send()}
                disabled={loading || !query.trim()}
                className="rounded-xl bg-gradient-to-r from-sky-600 to-sky-500 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-sky-900/25 transition hover:from-sky-500 hover:to-sky-400 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {loading ? "Sending…" : "Send"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
