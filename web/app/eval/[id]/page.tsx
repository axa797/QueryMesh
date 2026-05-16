"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { getPortalJwt, getStoredApiKey } from "@/lib/auth-storage";
import {
  ApiError,
  fetchEvalReportDetail,
  langfuseTraceUrl,
  type EvalReportDetailDTO,
} from "@/lib/querymesh";

/**
 * Collapse long prose / JSON cells in the eval table until the user expands them.
 */
function ExpandableTextCell({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const lineCount = text.split("\n").length;
  const longText = text.length > 240 || lineCount > 4;

  if (!longText) {
    return (
      <span className="whitespace-pre-wrap break-words text-zinc-300">
        {text}
      </span>
    );
  }

  return (
    <div className="max-w-[min(36rem,72vw)]">
      <div
        className={
          open
            ? "max-h-none whitespace-pre-wrap break-words text-zinc-300"
            : "line-clamp-4 max-h-[5.75rem] overflow-hidden whitespace-pre-wrap break-words text-zinc-300"
        }
      >
        {text}
      </div>
      <button
        type="button"
        aria-expanded={open}
        className="mt-1.5 cursor-pointer border-0 bg-transparent p-0 text-[11px] font-medium text-sky-400 hover:text-sky-300"
        onClick={() => setOpen((v) => !v)}
      >
        {open ? "Collapse" : "Read more"}
      </button>
    </div>
  );
}

function cellDisplayString(raw: unknown): string {
  if (typeof raw === "number") {
    return Number.isFinite(raw) ? raw.toFixed(4) : "—";
  }
  if (typeof raw === "string" || typeof raw === "boolean") {
    return String(raw);
  }
  if (raw == null) return "—";
  return JSON.stringify(raw);
}

export default function EvalDetailPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const id = decodeURIComponent(
    typeof params?.id === "string" ? params.id : "",
  );

  const [apiKey, setApiKey] = useState("");
  const [detail, setDetail] = useState<EvalReportDetailDTO | null>(null);
  const [err, setErr] = useState<string | null>(null);

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
    if (!key || !id) return;

    void (async () => {
      try {
        const d = await fetchEvalReportDetail(id, {
          Authorization: `Bearer ${key}`,
        });
        setDetail(d);
        setErr(null);
      } catch (ex) {
        setDetail(null);
        setErr(ex instanceof ApiError ? ex.message : "Report not found.");
      }
    })();
  }, [apiKey, id]);

  const chartRows = useMemo(() => {
    if (!detail) return [];
    return Object.entries(detail.aggregate_metrics)
      .filter(([, v]) => typeof v === "number")
      .map(([name, score]) => ({
        metric: name.replace(/_/g, " "),
        score: Number(score),
      }))
      .sort((a, b) => a.metric.localeCompare(b.metric));
  }, [detail]);

  const tableColumns = useMemo(() => {
    if (!detail?.per_row_metrics.length) return [] as string[];
    const prefs = ["golden_id", "category", "question_preview"];
    const seen = new Set<string>();
    for (const row of detail.per_row_metrics) {
      for (const k of Object.keys(row)) seen.add(k);
    }
    const rest = [...seen].filter((k) => !prefs.includes(k)).sort();
    return [...prefs.filter((k) => seen.has(k)), ...rest];
  }, [detail]);

  const traceHref = langfuseTraceUrl(detail?.langfuse_trace_id);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <Link href="/eval" className="text-sky-400 hover:text-sky-300">
          ← Reports
        </Link>
      </div>

      {!apiKey.trim() && (
        <p className="rounded-lg border border-amber-900/60 bg-amber-950/30 px-4 py-3 text-sm text-amber-200">
          Mint an API key and store it locally to view report details.
        </p>
      )}

      {err && apiKey.trim() && (
        <p className="rounded-lg border border-red-900/60 bg-red-950/40 px-4 py-2 text-sm text-red-200">
          {err}
        </p>
      )}

      {detail && (
        <>
          <div>
            <h1 className="text-xl font-semibold text-zinc-100">Eval report</h1>
            <p className="mt-2 text-xs text-zinc-500">{detail.id}</p>
            <p className="mt-1 text-sm text-zinc-400">
              {new Date(detail.created_at).toLocaleString()}
              {" · "}
              {detail.mode}
              {" · "}
              {detail.n_samples} samples
              {detail.trigger ? ` · trigger: ${detail.trigger}` : ""}
              {detail.git_commit ? (
                <>
                  {" · "}
                  <code className="rounded bg-zinc-900 px-1 text-[11px] text-zinc-400">
                    {detail.git_commit}
                  </code>
                </>
              ) : null}
            </p>
            <div className="mt-3 flex flex-wrap gap-3 text-xs text-zinc-500">
              <span>
                judge:{" "}
                <code className="text-zinc-400">{detail.judge_model}</code>
              </span>
              <span>
                embedding:{" "}
                <code className="text-zinc-400">{detail.embedding_model}</code>
              </span>
              {traceHref ? (
                <a
                  href={traceHref}
                  className="text-sky-400 hover:text-sky-300"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Open Langfuse trace
                </a>
              ) : null}
            </div>
          </div>

          <div className="rounded-xl border border-zinc-800 bg-zinc-950/50 px-4 py-5">
            <h2 className="text-sm font-medium uppercase tracking-wide text-zinc-500">
              Aggregate metrics
            </h2>
            <div className="mt-4 h-64">
              {chartRows.length === 0 ? (
                <p className="py-16 text-center text-sm text-zinc-500">
                  No numeric aggregate scores in this report (check persistence / RAGAS
                  columns).
                </p>
              ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    {/* Recharts 3: layout vertical = category on Y, numeric on X (bars extend left→right). */}
                    <BarChart
                      data={chartRows}
                      layout="vertical"
                      margin={{ top: 8, right: 12, bottom: 8, left: 120 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" stroke="#3f3f46" />
                      <XAxis
                        type="number"
                        domain={[0, 1]}
                        allowDecimals
                        ticks={[0, 0.25, 0.5, 0.75, 1]}
                        stroke="#71717a"
                        tick={{ fill: "#a1a1aa", fontSize: 11 }}
                      />
                      <YAxis
                        type="category"
                        dataKey="metric"
                        width={110}
                        stroke="#71717a"
                        tick={{ fill: "#a1a1aa", fontSize: 11 }}
                      />
                      <Tooltip
                        contentStyle={{
                          background: "#18181b",
                          border: "1px solid #27272a",
                          color: "#e4e4e7",
                        }}
                      />
                      <Bar dataKey="score" fill="#38bdf8" radius={[0, 4, 4, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
              )}
            </div>
          </div>

          <div>
            <h2 className="text-sm font-medium uppercase tracking-wide text-zinc-500">
              Per-sample rows
            </h2>
            <div className="mt-3 overflow-x-auto rounded-lg border border-zinc-800">
              <table className="min-w-full max-w-[90vw] text-left text-xs">
                <thead className="border-b border-zinc-800 bg-zinc-900/60 text-[10px] uppercase tracking-wide text-zinc-500">
                  <tr>
                    {tableColumns.map((c) => (
                      <th
                        key={c}
                        className="whitespace-nowrap px-3 py-2 font-medium"
                      >
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800">
                  {detail.per_row_metrics.map((row, i) => (
                    <tr key={String(i)} className="hover:bg-zinc-900/40">
                      {tableColumns.map((col) => {
                        const raw = row[col];
                        const cell = cellDisplayString(raw);
                        const isNumeric =
                          typeof raw === "number" && Number.isFinite(raw);

                        return (
                          <td
                            key={`${i}-${col}`}
                            className={`align-top px-3 py-2 ${isNumeric ? "tabular-nums text-zinc-300" : ""}`}
                          >
                            {isNumeric || cell === "—" ? (
                              <span className="text-zinc-300">{cell}</span>
                            ) : (
                              <ExpandableTextCell text={cell} />
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
