/** Browser-accessible QueryMesh API base (FastAPI). */
export function getApiBase(): string {
  const raw = process.env.NEXT_PUBLIC_QUERYMESH_URL || "http://127.0.0.1:8000";
  return raw.replace(/\/$/, "");
}

export type PortalTokenResponse = {
  access_token: string;
  token_type: string;
  user_id: string;
};

export type ApiKeyListItem = {
  key_id: string;
  created_at: string;
  revoked_at: string | null;
};

export type ApiKeyCreateResponse = {
  api_key: string;
  key_id: string;
};

export type SourceCard = {
  point_id: string;
  source_doc: string;
  section: string;
  product: string;
  page_number?: unknown;
  score?: unknown;
  excerpt: string;
};

export type QueryMeshSuccess = {
  response: {
    status?: string;
    synthesis?: { message?: string };
    source_cards?: SourceCard[];
    [key: string]: unknown;
  };
  session_id: string;
  trace_id: string;
  latency_ms: number;
};

export type StreamQueryEvent =
  | { type: "phase"; node: string }
  | { type: "assistant_partial"; message: string }
  | { type: "done"; payload: QueryMeshSuccess }
  | { type: "error"; message: string };

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function errorDetail(body: unknown): string {
  if (body == null) return "Request failed";
  if (typeof body === "string") return body;
  if (typeof body !== "object") return String(body);
  const o = body as Record<string, unknown>;
  if (typeof o.message === "string") return o.message;
  if (typeof o.error === "string" && typeof o.message === "string") return o.message;
  if (typeof o.detail === "string") return o.detail;
  if (Array.isArray(o.detail)) return JSON.stringify(o.detail);
  if (o.detail && typeof o.detail === "object") {
    const d = o.detail as Record<string, unknown>;
    if (typeof d.message === "string") return d.message;
  }
  try {
    return JSON.stringify(body);
  } catch {
    return "Request failed";
  }
}

export async function readJsonResponse<T>(res: Response): Promise<T> {
  const text = await res.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text) as unknown;
    } catch {
      body = text;
    }
  }
  if (!res.ok) {
    throw new ApiError(errorDetail(body), res.status);
  }
  return body as T;
}

export async function postQueryStream(
  body: { query: string; session_id?: string },
  headers: Record<string, string>,
  onEvent: (e: StreamQueryEvent) => void,
): Promise<void> {
  const res = await fetch(`${getApiBase()}/query/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...headers,
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new ApiError(await res.text(), res.status);
  }
  const reader = res.body?.getReader();
  if (!reader) {
    throw new ApiError("No response stream", res.status);
  }
  const dec = new TextDecoder();
  let buf = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let sep: number;
    while ((sep = buf.indexOf("\n\n")) !== -1) {
      const block = buf.slice(0, sep);
      buf = buf.slice(sep + 2);
      const line = block
        .split("\n")
        .map((l) => l.trim())
        .find((l) => l.startsWith("data:"));
      if (!line) continue;
      const raw = line.slice(5).trim();
      if (!raw) continue;
      try {
        const obj = JSON.parse(raw) as unknown;
        const o = obj as Record<string, unknown>;
        if (o?.type === "phase" && typeof o.node === "string") {
          onEvent({ type: "phase", node: o.node });
        } else if (
          o?.type === "assistant_partial" &&
          typeof o.message === "string"
        ) {
          onEvent({ type: "assistant_partial", message: o.message });
        } else if (o?.type === "done" && o.payload && typeof o.payload === "object") {
          onEvent({
            type: "done",
            payload: o.payload as QueryMeshSuccess,
          });
        } else if (o?.type === "error") {
          onEvent({
            type: "error",
            message: typeof o.message === "string" ? o.message : "stream_failed",
          });
        }
      } catch {
        /* malformed chunk */
      }
    }
  }
}

export async function postJson<T>(
  path: string,
  body: unknown,
  headers?: Record<string, string>,
): Promise<T> {
  const res = await fetch(`${getApiBase()}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...headers,
    },
    body: JSON.stringify(body),
  });
  return readJsonResponse<T>(res);
}

export async function getJson<T>(path: string, headers?: Record<string, string>): Promise<T> {
  const res = await fetch(`${getApiBase()}${path}`, {
    headers: { ...headers },
  });
  return readJsonResponse<T>(res);
}

export function formatQueryReply(data: QueryMeshSuccess): string {
  const msg = data.response?.synthesis?.message;
  if (typeof msg === "string" && msg.trim()) return msg;
  return JSON.stringify(data, null, 2);
}

/** Role strings from GET /query/history (checkpoint transcript). */
export type HistoryMessageRow = {
  role: "user" | "assistant" | "tool";
  content: string;
  /** Present on assistant rows when retrieval produced hits for that turn. */
  source_cards?: SourceCard[];
};

export type QueryHistoryResponse = {
  messages: HistoryMessageRow[];
  session_id: string | null;
};

export async function fetchQueryHistory(
  sessionId: string,
  headers: Record<string, string>,
): Promise<HistoryMessageRow[]> {
  const q = encodeURIComponent(sessionId);
  const res = await getJson<QueryHistoryResponse>(
    `/query/history?session_id=${q}`,
    headers,
  );
  return Array.isArray(res.messages) ? res.messages : [];
}

export type QuerySessionItem = {
  session_id: string;
  last_checkpoint_id: string;
};

export type QuerySessionsResponse = {
  sessions: QuerySessionItem[];
};

export async function fetchQuerySessions(
  headers: Record<string, string>,
): Promise<QuerySessionItem[]> {
  const res = await getJson<QuerySessionsResponse>(`/query/sessions`, headers);
  return Array.isArray(res.sessions) ? res.sessions : [];
}

/** Persisted eval report rows from ``GET /eval-reports``. */
export type EvalReportSummaryDTO = {
  id: string;
  created_at: string;
  mode: string;
  n_samples: number;
  aggregate_metrics: Record<string, number>;
  judge_model: string;
  embedding_model: string;
  langfuse_trace_id: string | null;
  trigger: string;
};

export type EvalReportDetailDTO = EvalReportSummaryDTO & {
  per_row_metrics: Record<string, unknown>[];
  git_commit: string | null;
};

export type PaginatedEvalReportsDTO = {
  items: EvalReportSummaryDTO[];
  total: number;
  page: number;
  page_size: number;
};

/**
 * Normalizes 32-char hex OTEL-style ids to hyphenated UUIDs for Langfuse ``/traces/`` segments.
 *
 * Persisted Langfuse URLs from ``evals.ragas_eval`` (``get_trace_url``) skip this entirely.
 */
function formatLangfuseTraceIdForPath(id: string): string {
  const t = id.trim();
  if (/^[0-9a-f]{32}$/i.test(t)) {
    return `${t.slice(0, 8)}-${t.slice(8, 12)}-${t.slice(12, 16)}-${t.slice(16, 20)}-${t.slice(20)}`;
  }
  return t;
}

/**
 * Absolute Langfuse trace URL when the persisted value or env allows building one.
 *
 * Langfuse UI paths are ``{origin}/project/{projectId}/traces/{traceId}``, not ``/traces/{id}``.
 */
export function langfuseTraceUrl(
  traceIdOrUrl: string | null | undefined,
): string | null {
  const raw = traceIdOrUrl?.trim();
  if (!raw) return null;

  // Eval CLI persists the SDK ``get_trace_url`` result (correct region + project).
  if (/^https?:\/\//i.test(raw)) {
    try {
      return new URL(raw).toString();
    } catch {
      return null;
    }
  }

  const base = (process.env.NEXT_PUBLIC_LANGFUSE_PUBLIC_URL || "").replace(
    /\/$/,
    "",
  );
  if (!base) return null;

  const projectId = (process.env.NEXT_PUBLIC_LANGFUSE_PROJECT_ID || "").replace(
    /\/$/,
    "",
  );
  if (!projectId) return null;

  const traceSegment = encodeURIComponent(formatLangfuseTraceIdForPath(raw));
  const proj = encodeURIComponent(projectId);

  try {
    return new URL(`/project/${proj}/traces/${traceSegment}`, `${base}/`)
      .toString();
  } catch {
    return null;
  }
}

export async function fetchEvalReportsPage(
  page: number,
  pageSize: number,
  headers: Record<string, string>,
): Promise<PaginatedEvalReportsDTO> {
  const q = `page=${page}&page_size=${pageSize}`;
  return getJson<PaginatedEvalReportsDTO>(`/eval-reports?${q}`, headers);
}

export async function fetchEvalReportDetail(
  id: string,
  headers: Record<string, string>,
): Promise<EvalReportDetailDTO> {
  return getJson<EvalReportDetailDTO>(
    `/eval-reports/${encodeURIComponent(id)}`,
    headers,
  );
}
