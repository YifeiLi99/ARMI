import type { components } from "./generated/creator";

export type BrowserSession =
  components["schemas"]["BrowserSessionCurrentResponse"];
export type BrowserSessionEstablished =
  components["schemas"]["BrowserSessionResponse"];
export type RuntimeStatus = components["schemas"]["RuntimeStatusResponse"];
export type SceneTimelinePage =
  components["schemas"]["SceneTimelinePageResponse"];

export class ApiFailure extends Error {
  constructor(readonly status: number) {
    super(`Creator request failed with status ${status}`);
  }
}

async function requireJson<Response>(
  response: globalThis.Response,
): Promise<Response> {
  if (!response.ok) {
    throw new ApiFailure(response.status);
  }
  return (await response.json()) as Response;
}

export async function createBrowserSession(
  bootstrapCode: string,
  signal?: AbortSignal,
): Promise<BrowserSessionEstablished> {
  const response = await fetch("/v1/browser-sessions", {
    method: "POST",
    credentials: "omit",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ bootstrap_code: bootstrapCode }),
    ...(signal === undefined ? {} : { signal }),
  });
  return requireJson(response);
}

export async function getCurrentBrowserSession(
  token: string,
  signal?: AbortSignal,
): Promise<BrowserSession> {
  const response = await fetch("/v1/browser-sessions/current", {
    credentials: "omit",
    headers: { Authorization: `Bearer ${token}` },
    ...(signal === undefined ? {} : { signal }),
  });
  return requireJson(response);
}

export async function getRuntimeStatus(
  token: string,
  signal?: AbortSignal,
): Promise<RuntimeStatus> {
  const response = await fetch("/v1/runtime/status", {
    credentials: "omit",
    headers: { Authorization: `Bearer ${token}` },
    ...(signal === undefined ? {} : { signal }),
  });
  return requireJson(response);
}

export async function deleteCurrentBrowserSession(
  token: string,
): Promise<void> {
  const response = await fetch("/v1/browser-sessions/current", {
    method: "DELETE",
    credentials: "omit",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    throw new ApiFailure(response.status);
  }
}

export async function getSceneTimeline(
  token: string,
  sceneKey: string,
  limit: number,
  cursor?: string,
  signal?: AbortSignal,
): Promise<SceneTimelinePage> {
  const query = new URLSearchParams({ limit: String(limit) });
  if (cursor !== undefined) {
    query.set("cursor", cursor);
  }
  const response = await fetch(
    `/v1/scenes/${encodeURIComponent(sceneKey)}/timeline?${query.toString()}`,
    {
      credentials: "omit",
      headers: { Authorization: `Bearer ${token}` },
      ...(signal === undefined ? {} : { signal }),
    },
  );
  return requireJson(response);
}
