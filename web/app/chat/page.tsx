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
  type ApiKeyCreateResponse,
  type QueryMeshSuccess,
} from "@/lib/querymesh";

export default function ChatPage() {
  const [apiKey, setApiKey] = useState("");
  const [query, setQuery] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [reply, setReply] = useState<string | null>(null);
  const [latency, setLatency] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
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

      let data: QueryMeshSuccess;
      try {
        data = await postJson<QueryMeshSuccess>("/query", body, {
          Authorization: `Bearer ${key}`,
        });
      } catch (ex) {
        if (ex instanceof ApiError && ex.status === 401) {
          const fresh = await remintKey();
          if (!fresh) {
            router.push("/login");
            return;
          }
          key = fresh;
          data = await postJson<QueryMeshSuccess>("/query", body, {
            Authorization: `Bearer ${key}`,
          });
        } else {
          throw ex;
        }
      }

      setReply(formatQueryReply(data));
      setLatency(data.latency_ms ?? null);
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
