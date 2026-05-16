"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  getPortalJwt,
  getStoredApiKey,
} from "@/lib/auth-storage";
import {
  ApiError,
  fetchEvalReportsPage,
  langfuseTraceUrl,
  type EvalReportSummaryDTO,
} from "@/lib/querymesh";

export default function EvalListPage() {
  const router = useRouter();
  const [apiKey, setApiKey] = useState("");
  const [items, setItems] = useState<EvalReportSummaryDTO[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const jwt = getPortalJwt();
    if (!jwt) {
      router.replace("/register");
      return;
    }
    const k = getStoredApiKey();
    if (k) setApiKey(k);
  }, [router]);

  useEffect(() => {
    const key = apiKey.trim();
    if (!key) {
      setLoading(false);
      return;
    }
    setLoading(true);
    void (async () => {
      try {
        const data = await fetchEvalReportsPage(
          page,
          pageSize,
          { Authorization: `Bearer ${key}` },
        );
        setItems(data.items);
        setTotal(data.total);
        setErr(null);
      } catch (ex) {
        setErr(ex instanceof ApiError ? ex.message : "Failed to load reports");
      } finally {
        setLoading(false);
      }
    })();
  }, [apiKey, page, pageSize]);

  const canNext = total > 0 && page * pageSize < total;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-zinc-100">
          Evaluation reports
        </h1>
        <p className="mt-2 text-sm text-zinc-500">
          Persisted RAGAS runs from{" "}
          <code className="rounded bg-zinc-900 px-1 py-0.5 text-xs text-zinc-300">
            evals/ragas_eval
          </code>{" "}
          with{" "}
          <code className="rounded bg-zinc-900 px-1 py-0.5 text-xs text-zinc-300">
            --persist
          </code>{" "}
          or{" "}
          <code className="rounded bg-zinc-900 px-1 py-0.5 text-xs text-zinc-300">
            EVAL_PERSIST_DATABASE
          </code>
          .
        </p>
        <p className="mt-2 text-xs text-zinc-500">
          Trace links use the persisted Langfuse SDK URL when available (
          “Open Langfuse trace”).
          Fallback (bare ids):
          {" "}
          <code className="rounded bg-zinc-900 px-1 text-xs text-zinc-400">
            NEXT_PUBLIC_LANGFUSE_PUBLIC_URL
          </code>{" "}
          +{" "}
          <code className="rounded bg-zinc-900 px-1 text-xs text-zinc-400">
            NEXT_PUBLIC_LANGFUSE_PROJECT_ID
          </code>
          ,
          Host must match the project region (EU{" "}
          <code className="text-zinc-500">https://cloud.langfuse.com</code>
          ,
          {" "}
          US{" "}
          <code className="text-zinc-500">https://us.cloud.langfuse.com</code>
          ).
        </p>
      </div>

      {!apiKey.trim() && (
        <p className="rounded-lg border border-amber-900/60 bg-amber-950/30 px-4 py-3 text-sm text-amber-200">
          Mint an API key on the account portal and store it locally to load reports.
        </p>
      )}

      {err && (
        <p className="rounded-lg border border-red-900/60 bg-red-950/40 px-4 py-2 text-sm text-red-200">
          {err}
        </p>
      )}

      {loading && apiKey.trim() && (
        <p className="text-sm text-zinc-400">Loading…</p>
      )}

      {!loading && apiKey.trim() && (
        <>
          <p className="text-xs text-zinc-500">
            {total} report{total === 1 ? "" : "s"} · page {page} of{" "}
            {Math.max(1, Math.ceil(total / pageSize))}
          </p>
          <div className="overflow-x-auto rounded-lg border border-zinc-800">
            <table className="min-w-full text-left text-sm">
              <thead className="border-b border-zinc-800 bg-zinc-900/60 text-xs uppercase tracking-wide text-zinc-400">
                <tr>
                  <th className="px-4 py-2">When</th>
                  <th className="px-4 py-2">Mode</th>
                  <th className="px-4 py-2">N</th>
                  <th className="px-4 py-2">Faithfulness</th>
                  <th className="px-4 py-2">Langfuse</th>
                  <th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800">
                {items.length === 0 && (
                  <tr>
                    <td
                      colSpan={6}
                      className="px-4 py-8 text-center text-zinc-500"
                    >
                      No persisted reports yet. Run RAGAS with DB persist enabled after
                      applying migration{" "}
                      <code className="rounded bg-zinc-900 px-1 text-xs text-zinc-400">
                        005_eval_reports_table
                      </code>
                      .
                    </td>
                  </tr>
                )}
                {items.map((r) => (
                  <tr key={r.id} className="hover:bg-zinc-900/40">
                    <td className="whitespace-nowrap px-4 py-2 text-zinc-300">
                      {new Date(r.created_at).toLocaleString()}
                    </td>
                    <td className="max-w-[12rem] truncate px-4 py-2 text-zinc-400">
                      {r.mode}
                    </td>
                    <td className="px-4 py-2 text-zinc-300">{r.n_samples}</td>
                    <td className="px-4 py-2 text-zinc-300">
                      {typeof r.aggregate_metrics?.faithfulness === "number"
                        ? r.aggregate_metrics.faithfulness.toFixed(3)
                        : "—"}
                    </td>
                    <td className="px-4 py-2">
                      {r.langfuse_trace_id &&
                      langfuseTraceUrl(r.langfuse_trace_id) ? (
                        <a
                          href={langfuseTraceUrl(r.langfuse_trace_id)!}
                          className="text-sky-400 hover:text-sky-300"
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          Trace
                        </a>
                      ) : (
                        <span className="text-zinc-600">—</span>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-4 py-2">
                      <Link
                        href={`/eval/${r.id}`}
                        className="text-sky-400 hover:text-sky-300"
                      >
                        View
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center gap-4 text-xs text-zinc-500">
            <button
              type="button"
              disabled={page <= 1}
              className="rounded border border-zinc-700 px-3 py-1 text-zinc-300 disabled:opacity-40"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              Previous
            </button>
            <span>Page {page}</span>
            <button
              type="button"
              disabled={!canNext}
              className="rounded border border-zinc-700 px-3 py-1 text-zinc-300 disabled:opacity-40"
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </button>
          </div>
        </>
      )}
    </div>
  );
}
