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

export type QueryMeshSuccess = {
  response: {
    status?: string;
    synthesis?: { message?: string };
    [key: string]: unknown;
  };
  session_id: string;
  trace_id: string;
  latency_ms: number;
};

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
    throw new Error(errorDetail(body));
  }
  return body as T;
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
