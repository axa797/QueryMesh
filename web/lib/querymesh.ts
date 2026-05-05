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
