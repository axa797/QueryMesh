"use client";

import { useCallback, useState } from "react";
import { ApiOfflineNotice } from "@/components/ApiOfflineNotice";
import { probeApiHealth, useApiReachability } from "@/lib/api-reachability";
import { getApiBase } from "@/lib/querymesh";
import { QueryMeshLogo } from "@/components/QueryMeshLogo";
import { SurfaceCard } from "@/components/SurfaceCard";

export default function LoginPage() {
  const { state: preflight, apiOffline } = useApiReachability();
  const [checkingOAuth, setCheckingOAuth] = useState(false);
  const [oauthBlocked, setOauthBlocked] = useState(false);

  const startGoogleOAuth = useCallback(async () => {
    setOauthBlocked(false);
    setCheckingOAuth(true);
    try {
      const r = await probeApiHealth();
      if (r.ok) {
        window.location.href = `${getApiBase()}/account/oauth/google/start`;
        return;
      }
      setOauthBlocked(true);
    } finally {
      setCheckingOAuth(false);
    }
  }, []);

  return (
    <div className="flex min-h-[min(64vh,calc(100vh-10rem))] flex-col items-center justify-center px-2 sm:px-0">
      <SurfaceCard className="w-full max-w-sm">
        <div className="flex flex-col items-center gap-6 text-center">
          <QueryMeshLogo
            size={52}
            className="drop-shadow-[0_0_24px_rgba(56,189,248,0.2)]"
          />
          <div>
            <h1 className="text-lg font-semibold text-zinc-100">Sign in</h1>
            <p className="mt-1 text-xs text-zinc-500">
              Use your Google account to continue.
            </p>
          </div>

          {apiOffline && (
            <ApiOfflineNotice variant="banner" className="w-full" />
          )}

          <div className="flex w-full flex-col gap-3">
            <button
              type="button"
              onClick={() => void startGoogleOAuth()}
              disabled={
                checkingOAuth || preflight === "checking" || apiOffline
              }
              className={`flex w-full items-center justify-center gap-3 rounded-xl border py-3 pl-3 pr-4 text-sm font-medium shadow-md transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-500 disabled:cursor-not-allowed ${
                apiOffline || checkingOAuth || preflight === "checking"
                  ? "border-zinc-600 bg-zinc-800/70 text-zinc-400 shadow-black/10 grayscale hover:bg-zinc-800/70"
                  : "border-zinc-600 bg-white text-zinc-800 shadow-black/20 hover:bg-zinc-50"
              }`}
            >
              <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden>
                <path
                  fill="#EA4335"
                  d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
                />
                <path
                  fill="#4285F4"
                  d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6C44.25 37.97 48 31.9 48 24c0-1.64-.14-3.29-.41-4.54z"
                />
                <path
                  fill="#FBBC05"
                  d="M6.26 14.88a23.82 23.82 0 0 0-.9 6.12c0 2.13.36 4.19.98 6.12l7.99-6.2c-.4-1.22-.63-2.53-.63-3.93s.24-2.71.64-3.92z"
                />
                <path
                  fill="#34A853"
                  d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
                />
                <path fill="none" d="M0 0h48v48H0z" />
              </svg>
              {preflight === "checking" || checkingOAuth
                ? "Checking…"
                : "Continue with Google"}
            </button>

            {oauthBlocked && !apiOffline && (
              <ApiOfflineNotice variant="inline" className="w-full" />
            )}
          </div>
        </div>
      </SurfaceCard>
    </div>
  );
}