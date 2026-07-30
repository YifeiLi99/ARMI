const STORAGE_KEY = "armi.browser-session.v1";

export interface StoredBrowserSession {
  token: string;
  expiresAt: string;
  environmentId: string;
}

export function loadStoredSession(): StoredBrowserSession | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (raw === null) {
      return null;
    }
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed !== "object" ||
      parsed === null ||
      Object.keys(parsed).sort().join(",") !==
        "environmentId,expiresAt,token" ||
      typeof (parsed as StoredBrowserSession).token !== "string" ||
      typeof (parsed as StoredBrowserSession).expiresAt !== "string" ||
      typeof (parsed as StoredBrowserSession).environmentId !== "string"
    ) {
      clearStoredSession();
      return null;
    }
    return parsed as StoredBrowserSession;
  } catch {
    clearStoredSession();
    return null;
  }
}

export function saveStoredSession(session: StoredBrowserSession): void {
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session));
}

export function clearStoredSession(): void {
  sessionStorage.removeItem(STORAGE_KEY);
}
