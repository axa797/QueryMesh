"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { getPortalJwt } from "@/lib/auth-storage";

export default function Home() {
  const [signedIn, setSignedIn] = useState(false);
  const router = useRouter();

  useEffect(() => {
    setSignedIn(!!getPortalJwt());
  }, []);

  return (
    <div className="flex min-h-[70vh] flex-col items-center justify-center text-center">
      <div className="space-y-4">
        <h1 className="text-4xl font-bold tracking-tight text-zinc-50">
          QueryMesh
        </h1>
        <p className="text-zinc-400 max-w-sm mx-auto">
          GCP knowledge assistant — ask anything about Google Cloud.
        </p>
      </div>

      <div className="mt-10 flex gap-3">
        {signedIn ? (
          <Link
            href="/chat"
            className="rounded-lg bg-sky-600 px-6 py-2.5 text-sm font-medium text-white hover:bg-sky-500 transition-colors"
          >
            Open Chat
          </Link>
        ) : (
          <>
            <Link
              href="/register"
              className="rounded-lg bg-sky-600 px-6 py-2.5 text-sm font-medium text-white hover:bg-sky-500 transition-colors"
            >
              Get started
            </Link>
            <Link
              href="/login"
              className="rounded-lg border border-zinc-700 px-6 py-2.5 text-sm font-medium text-zinc-300 hover:border-zinc-500 hover:text-zinc-100 transition-colors"
            >
              Sign in
            </Link>
          </>
        )}
      </div>
    </div>
  );
}
