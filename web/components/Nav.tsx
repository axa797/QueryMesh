import Link from "next/link";
import { AuthControls } from "./AuthControls";
import { NavRoutes } from "./NavRoutes";
import { QueryMeshLogo } from "./QueryMeshLogo";

export function Nav() {
  return (
    <header className="sticky top-0 z-[100] isolate shrink-0 border-b border-zinc-800/80 bg-zinc-950/90 backdrop-blur">
      <div className="mx-auto flex w-full max-w-[min(100%,92.5rem)] flex-wrap items-center gap-4 px-4 py-3">
        <Link
          href="/"
          className="flex items-center gap-2.5 font-semibold tracking-tight text-zinc-100 transition hover:text-white"
        >
          <QueryMeshLogo size={30} className="shrink-0" />
          <span>QueryMesh</span>
        </Link>
        <NavRoutes />
        <div className="ml-auto">
          <AuthControls />
        </div>
      </div>
    </header>
  );
}
