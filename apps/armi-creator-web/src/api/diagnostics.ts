import { loadStoredSession } from "../features/session/storage";
import { sendClientDiagnostics } from "./client";

type TechnicalEvent = {
  event:
    | "unhandled_error"
    | "unhandled_rejection"
    | "request_failed"
    | "buffer_status";
  message: string;
  location?: string;
  http_status?: number;
  dropped?: number;
  rejected?: number;
};

const limit = 1024 * 1024;
const queue: TechnicalEvent[] = [];
let bytes = 0;
let dropped = 0;
let rejected = 0;
let sending = false;

// Keep only technical metadata in memory. Error objects, request bodies and headers
// can contain private conversation data and are never serialized into this queue.
export function reportDiagnostic(event: TechnicalEvent): void {
  const size = new TextEncoder().encode(JSON.stringify(event)).length;
  if (size > limit || bytes + size > limit) {
    dropped += 1;
    return;
  }
  queue.push(event);
  bytes += size;
}

export async function flushDiagnostics(): Promise<void> {
  const session = loadStoredSession();
  if (
    sending ||
    session === null ||
    (queue.length === 0 && !dropped && !rejected)
  )
    return;
  sending = true;
  const batch = queue.slice(0, 19);
  const counters = { dropped, rejected };
  const events = [...batch];
  if (counters.dropped || counters.rejected) {
    events.push({
      event: "buffer_status",
      message: "Client diagnostic buffer counters",
      ...counters,
    });
  }
  try {
    const response = await sendClientDiagnostics(session.token, events);
    if (response.ok) {
      queue.splice(0, batch.length);
      bytes = queue.reduce(
        (total, event) =>
          total + new TextEncoder().encode(JSON.stringify(event)).length,
        0,
      );
      dropped -= counters.dropped;
      rejected -= counters.rejected;
    } else {
      rejected += events.length;
    }
  } catch {
    // Transport is offline; retain the bounded technical queue until next flush.
  } finally {
    sending = false;
  }
}

export function installDiagnostics(): void {
  window.addEventListener("error", (event) => {
    let file = "unknown";
    try {
      file =
        new URL(event.filename, window.location.href).pathname
          .split("/")
          .at(-1) ?? "unknown";
    } catch {
      /* No location supplied. */
    }
    reportDiagnostic({
      event: "unhandled_error",
      message: "Unhandled browser error",
      location: `${file}:${event.lineno}:${event.colno}`,
    });
  });
  window.addEventListener("unhandledrejection", () => {
    reportDiagnostic({
      event: "unhandled_rejection",
      message: "Unhandled Promise rejection",
    });
  });
  window.addEventListener("online", () => {
    void flushDiagnostics();
  });
  window.setInterval(() => {
    void flushDiagnostics();
  }, 5000);
}
