import { getApiBase } from "@/lib/querymesh";

const HEALTH_TIMEOUT_MS = 4000;

export type ApiReachabilityOk = { ok: true };

export type ApiReachabilityFail = {
  ok: false;
  kind: "timeout" | "network" | "http";
  status?: number;
};

export type ApiReachabilityResult = ApiReachabilityOk | ApiReachabilityFail;

/**
 * Probes whether the browser can reach the FastAPI `/health` endpoint.
 * Used before OAuth redirect so users don't land on a dead host tab.
 */
export async function probeApiHealth(): Promise<ApiReachabilityResult> {
  const url = `${getApiBase()}/health`;
  try {
    const res = await fetch(url, {
      method: "GET",
      cache: "no-store",
      signal: AbortSignal.timeout(HEALTH_TIMEOUT_MS),
    });
    if (!res.ok) {
      return { ok: false, kind: "http", status: res.status };
    }
    const body: unknown = await res.json().catch(() => null);
    if (
      body &&
      typeof body === "object" &&
      (body as { status?: unknown }).status === "ok"
    ) {
      return { ok: true };
    }
    return { ok: false, kind: "http", status: res.status };
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") {
      return { ok: false, kind: "timeout" };
    }
    return { ok: false, kind: "network" };
  }
}
