"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { clearAuth, getPortalJwt } from "@/lib/auth-storage";

export function AuthControls() {
  const [signedIn, setSignedIn] = useState(false);
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    setSignedIn(!!getPortalJwt());
  }, [pathname]);

  if (!signedIn) {
    return (
      <nav className="flex flex-wrap gap-4 text-sm text-zinc-400">
        <Link href="/login" className="hover:text-zinc-200">
          Sign in
        </Link>
      </nav>
    );
  }

  return (
    <button
      type="button"
      className="text-xs text-sky-400 hover:underline"
      onClick={() => {
        clearAuth();
        setSignedIn(false);
        router.push("/login");
        router.refresh();
      }}
    >
      Sign out
    </button>
  );
}
