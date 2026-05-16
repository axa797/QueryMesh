"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ApiOfflineNotice } from "@/components/ApiOfflineNotice";
import {
  formatUserFacingApiError,
  probeApiHealth,
} from "@/lib/api-reachability";
import { clearSession, getStoredApiKey, setPortalJwt, setStoredApiKey } from "@/lib/auth-storage";
import { postJson, type ApiKeyCreateResponse } from "@/lib/querymesh";

export default function OAuthCallbackPage() {
  const router = useRouter();
  const [err, setErr] = useState<string | null>(null);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    const fragment = typeof window !== "undefined" ? window.location.hash.slice(1) : "";
    const params = new URLSearchParams(fragment);
    const oauthErr = params.get("error");
    const desc = params.get("error_description");
    if (oauthErr) {
      setErr(formatUserFacingApiError(desc || oauthErr || "Sign-in failed."));
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
      return;
    }
    const tok = params.get("access_token");
    if (!tok) {
      setErr("Missing access token in redirect. Try signing in again.");
      return;
    }
    setPortalJwt(tok);

    async function mintAndGo() {
      const ready = await probeApiHealth();
      if (!ready.ok) {
        setOffline(true);
        setErr(null);
        return;
      }
      try {
        if (!getStoredApiKey()) {
          const minted = await postJson<ApiKeyCreateResponse>(
            "/account/api-keys",
            {},
            { Authorization: `Bearer ${tok}` },
          );
          setStoredApiKey(minted.api_key);
        }
        clearSession();
        window.history.replaceState(null, "", window.location.pathname + window.location.search);
        router.replace("/chat");
      } catch (ex) {
        setErr(formatUserFacingApiError(ex));
      }
    }

    void mintAndGo();
  }, [router]);

  return (
    <div className="mx-auto max-w-md space-y-6 py-8">
      {!err && !offline ? (
        <p className="text-sm text-zinc-400">Finishing sign-in…</p>
      ) : offline ? (
        <>
          <ApiOfflineNotice variant="banner" className="w-full" />
          <Link href="/login" className="text-sm text-sky-400 hover:underline">
            Back to sign in
          </Link>
        </>
      ) : (
        <>
          <p className="rounded-lg border border-red-900/50 bg-red-950/40 px-3 py-2 text-sm text-red-300">
            {err}
          </p>
          <Link href="/login" className="text-sm text-sky-400 hover:underline">
            Back to sign in
          </Link>
        </>
      )}
    </div>
  );
}
