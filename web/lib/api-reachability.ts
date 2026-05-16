"use client";

import { useCallback, useEffect, useState } from "react";
import { getApiBase } from "@/lib/querymesh";

const HEALTH_TIMEOUT_MS = 4000;
const POLL_WHEN_DOWN_MS = 20_000;

export type HealthServices = {
  postgres?: boolean;
  redis?: boolean;
  qdrant?: boolean;
};

export type ApiReachabilityOk = { ok: true; services: HealthServices };

export type ApiReachabilityFail = {
  ok: false;
  kind: "timeout" | "network" | "http" | "degraded";
  status?: number;
  services?: HealthServices;
};

export type ApiReachabilityResult = ApiReachabilityOk | ApiReachabilityFail;

export type ApiReachabilityState = "checking" | "up" | "down";

const OFFLINE_SHORT =
  "We can't reach the API right now. When it's back, this will work again.";

const OFFLINE_BODY =
  "The QueryMesh API isn't ready—often because the backend is parked. Run wake_gcp_compute.sh or start local services, then try again.";

/** True when /health reports full readiness (postgres + redis required for chat/auth). */
export function isHealthReady(body: unknown): boolean {
  if (!body || typeof body !== "object") return false;
  const o = body as {
    status?: unknown;
    services?: { postgres?: unknown; redis?: unknown };
  };
  if (o.status !== "ok") return false;
  const svc = o.services;
  if (!svc || typeof svc !== "object") return false;
  return svc.postgres === true && svc.redis === true;
}

function parseServices(body: unknown): HealthServices {
  if (!body || typeof body !== "object") return {};
  const svc = (body as { services?: unknown }).services;
  if (!svc || typeof svc !== "object") return {};
  const s = svc as Record<string, unknown>;
  return {
    postgres: s.postgres === true,
    redis: s.redis === true,
    qdrant: s.qdrant === true,
  };
}

/**
 * Probes FastAPI `/health` for liveness and readiness (postgres + redis).
 */
export async function probeApiHealth(): Promise<ApiReachabilityResult> {
  const url = `${getApiBase()}/health`;
  try {
    const res = await fetch(url, {
      method: "GET",
      cache: "no-store",
      signal: AbortSignal.timeout(HEALTH_TIMEOUT_MS),
    });
    const body: unknown = await res.json().catch(() => null);
    const services = parseServices(body);
    if (!res.ok) {
      return { ok: false, kind: "http", status: res.status, services };
    }
    if (isHealthReady(body)) {
      return { ok: true, services };
    }
    const status =
      body && typeof body === "object"
        ? (body as { status?: unknown }).status
        : undefined;
    return {
      ok: false,
      kind: status === "degraded" ? "degraded" : "http",
      status: res.status,
      services,
    };
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") {
      return { ok: false, kind: "timeout" };
    }
    return { ok: false, kind: "network" };
  }
}

/** User-facing copy for errors and OAuth fragments (no raw errno). */
export function formatUserFacingApiError(err: unknown): string {
  if (err == null) return OFFLINE_SHORT;
  const raw = err instanceof Error ? err.message : String(err);
  const lower = raw.toLowerCase();
  if (
    lower.includes("connection refused") ||
    lower.includes("errno 111") ||
    lower.includes("failed to fetch") ||
    lower.includes("networkerror") ||
    lower.includes("load failed")
  ) {
    return OFFLINE_SHORT;
  }
  if (
    lower.includes("database is unavailable") ||
    lower.includes("backend is running") ||
    lower.includes("oauth_failed")
  ) {
    return raw;
  }
  if (lower.startsWith("account error:") || lower.includes("operationalerror")) {
    return "Sign-in could not be completed. Try again when the backend is running.";
  }
  if (lower.includes("token exchange failed")) {
    return "Google sign-in could not be completed. Try again when the API is ready.";
  }
  return raw.length > 200 ? OFFLINE_SHORT : raw;
}

export function offlineMessage(variant: "short" | "body" = "short"): string {
  return variant === "body" ? OFFLINE_BODY : OFFLINE_SHORT;
}

export function useApiReachability(): {
  state: ApiReachabilityState;
  apiOffline: boolean;
  recheck: () => Promise<void>;
} {
  const [state, setState] = useState<ApiReachabilityState>("checking");

  const recheck = useCallback(async () => {
    const r = await probeApiHealth();
    setState(r.ok ? "up" : "down");
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const r = await probeApiHealth();
      if (!cancelled) setState(r.ok ? "up" : "down");
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (state !== "down") return;
    const id = window.setInterval(() => {
      void recheck();
    }, POLL_WHEN_DOWN_MS);
    return () => window.clearInterval(id);
  }, [state, recheck]);

  return {
    state,
    apiOffline: state === "down",
    recheck,
  };
}
