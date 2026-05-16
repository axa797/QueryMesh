"use client";

import Link from "next/link";
import { getApiBase } from "@/lib/querymesh";

function startGoogleOAuth() {
  window.location.href = `${getApiBase()}/account/oauth/google/start`;
}

export default function LoginPage() {
  return (
    <div className="mx-auto max-w-md space-y-6">
      <h1 className="text-xl font-semibold text-zinc-50">Sign in</h1>
      <p className="text-sm text-zinc-500">
        Uses Google OAuth. You leave this app briefly so the API can set a secure
        cookie, then return here signed in.
      </p>
      <button
        type="button"
        className="w-full rounded-lg border border-zinc-700 bg-zinc-950 py-2.5 text-sm font-medium text-zinc-100 hover:border-zinc-500 hover:bg-zinc-900"
        onClick={startGoogleOAuth}
      >
        Continue with Google
      </button>
      <p className="text-center text-sm text-zinc-500">
        If you landed from an old bookmark, sign-in replaces the separate register flow.
      </p>
      <p className="text-center text-sm">
        <Link href="/" className="text-sky-400 hover:underline">
          ← Home
        </Link>
      </p>
    </div>
  );
}
