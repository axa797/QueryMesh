export const PORTAL_JWT_KEY = "querymesh_portal_jwt";
export const API_KEY_STORAGE = "querymesh_api_key";
export const SESSION_STORAGE_KEY = "querymesh_session_id";

export function getPortalJwt(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(PORTAL_JWT_KEY);
}

export function setPortalJwt(token: string): void {
  localStorage.setItem(PORTAL_JWT_KEY, token);
}

export function getStoredApiKey(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(API_KEY_STORAGE);
}

export function setStoredApiKey(key: string): void {
  localStorage.setItem(API_KEY_STORAGE, key);
}

export function clearSession(): void {
  if (typeof window !== "undefined")
    sessionStorage.removeItem(SESSION_STORAGE_KEY);
}

export function clearAuth(): void {
  localStorage.removeItem(PORTAL_JWT_KEY);
  localStorage.removeItem(API_KEY_STORAGE);
  clearSession();
}
