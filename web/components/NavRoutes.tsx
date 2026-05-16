"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { getPortalJwt } from "@/lib/auth-storage";

/** Chat always; Eval only when signed in (portal JWT). */
export function NavRoutes() {
  const [signedIn, setSignedIn] = useState(false);
  const pathname = usePathname();

  useEffect(() => {
    setSignedIn(!!getPortalJwt());
  }, [pathname]);

  return (
    <nav className="flex flex-wrap gap-4 text-sm text-zinc-400">
      <Link href="/chat" className="transition hover:text-zinc-200">
        Chat
      </Link>
      {signedIn ? (
        <Link href="/eval" className="transition hover:text-zinc-200">
          Eval
        </Link>
      ) : null}
    </nav>
  );
}
