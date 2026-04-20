type ApiFetchOptions = RequestInit & {
  requireSupabaseAuth?: boolean;
};

const SUPABASE_ACCESS_TOKEN_KEYS = [
  "supabase.access_token",
  "sb-access-token",
  "sb:access_token",
];

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined)
  ?.trim()
  .replace(/\/$/, "");

function resolveApiUrl(url: string): string {
  if (!API_BASE_URL) {
    return url;
  }

  if (url === "/api") {
    return API_BASE_URL;
  }

  if (url.startsWith("/api/")) {
    return `${API_BASE_URL}${url.slice(4)}`;
  }

  if (url.startsWith("/")) {
    return `${API_BASE_URL}${url}`;
  }

  return url;
}

function parseSupabaseSessionPayload(payload: string | null): string | null {
  if (!payload) return null;

  try {
    const parsed = JSON.parse(payload);

    if (typeof parsed === "string") {
      return parsed;
    }

    if (parsed?.access_token && typeof parsed.access_token === "string") {
      return parsed.access_token;
    }

    if (parsed?.currentSession?.access_token) {
      return parsed.currentSession.access_token as string;
    }

    if (Array.isArray(parsed) && parsed.length > 0) {
      const first = parsed[0];
      if (first?.access_token && typeof first.access_token === "string") {
        return first.access_token;
      }
    }
  } catch {
    if (payload.includes(".")) {
      return payload;
    }
  }

  return null;
}

function getSupabaseAccessToken(): string | null {
  if (typeof window === "undefined") return null;

  for (const key of SUPABASE_ACCESS_TOKEN_KEYS) {
    const token = parseSupabaseSessionPayload(window.localStorage.getItem(key));
    if (token) return token;
  }

  for (let i = 0; i < window.localStorage.length; i += 1) {
    const key = window.localStorage.key(i);
    if (!key) continue;

    if (key.startsWith("sb-") && key.endsWith("-auth-token")) {
      const token = parseSupabaseSessionPayload(window.localStorage.getItem(key));
      if (token) return token;
    }
  }

  return null;
}

export async function apiFetch(url: string, options: ApiFetchOptions = {}) {
  const { requireSupabaseAuth = false, headers, ...rest } = options;
  const token = getSupabaseAccessToken();

  if (requireSupabaseAuth && !token) {
    throw new Error("Supabase session not found. Please sign in again.");
  }

  const mergedHeaders = new Headers(headers ?? {});
  if (token && !mergedHeaders.has("Authorization")) {
    mergedHeaders.set("Authorization", `Bearer ${token}`);
  }

  return fetch(url, {
    credentials: "include",
    headers: mergedHeaders,
    ...rest,
  });
}
