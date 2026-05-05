"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  getPortalJwt,
  getStoredApiKey,
  SESSION_STORAGE_KEY,
  setStoredApiKey,
} from "@/lib/auth-storage";
import {
  ApiError,
  formatQueryReply,
  postJson,
  postQueryStream,
  type ApiKeyCreateResponse,
  type QueryMeshSuccess,
  type SourceCard,
} from "@/lib/querymesh";

export default function ChatPage() {
  const [apiKey, setApiKey] = useState("");
  const [query, setQuery] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [reply, setReply] = useState<string | null>(null);
  const [latency, setLatency] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [pipelinePhases, setPipelinePhases] = useState<string[]>([]);
  const [sourceCards, setSourceCards] = useState<SourceCard[]>([]);
  const [streamMode, setStreamMode] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
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

  async function remintKey(): Promise<string | null> {
    const jwt = getPortalJwt();
    if (!jwt) return null;
    try {
      const res = await postJson<ApiKeyCreateResponse>("/account/api-keys", {}, {
        Authorization: `Bearer ${jwt}`,
      });
      setStoredApiKey(res.api_key);
      setApiKey(res.api_key);
      return res.api_key;
    } catch {
      return null;
    }
  }

  async function send() {
    setErr(null);
    setReply(null);
    setLatency(null);
    setPipelinePhases([]);
    setSourceCards([]);
    const q = query.trim();
    if (!q) return;

    let key = apiKey.trim();
    if (!key) {
      router.push("/login");
      return;
    }

    setLoading(true);
    try {
      const body: { query: string; session_id?: string } = { query: q };
      const sid = sessionId?.trim();
      if (sid) body.session_id = sid;

      const authHeader = (k: string) => ({ Authorization: `Bearer ${k}` });

      let data: QueryMeshSuccess | null = null;

      async function consumeStream(hdr: Record<string, string>): Promise<void> {
        await postQueryStream(body, hdr, (ev) => {
          if (ev.type === "phase") {
            setPipelinePhases((prev) =>
              prev.includes(ev.node) ? prev : [...prev, ev.node],
            );
          } else if (ev.type === "done") {
            data = ev.payload;
          } else if (ev.type === "error") {
            throw new Error(ev.message);
          }
        });
      }

      if (streamMode) {
        try {
          await consumeStream(authHeader(key));
        } catch (ex) {
          if (ex instanceof ApiError && ex.status === 401) {
            const fresh = await remintKey();
            if (!fresh) {
              router.push("/login");
              return;
            }
            key = fresh;
            await consumeStream(authHeader(key));
          } else {
            throw ex;
          }
        }
      } else {
        try {
          data = await postJson<QueryMeshSuccess>("/query", body, authHeader(key));
        } catch (ex) {
          if (ex instanceof ApiError && ex.status === 401) {
            const fresh = await remintKey();
            if (!fresh) {
              router.push("/login");
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

      if (!data) {
        setErr(streamMode ? "Stream ended without a result" : "No response");
        return;
      }

      setReply(formatQueryReply(data));
      setLatency(data.latency_ms ?? null);
      const cards = data.response?.source_cards;
      if (Array.isArray(cards))
        setSourceCards(cards as SourceCard[]);

      if (data.session_id && typeof window !== "undefined") {
        sessionStorage.setItem(SESSION_STORAGE_KEY, data.session_id);
        setSessionId(data.session_id);
      }
      setQuery("");
      textareaRef.current?.focus();
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : "Query failed");
    } finally {
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
    <div className="space-y-4">
      <textarea
        ref={textareaRef}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={onKeyDown}
        rows={4}
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
          Stream phases (SSE)
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
        {latency != null && (
          <span className="text-xs text-zinc-500">{latency} ms</span>
        )}
      </div>

      {err && (
        <p className="rounded-lg border border-red-900/50 bg-red-950/40 px-4 py-3 text-sm text-red-300">
          {err}
        </p>
      )}

      {pipelinePhases.length > 0 && (
        <p className="text-xs text-zinc-500 font-mono">
          Phases: {pipelinePhases.join(" → ")}
        </p>
      )}

      {sourceCards.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-medium uppercase tracking-wide text-zinc-500">
            Sources
          </p>
          <ul className="space-y-2">
            {sourceCards.map((s, idx) => (
              <li
                key={`${s.point_id || "np"}-${idx}`}
                className="rounded-md border border-zinc-800 bg-zinc-900/60 px-3 py-2"
              >
                <div className="text-xs font-medium text-sky-400">
                  {(s.source_doc || "unknown").slice(0, 80)}
                  {s.section ? (
                    <span className="text-zinc-500"> · {s.section}</span>
                  ) : null}
                </div>
                {s.excerpt ? (
                  <p className="mt-1 text-xs leading-relaxed text-zinc-400">
                    {s.excerpt}
                    {s.excerpt.length >= 400 ? "…" : ""}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      )}

      {reply && (
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 px-4 py-4">
          <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-zinc-200">
            {reply}
          </pre>
        </div>
      )}
    </div>
  );
}
