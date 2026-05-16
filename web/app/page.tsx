"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getPortalJwt } from "@/lib/auth-storage";
import { QueryMeshLogo } from "@/components/QueryMeshLogo";
import { SurfaceCard } from "@/components/SurfaceCard";

export default function Home() {
  const [signedIn, setSignedIn] = useState(false);

  useEffect(() => {
    setSignedIn(!!getPortalJwt());
  }, []);

  return (
    <div className="flex min-h-[min(72vh,calc(100vh-10rem))] flex-col items-center justify-center px-2 sm:px-0">
      <SurfaceCard className="w-full max-w-xl">
        <div className="flex flex-col items-center space-y-5 text-center">
          <QueryMeshLogo size={60} className="drop-shadow-[0_0_28px_rgba(56,189,248,0.22)]" />
          <div className="inline-flex items-center rounded-full border border-sky-500/25 bg-sky-500/10 px-3 py-1 text-[11px] font-medium uppercase tracking-wider text-sky-300/95">
            Cloud Next 2026 corpus
          </div>
          <h1 className="bg-gradient-to-r from-sky-100 via-sky-200 to-indigo-200 bg-clip-text text-3xl font-bold tracking-tight text-transparent sm:text-4xl">
            QueryMesh
          </h1>
          <p className="mx-auto max-w-lg text-sm leading-relaxed text-zinc-400">
            A knowledge-base search experience: semantic retrieval over indexed docs,
            synthesized answers with citations, and an optional sandboxed code tool
            for analysis — no live open-web search; answers stay grounded in what’s
            loaded.
          </p>
          <p className="mx-auto max-w-lg text-xs leading-relaxed text-zinc-500">
            The corpus in this deployment is oriented around Google Cloud Next 2026
            material.
          </p>
          <div className="pt-2">
            {signedIn ? (
              <Link
                href="/chat"
                className="inline-flex rounded-xl bg-gradient-to-r from-sky-600 to-indigo-600 px-8 py-2.5 text-sm font-semibold text-white shadow-lg shadow-sky-950/40 transition hover:from-sky-500 hover:to-indigo-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-400"
              >
                Open Chat
              </Link>
            ) : (
              <Link
                href="/login"
                className="inline-flex rounded-xl bg-gradient-to-r from-sky-600 to-indigo-600 px-8 py-2.5 text-sm font-semibold text-white shadow-lg shadow-sky-950/40 transition hover:from-sky-500 hover:to-indigo-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-400"
              >
                Sign in with Google
              </Link>
            )}
          </div>
        </div>
      </SurfaceCard>
    </div>
  );
}
