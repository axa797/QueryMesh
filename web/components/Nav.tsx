import Link from "next/link";
import { AuthControls } from "./AuthControls";

export function Nav() {
  return (
    <header className="border-b border-zinc-800 bg-zinc-950/90 backdrop-blur">
      <div className="mx-auto flex max-w-3xl flex-wrap items-center gap-4 px-4 py-3">
        <Link href="/" className="font-semibold tracking-tight text-zinc-100">
          QueryMesh
        </Link>
        <nav className="flex flex-wrap gap-4 text-sm text-zinc-400">
          <Link href="/chat" className="hover:text-zinc-200">
            Chat
          </Link>
        </nav>
        <div className="ml-auto">
          <AuthControls />
        </div>
      </div>
    </header>
  );
}
