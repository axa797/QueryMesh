import Link from "next/link";

export default function Home() {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold text-zinc-50">QueryMesh web UI</h1>
      <p className="text-sm leading-relaxed text-zinc-400">
        This Next.js app talks to your FastAPI backend. Set{" "}
        <code className="rounded bg-zinc-900 px-1.5 py-0.5 font-mono text-xs">
          NEXT_PUBLIC_QUERYMESH_URL
        </code>{" "}
        (defaults to <code className="font-mono text-xs">http://127.0.0.1:8000</code>). The API
        must have{" "}
        <code className="rounded bg-zinc-900 px-1.5 font-mono text-xs">PORTAL_JWT_SECRET</code> set
        for registration and login.
      </p>
      <ul className="list-inside list-disc space-y-2 text-sm text-zinc-400">
        <li>
          <Link href="/register" className="text-sky-400 hover:underline">
            Register
          </Link>{" "}
          — email + password → portal session (JWT in browser).
        </li>
        <li>
          <Link href="/keys" className="text-sky-400 hover:underline">
            API keys
          </Link>{" "}
          — mint / list / revoke keys for{" "}
          <code className="font-mono text-xs">POST /query</code>.
        </li>
        <li>
          <Link href="/chat" className="text-sky-400 hover:underline">
            Chat
          </Link>{" "}
          — uses a raw API key (stored locally after mint).
        </li>
      </ul>
    </div>
  );
}
