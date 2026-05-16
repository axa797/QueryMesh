"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  clearSession,
  getPortalJwt,
  getStoredApiKey,
  SESSION_STORAGE_KEY,
  setStoredApiKey,
} from "@/lib/auth-storage";
import {
  ApiError,
  formatQueryReply,
  fetchQueryHistory,
  postJson,
  postQueryStream,
  type ApiKeyCreateResponse,
  type HistoryMessageRow,
  type QueryMeshSuccess,
  type SourceCard,
} from "@/lib/querymesh";

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

export default function ChatPage() {
  const [apiKey, setApiKey] = useState("");
  const [query, setQuery] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [streamMode, setStreamMode] = useState(false);
  const [streamingPhases, setStreamingPhases] = useState<string[]>([]);
  const [assistantDraft, setAssistantDraft] = useState("");

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const transcriptEndRef = useRef<HTMLDivElement>(null);
  const router = useRouter();

  useEffect(() => {
    const jwt = getPortalJwt();
    if (!jwt) {
      router.replace("/register");
      return;
    }
    const k = getStoredApiKey();
    if (k) setApiKey(k);
    if (typeof window !== "undefined")
      setSessionId(sessionStorage.getItem(SESSION_STORAGE_KEY));
  }, [router]);

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, loading, streamingPhases, assistantDraft]);

  async function hydrateFromServer(sid: string, key: string) {
    try {
      const rows = await fetchQueryHistory(sid, {
        Authorization: `Bearer ${key}`,
      });
      setTurns(historyToTurns(rows));
    } catch {
      setTurns([]);
    }
  }

  useEffect(() => {
    const key = apiKey.trim();
    const sid = sessionId?.trim();
    if (!key || !sid) return;
    void hydrateFromServer(sid, key);
  }, [apiKey, sessionId]);

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
    textareaRef.current?.focus();
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
    <div className="flex max-h-[min(92vh,calc(100vh-120px))] flex-col gap-4">
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden rounded-xl border border-zinc-800 bg-zinc-950/50">
        <div className="flex items-center justify-between border-b border-zinc-800 px-3 py-2">
          <span className="text-xs uppercase tracking-wide text-zinc-500">
            Conversation
          </span>
          <button
            type="button"
            onClick={newConversation}
            className="rounded-md border border-zinc-700 px-3 py-1 text-xs text-zinc-300 hover:border-zinc-500 hover:text-zinc-100"
          >
            New conversation
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-6 space-y-4">
          {turns.length === 0 && !loading && (
            <p className="py-8 text-center text-sm text-zinc-500">
              Messages appear here — ask a question below.
            </p>
          )}
          {turns.map((t) =>
            t.role === "user" ? (
              <div
                key={t.id}
                className="rounded-lg border border-sky-900/40 bg-sky-950/30 px-3 py-2"
              >
                <div className="text-[10px] font-semibold uppercase text-sky-500">
                  You
                </div>
                <pre className="mt-1 whitespace-pre-wrap font-sans text-sm text-zinc-100">
                  {t.content}
                </pre>
              </div>
            ) : (
              <div
                key={t.id}
                className="rounded-lg border border-zinc-800 bg-zinc-900/60 px-3 py-2"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[10px] font-semibold uppercase text-zinc-500">
                    Assistant
                  </span>
                  {t.latencyMs != null && (
                    <span className="text-[10px] text-zinc-600">
                      {t.latencyMs} ms
                    </span>
                  )}
                </div>
                {t.phases && t.phases.length > 0 && (
                  <p className="mt-1 text-[11px] font-mono text-zinc-600">
                    Phases: {t.phases.join(" → ")}
                  </p>
                )}
                <pre className="mt-1 whitespace-pre-wrap font-sans text-sm leading-relaxed text-zinc-200">
                  {t.content}
                </pre>
                {t.sourceCards && t.sourceCards.length > 0 && (
                  <details className="mt-3 border-t border-zinc-800 pt-3 [&_summary::-webkit-details-marker]:hidden">
                    <summary className="cursor-pointer select-none text-[10px] font-semibold uppercase tracking-wide text-zinc-500 hover:text-zinc-400">
                      Sources ({t.sourceCards.length}) — expand
                    </summary>
                    <ul className="mt-3 space-y-2">
                      {t.sourceCards.map((s, idx) => (
                        <li
                          key={`${s.point_id || "np"}-${idx}-${t.id}`}
                          className="rounded-md border border-zinc-800/80 bg-zinc-950/50 px-2 py-2"
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
            ),
          )}
          {loading && streamMode && assistantDraft.trim() !== "" && (
            <div className="rounded-lg border border-amber-900/35 bg-zinc-900/70 px-3 py-2">
              <div className="text-[10px] font-semibold uppercase text-amber-600">
                Assistant (streaming…)
              </div>
              <pre className="mt-1 whitespace-pre-wrap font-sans text-sm leading-relaxed text-zinc-100">
                {assistantDraft}
              </pre>
            </div>
          )}
          {loading && streamingPhases.length > 0 && (
            <p className="text-xs font-mono text-zinc-500">
              Phases: {streamingPhases.join(" → ")}
            </p>
          )}
          {loading && streamingPhases.length === 0 && (
            <p className="text-xs text-zinc-500 italic">Thinking…</p>
          )}
          <div ref={transcriptEndRef} />
        </div>
      </div>

      <textarea
        ref={textareaRef}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={onKeyDown}
        rows={3}
        disabled={loading}
        className="w-full rounded-lg border border-zinc-800 bg-zinc-900 px-4 py-3 text-sm text-zinc-100 outline-none focus:border-zinc-600 disabled:opacity-50 resize-none"
        placeholder="Ask something about GCP… (⌘↵ to send)"
      />
      <div className="flex flex-wrap items-center gap-4">
        <label className="flex cursor-pointer items-center gap-2 text-xs text-zinc-400 select-none">
          <input
            type="checkbox"
            checked={streamMode}
            onChange={(e) => setStreamMode(e.target.checked)}
            className="rounded border-zinc-600 bg-zinc-900"
          />
          Stream answer (SSE: phases + answer preview)
        </label>
      </div>
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => void send()}
          disabled={loading || !query.trim()}
          className="rounded-lg bg-sky-600 px-5 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-40 transition-colors"
        >
          {loading ? "Sending…" : "Send"}
        </button>
      </div>

      {err && (
        <p className="rounded-lg border border-red-900/50 bg-red-950/40 px-4 py-3 text-sm text-red-300">
          {err}
        </p>
      )}
    </div>
  );
}
