"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  getStoredApiKey,
  SESSION_STORAGE_KEY,
  setStoredApiKey,
} from "@/lib/auth-storage";
import { formatQueryReply, postJson, type QueryMeshSuccess } from "@/lib/querymesh";

export default function ChatPage() {
  const [apiKey, setApiKey] = useState("");
  const [query, setQuery] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [reply, setReply] = useState<string | null>(null);
  const [latency, setLatency] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const k = getStoredApiKey();
    if (k) setApiKey(k);
    if (typeof window === "undefined") return;
    setSessionId(sessionStorage.getItem(SESSION_STORAGE_KEY));
  }, []);

  async function send() {
    setErr(null);
    setReply(null);
    setLatency(null);
    const key = apiKey.trim();
    if (!key) {
      setErr("Set an API key (paste or mint on the Keys page).");
      return;
    }
    const q = query.trim();
    if (!q) {
      setErr("Enter a message.");
      return;
    }
    setStoredApiKey(key);
    setLoading(true);
    try {
      const body: { query: string; session_id?: string } = { query: q };
      const sid = sessionId?.trim();
      if (sid) body.session_id = sid;
      const data = await postJson<QueryMeshSuccess>("/query", body, {
        Authorization: `Bearer ${key}`,
      });
      setReply(formatQueryReply(data));
      setLatency(data.latency_ms ?? null);
      if (data.session_id && typeof window !== "undefined") {
        sessionStorage.setItem(SESSION_STORAGE_KEY, data.session_id);
        setSessionId(data.session_id);
      }
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : "Query failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold text-zinc-50">Chat</h1>
      <p className="text-sm text-zinc-400">
        Uses your <strong className="text-zinc-300">API key</strong> (not the portal JWT).{" "}
        <Link href="/keys" className="text-sky-400 hover:underline">
          Mint a key
        </Link>{" "}
        if needed. Ensure FastAPI allows this origin in{" "}
        <code className="font-mono text-xs">CORS_ALLOW_ORIGINS</code> (e.g.{" "}
        <code className="font-mono text-xs">http://localhost:3000</code>).
      </p>
      <div className="space-y-3">
        <div>
          <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">
            API key
          </label>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="Bearer token for /query"
            className="w-full rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2 font-mono text-xs text-zinc-100 outline-none focus:border-zinc-600"
          />
        </div>
        {sessionId && (
          <p className="text-xs text-zinc-500">
            Session: <span className="font-mono text-zinc-400">{sessionId}</span>
          </p>
        )}
        <div>
          <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">
            Message
          </label>
          <textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            rows={4}
            className="w-full rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-zinc-600"
            placeholder="Ask something…"
          />
        </div>
        <button
          type="button"
          onClick={() => void send()}
          disabled={loading}
          className="rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50"
        >
          {loading ? "Sending…" : "Send"}
        </button>
      </div>
      {err && (
        <p className="rounded-lg border border-red-900/50 bg-red-950/40 px-3 py-2 text-sm text-red-300">
          {err}
        </p>
      )}
      {reply && (
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4">
          {latency != null && (
            <p className="mb-2 text-xs text-zinc-500">{latency} ms</p>
          )}
          <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-zinc-200">
            {reply}
          </pre>
        </div>
      )}
    </div>
  );
}
