import { getPortalJwt } from "@/lib/auth-storage";

/** Decode portal JWT payload (display only; API verifies the real token). */
function payloadFromJwt(token: string): Record<string, unknown> | null {
  try {
    const seg = token.split(".")[1];
    if (!seg) return null;
    const base64 = seg.replace(/-/g, "+").replace(/_/g, "/");
    const pad = (4 - (base64.length % 4)) % 4;
    const padded = base64 + "=".repeat(pad);
    const json = atob(padded);
    return JSON.parse(json) as Record<string, unknown>;
  } catch {
    return null;
  }
}

/** `name` from Google when present in JWT. */
export function getPortalJwtName(): string | null {
  const t = getPortalJwt();
  if (!t) return null;
  const p = payloadFromJwt(t);
  const n = p?.name;
  return typeof n === "string" && n.trim() ? n.trim() : null;
}

/** Email claim when issued from Google OAuth; absent for older tokens. */
export function getPortalJwtEmail(): string | null {
  const t = getPortalJwt();
  if (!t) return null;
  const p = payloadFromJwt(t);
  const e = p?.email;
  return typeof e === "string" && e.trim() ? e.trim() : null;
}

export function initialsFromEmail(email: string | null): string {
  if (!email) return "?";
  const local = email.split("@")[0]?.trim();
  if (!local) return "?";
  const parts = local.split(/[._-]+/).filter(Boolean);
  if (parts.length >= 2) {
    return (parts[0]![0]! + parts[1]![0]!).toUpperCase();
  }
  return local.slice(0, 2).toUpperCase();
}
