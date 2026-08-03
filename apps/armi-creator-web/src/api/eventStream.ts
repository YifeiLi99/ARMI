import type { components } from "./generated/creator";

export type CreatorProjectionEvent =
  components["schemas"]["CreatorProjectionEventResponse"];

const EVENT_ID = /^sse-v1\.([A-Za-z0-9_-]{22})\.([1-9][0-9]*)$/;
const SCENE_KEY = /^[a-z0-9][a-z0-9._-]{0,63}$/;
const UUID_V7 =
  /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const INSTANT = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:[0-5]\d\.\d{6}Z$/;
const MAX_EVENT_BYTES = 4096;
const RESOURCES = {
  scene_timeline: [
    "scene.timeline.invalidated",
    "scene-timeline.v3",
    SCENE_KEY,
  ],
  capability_request: [
    "capability.request.invalidated",
    "capability-request.v3",
    UUID_V7,
  ],
  operation: ["operation.invalidated", "creator-operation.v1", UUID_V7],
  effect: ["effect.invalidated", "creator-effect.v1", UUID_V7],
  subject_summary: [
    "subject.summary.invalidated",
    "subject-summary.v1",
    UUID_V7,
  ],
} as const;

export class EventStreamFailure extends Error {
  constructor(
    readonly kind: "http" | "content-type" | "decode" | "syntax" | "event",
    readonly status?: number,
  ) {
    super("Creator event stream failed");
  }
}

type PendingEvent = {
  id?: string;
  event?: string;
  data?: string;
  retry?: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseEventData(value: string): CreatorProjectionEvent {
  if (new TextEncoder().encode(value).byteLength > MAX_EVENT_BYTES) {
    throw new EventStreamFailure("event");
  }
  let decoded: unknown;
  try {
    decoded = JSON.parse(value);
  } catch {
    throw new EventStreamFailure("event");
  }
  if (!isRecord(decoded)) {
    throw new EventStreamFailure("event");
  }
  const keys = Object.keys(decoded).sort();
  const expected = [
    "contract_version",
    "event_id",
    "event_kind",
    "occurred_at",
    "projection_version",
    "resource_kind",
    "resource_ref",
  ];
  if (
    keys.length !== expected.length ||
    keys.some((key, index) => key !== expected[index])
  ) {
    throw new EventStreamFailure("event");
  }
  const resource =
    typeof decoded.resource_kind === "string" &&
    decoded.resource_kind in RESOURCES
      ? RESOURCES[decoded.resource_kind as keyof typeof RESOURCES]
      : undefined;
  if (
    decoded.contract_version !== "1.0" ||
    typeof decoded.event_id !== "string" ||
    !EVENT_ID.test(decoded.event_id) ||
    resource === undefined ||
    decoded.event_kind !== resource[0] ||
    typeof decoded.resource_ref !== "string" ||
    !resource[2].test(decoded.resource_ref) ||
    decoded.projection_version !== resource[1] ||
    typeof decoded.occurred_at !== "string" ||
    !INSTANT.test(decoded.occurred_at)
  ) {
    throw new EventStreamFailure("event");
  }
  return decoded as CreatorProjectionEvent;
}

function acceptField(pending: PendingEvent, line: string): void {
  if (line.startsWith(":")) {
    if (line.length > MAX_EVENT_BYTES) {
      throw new EventStreamFailure("syntax");
    }
    return;
  }
  const separator = line.indexOf(":");
  if (separator < 1) {
    throw new EventStreamFailure("syntax");
  }
  const field = line.slice(0, separator);
  let value = line.slice(separator + 1);
  if (value.startsWith(" ")) {
    value = value.slice(1);
  }
  if (!["id", "event", "data", "retry"].includes(field)) {
    throw new EventStreamFailure("syntax");
  }
  const key = field as keyof PendingEvent;
  if (pending[key] !== undefined) {
    throw new EventStreamFailure("syntax");
  }
  pending[key] = value;
}

function finishEvent(
  pending: PendingEvent,
): CreatorProjectionEvent | undefined {
  if (
    pending.id === undefined &&
    pending.event === undefined &&
    pending.data === undefined
  ) {
    if (pending.retry !== undefined && pending.retry !== "1000") {
      throw new EventStreamFailure("syntax");
    }
    return undefined;
  }
  if (
    pending.id === undefined ||
    pending.event === undefined ||
    pending.data === undefined ||
    pending.retry !== undefined
  ) {
    throw new EventStreamFailure("syntax");
  }
  const event = parseEventData(pending.data);
  if (event.event_id !== pending.id || event.event_kind !== pending.event) {
    throw new EventStreamFailure("event");
  }
  return event;
}

export async function* parseCreatorEventStream(
  chunks: AsyncIterable<Uint8Array>,
): AsyncGenerator<CreatorProjectionEvent> {
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let buffered = "";
  let pending: PendingEvent = {};
  try {
    for await (const chunk of chunks) {
      buffered += decoder.decode(chunk, { stream: true });
      if (buffered.length > MAX_EVENT_BYTES * 2) {
        throw new EventStreamFailure("syntax");
      }
      while (true) {
        const newline = buffered.indexOf("\n");
        if (newline < 0) {
          break;
        }
        let line = buffered.slice(0, newline);
        buffered = buffered.slice(newline + 1);
        if (line.endsWith("\r")) {
          line = line.slice(0, -1);
        } else if (line.includes("\r")) {
          throw new EventStreamFailure("syntax");
        }
        if (line.length > MAX_EVENT_BYTES) {
          throw new EventStreamFailure("syntax");
        }
        if (line === "") {
          const event = finishEvent(pending);
          pending = {};
          if (event !== undefined) {
            yield event;
          }
        } else {
          acceptField(pending, line);
        }
      }
    }
    buffered += decoder.decode();
  } catch (error) {
    if (error instanceof EventStreamFailure) {
      throw error;
    }
    throw new EventStreamFailure("decode");
  }
}

async function* responseChunks(
  body: ReadableStream<Uint8Array>,
  signal: AbortSignal,
): AsyncGenerator<Uint8Array> {
  const reader = body.getReader();
  const abort = () => void reader.cancel();
  signal.addEventListener("abort", abort, { once: true });
  try {
    while (!signal.aborted) {
      const result = await reader.read();
      if (result.done) {
        return;
      }
      yield result.value;
    }
  } finally {
    signal.removeEventListener("abort", abort);
    reader.releaseLock();
  }
}

export async function consumeCreatorEventStream(
  token: string,
  sceneKey: string,
  lastEventId: string | undefined,
  signal: AbortSignal,
  onConnected: () => void,
  onEvent: (event: CreatorProjectionEvent) => Promise<void>,
): Promise<void> {
  const headers: Record<string, string> = {
    Accept: "text/event-stream",
    Authorization: `Bearer ${token}`,
  };
  if (lastEventId !== undefined) {
    headers["Last-Event-ID"] = lastEventId;
  }
  const response = await fetch(
    `/v1/scenes/${encodeURIComponent(sceneKey)}/events`,
    {
      credentials: "omit",
      headers,
      signal,
    },
  );
  if (!response.ok) {
    throw new EventStreamFailure("http", response.status);
  }
  if (
    response.body === null ||
    !response.headers.get("content-type")?.startsWith("text/event-stream")
  ) {
    throw new EventStreamFailure("content-type");
  }
  onConnected();
  for await (const event of parseCreatorEventStream(
    responseChunks(response.body, signal),
  )) {
    await onEvent(event);
  }
}

export function compareEventIds(
  previous: string,
  current: string,
): "duplicate" | "forward" | "inconsistent" {
  const previousMatch = EVENT_ID.exec(previous);
  const currentMatch = EVENT_ID.exec(current);
  if (previousMatch === null || currentMatch === null) {
    return "inconsistent";
  }
  if (previous === current) {
    return "duplicate";
  }
  if (
    previousMatch[1] !== currentMatch[1] ||
    BigInt(currentMatch[2]!) <= BigInt(previousMatch[2]!)
  ) {
    return "inconsistent";
  }
  return "forward";
}
