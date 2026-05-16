"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  API_KEY_STORAGE,
  getPortalJwt,
  setStoredApiKey,
} from "@/lib/auth-storage";
import { ApiOfflineNotice } from "@/components/ApiOfflineNotice";
import {
  formatUserFacingApiError,
  useApiReachability,
} from "@/lib/api-reachability";
import {
  getJson,
  postJson,
  type ApiKeyCreateResponse,
  type ApiKeyListItem,
} from "@/lib/querymesh";

export default function KeysPage() {
  const { apiOffline } = useApiReachability();
  const [rows, setRows] = useState<ApiKeyListItem[] | null>(null);
  const [minted, setMinted] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  const portal = typeof window !== "undefined" ? getPortalJwt() : null;

  useEffect(() => {
    if (!getPortalJwt()) router.replace("/login");
  }, [router]);

  const load = useCallback(async () => {
    const t = getPortalJwt();
    if (!t) {
      setRows([]);
      return;
    }
    if (apiOffline) {
      setRows([]);
      setErr(null);
      return;
    }
    setErr(null);
    try {
      const list = await getJson<ApiKeyListItem[]>("/account/api-keys", {
        Authorization: `Bearer ${t}`,
      });
      setRows(list);
    } catch (ex) {
      setErr(formatUserFacingApiError(ex));
      setRows([]);
    }
  }, [apiOffline]);

  useEffect(() => {
    void load();
  }, [load]);

  async function mint() {
    const t = getPortalJwt();
    if (!t || apiOffline) return;
    setErr(null);
    setLoading(true);
    setMinted(null);
    try {
      const res = await postJson<ApiKeyCreateResponse>(
        "/account/api-keys",
        {},
        { Authorization: `Bearer ${t}` },
      );
      setMinted(res.api_key);
      setStoredApiKey(res.api_key);
      await load();
    } catch (ex) {
      setErr(formatUserFacingApiError(ex));
    } finally {
      setLoading(false);
    }
  }

  async function revoke(id: string) {
    const t = getPortalJwt();
    if (!t || apiOffline) return;
    setErr(null);
    try {
      await postJson<unknown>(
        `/account/api-keys/${id}/revoke`,
        {},
        { Authorization: `Bearer ${t}` },
      );
      await load();
    } catch (ex) {
      setErr(formatUserFacingApiError(ex));
    }
  }

  if (!portal) {
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-semibold text-zinc-50">API keys</h1>
        <p className="text-sm text-zinc-400">
          Sign in first to manage keys.{" "}
          <Link href="/login" className="text-sky-400 hover:underline">
            Login
          </Link>
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {apiOffline && <ApiOfflineNotice variant="banner" />}
      <h1 className="text-xl font-semibold text-zinc-50">API keys</h1>
      <p className="text-sm text-zinc-400">
        Mint a key and use it as <code className="font-mono text-xs">Authorization: Bearer</code>{" "}
        on <code className="font-mono text-xs">POST /query</code>. The last minted key is saved in{" "}
        <code className="font-mono text-xs">localStorage.{API_KEY_STORAGE}</code> for the Chat page.
      </p>
      <button
        type="button"
        onClick={() => void mint()}
        disabled={loading || apiOffline}
        className="rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50"
      >
        {loading ? "Minting…" : "Mint new key"}
      </button>
      {minted && (
        <div className="rounded-lg border border-amber-900/50 bg-amber-950/30 p-3 text-sm">
          <p className="mb-1 font-medium text-amber-200">New key (copy now; stored for Chat)</p>
          <pre className="break-all font-mono text-xs text-amber-100/90">{minted}</pre>
        </div>
      )}
      {err && (
        <p className="rounded-lg border border-red-900/50 bg-red-950/40 px-3 py-2 text-sm text-red-300">
          {err}
        </p>
      )}
      <div className="space-y-2">
        <h2 className="text-sm font-medium text-zinc-400">Your keys</h2>
        {rows === null ? (
          <p className="text-sm text-zinc-500">Loading…</p>
        ) : rows.length === 0 ? (
          <p className="text-sm text-zinc-500">No keys yet.</p>
        ) : (
          <ul className="space-y-2">
            {rows.map((r) => (
              <li
                key={r.key_id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-zinc-800 bg-zinc-900/50 px-3 py-2 text-sm"
              >
                <div>
                  <span className="font-mono text-xs text-zinc-300">{r.key_id}</span>
                  <span className="ml-2 text-zinc-500">
                    {r.revoked_at ? (
                      <span className="text-amber-600">revoked</span>
                    ) : (
                      <span className="text-emerald-600">active</span>
                    )}
                  </span>
                </div>
                {!r.revoked_at && (
                  <button
                    type="button"
                    onClick={() => void revoke(r.key_id)}
                    className="text-xs text-red-400 hover:underline"
                  >
                    Revoke
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
      <p className="text-sm">
        <Link href="/chat" className="text-sky-400 hover:underline">
          Open Chat →
        </Link>
      </p>
    </div>
  );
}
