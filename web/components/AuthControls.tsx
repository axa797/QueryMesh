"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { clearAuth, getPortalJwt } from "@/lib/auth-storage";
import {
  getPortalJwtEmail,
  getPortalJwtName,
  initialsFromEmail,
} from "@/lib/portal-jwt";

export function AuthControls() {
  const [signedIn, setSignedIn] = useState(false);
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState<string | null>(null);
  const [displayName, setDisplayName] = useState<string | null>(null);
  const router = useRouter();
  const pathname = usePathname();
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const jwt = getPortalJwt();
    setSignedIn(!!jwt);
    setEmail(getPortalJwtEmail());
    setDisplayName(getPortalJwtName());
  }, [pathname]);

  useEffect(() => {
    if (!open) return;
    function onDoc(e: MouseEvent) {
      if (!menuRef.current?.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!signedIn) {
    return (
      <nav className="flex flex-wrap gap-4 text-sm text-zinc-400">
        <Link href="/login" className="hover:text-zinc-200">
          Sign in
        </Link>
      </nav>
    );
  }

  const initials = initialsFromEmail(email);
  const titleLine =
    displayName ||
    (email ? email.split("@")[0]?.replace(/[._-]/g, " ") : null) ||
    "Account";

  function signOut() {
    clearAuth();
    setSignedIn(false);
    setOpen(false);
    router.push("/login");
    router.refresh();
  }

  return (
    <div className="relative" ref={menuRef}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="menu"
        className="flex size-9 items-center justify-center rounded-full border border-sky-500/45 bg-gradient-to-br from-sky-500/40 to-indigo-600/45 text-xs font-semibold tracking-tight text-sky-100 shadow-md shadow-sky-950/30 outline-none ring-0 transition hover:border-sky-400/55 hover:from-sky-500/50 focus-visible:ring-2 focus-visible:ring-sky-500/50"
      >
        {initials}
      </button>
      {open ? (
        <div
          className="absolute right-0 top-full z-[200] mt-2 w-[min(calc(100vw-2rem),15rem)] rounded-xl border border-zinc-700/80 bg-zinc-950 py-1 shadow-2xl shadow-black/70 ring-1 ring-black/40"
          role="menu"
        >
          <div className="border-b border-zinc-800 px-3 py-2.5">
            <p className="truncate text-sm font-medium text-zinc-100" title={titleLine}>
              {titleLine}
            </p>
            {email ? (
              <p className="truncate text-xs text-zinc-400" title={email}>
                {email}
              </p>
            ) : (
              <p className="text-xs text-zinc-500">Signed in</p>
            )}
          </div>
          <button
            type="button"
            role="menuitem"
            onClick={() => signOut()}
            className="w-full px-3 py-2.5 text-left text-sm text-zinc-200 transition hover:bg-zinc-800 hover:text-white"
          >
            Sign out
          </button>
        </div>
      ) : null}
    </div>
  );
}
