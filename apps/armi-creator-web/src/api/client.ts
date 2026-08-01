import type { components } from "./generated/creator";

export type BrowserSession =
  components["schemas"]["BrowserSessionCurrentResponse"];
export type BrowserSessionEstablished =
  components["schemas"]["BrowserSessionResponse"];
export type RuntimeStatus = components["schemas"]["RuntimeStatusResponse"];
export type SceneTimelinePage =
  components["schemas"]["SceneTimelinePageResponse"];
export type AcceptedOperation =
  components["schemas"]["AcceptedOutcomeResponse"];
export type CreatorOperation =
  components["schemas"]["OperationOutcomeResponse"];
export type SubjectSummary = components["schemas"]["SubjectSummaryResponse"];
export type CapabilityRequestPage =
  components["schemas"]["CapabilityRequestPageResponse"];
export type CapabilityRequest =
  components["schemas"]["CapabilityRequestItemResponse"];
export type CapabilityDecision =
  components["schemas"]["CapabilityRequestDecisionRequest"];
export type CapabilityDecisionResult =
  components["schemas"]["AppliedOutcomeResponse"];
export type EffectDetail = components["schemas"]["EffectResponse"];

export class ApiFailure extends Error {
  constructor(
    readonly status: number,
    readonly code?: string,
  ) {
    super(`Creator request failed with status ${status}`);
  }
}

async function safeErrorCode(
  response: globalThis.Response,
): Promise<string | undefined> {
  try {
    const body: unknown = await response.json();
    if (
      typeof body === "object" &&
      body !== null &&
      "error" in body &&
      typeof body.error === "object" &&
      body.error !== null &&
      "code" in body.error &&
      typeof body.error.code === "string" &&
      /^[A-Z][A-Z0-9_]{2,127}$/.test(body.error.code)
    ) {
      return body.error.code;
    }
  } catch {
    // The status remains the only trusted error signal.
  }
  return undefined;
}

async function requireJson<Response>(
  response: globalThis.Response,
): Promise<Response> {
  if (!response.ok) {
    throw new ApiFailure(response.status, await safeErrorCode(response));
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

export async function acceptCreatorMessage(
  token: string,
  sceneKey: string,
  idempotencyKey: string,
  message: string,
  signal?: AbortSignal,
): Promise<AcceptedOperation> {
  const response = await fetch(
    `/v1/scenes/${encodeURIComponent(sceneKey)}/messages`,
    {
      method: "POST",
      credentials: "omit",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey,
      },
      body: JSON.stringify({ contract_version: "1.0", message }),
      ...(signal === undefined ? {} : { signal }),
    },
  );
  return requireJson(response);
}

export async function getCreatorOperation(
  token: string,
  operationRef: string,
  signal?: AbortSignal,
): Promise<CreatorOperation> {
  const response = await fetch(
    `/v1/operations/${encodeURIComponent(operationRef)}`,
    {
      credentials: "omit",
      headers: { Authorization: `Bearer ${token}` },
      ...(signal === undefined ? {} : { signal }),
    },
  );
  return requireJson(response);
}

export async function getSubjectSummary(
  token: string,
  signal?: AbortSignal,
): Promise<SubjectSummary> {
  const response = await fetch("/v1/subject/summary", {
    credentials: "omit",
    headers: { Authorization: `Bearer ${token}` },
    ...(signal === undefined ? {} : { signal }),
  });
  return requireJson(response);
}

export async function getCapabilityRequests(
  token: string,
  limit: number,
  cursor?: string,
  signal?: AbortSignal,
): Promise<CapabilityRequestPage> {
  const query = new URLSearchParams({ limit: String(limit) });
  if (cursor !== undefined) {
    query.set("cursor", cursor);
  }
  const response = await fetch(`/v1/capability-requests?${query.toString()}`, {
    credentials: "omit",
    headers: { Authorization: `Bearer ${token}` },
    ...(signal === undefined ? {} : { signal }),
  });
  return requireJson(response);
}

export async function decideCapabilityRequest(
  token: string,
  requestId: string,
  decision: CapabilityDecision,
  signal?: AbortSignal,
): Promise<CapabilityDecisionResult> {
  const response = await fetch(
    `/v1/capability-requests/${encodeURIComponent(requestId)}/decision`,
    {
      method: "POST",
      credentials: "omit",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(decision),
      ...(signal === undefined ? {} : { signal }),
    },
  );
  return requireJson(response);
}

export async function getEffectDetail(
  token: string,
  effectId: string,
  signal?: AbortSignal,
): Promise<EffectDetail> {
  const response = await fetch(`/v1/effects/${encodeURIComponent(effectId)}`, {
    credentials: "omit",
    headers: { Authorization: `Bearer ${token}` },
    ...(signal === undefined ? {} : { signal }),
  });
  return requireJson(response);
}
