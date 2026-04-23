"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { clearAuth, getPortalJwt } from "@/lib/auth-storage";

export function AuthControls() {
  const [signedIn, setSignedIn] = useState(false);
  const router = useRouter();

  useEffect(() => {
    setSignedIn(!!getPortalJwt());
  }, []);

  if (!signedIn) {
    return <span className="text-xs text-zinc-500">Portal: not signed in</span>;
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
