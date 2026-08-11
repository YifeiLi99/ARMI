import { describe, expect, it } from "vitest";

import {
  compareEventIds,
  EventStreamFailure,
  parseCreatorEventStream,
} from "./eventStream";

const EPOCH = "a".repeat(22);
const EVENT_ID = `sse-v1.${EPOCH}.1`;
const DATA = JSON.stringify({
  contract_version: "1.0",
  event_id: EVENT_ID,
  event_kind: "scene.timeline.invalidated",
  resource_kind: "scene_timeline",
  resource_ref: "default",
  projection_version: "scene-timeline.v5",
  occurred_at: "2026-07-30T10:00:00.000000Z",
});
const FRAME = `: keepalive\n\nid: ${EVENT_ID}\nevent: scene.timeline.invalidated\ndata: ${DATA}\n\n`;

async function* chunks(values: Uint8Array[]): AsyncGenerator<Uint8Array> {
  for (const value of values) {
    yield value;
  }
}

async function read(values: Uint8Array[]): Promise<string[]> {
  const found: string[] = [];
  for await (const event of parseCreatorEventStream(chunks(values))) {
    found.push(event.event_id);
  }
  return found;
}

describe("authenticated Creator event stream parser", () => {
  it.each([
    [
      "activity.invalidated",
      "activity",
      "018f47a6-7b2d-7c35-8b18-684e38ab6ef6",
      "creator-activity.v1",
    ],
    [
      "memory.invalidated",
      "memory",
      "018f47a6-7b2d-7c35-8b18-684e38ab6ef5",
      "creator-memory.v1",
    ],
    [
      "maintenance.invalidated",
      "maintenance",
      "018f47a6-7b2d-7c35-8b18-684e38ab6ef7",
      "creator-maintenance.v2",
    ],
    [
      "material.invalidated",
      "material",
      "018f47a6-7b2d-7c35-8b18-684e38ab6ef3",
      "life-record-query.v2",
    ],
    [
      "relationship.invalidated",
      "relationship",
      "018f47a6-7b2d-7c35-8b18-684e38ab6ef4",
      "creator-relationship.v1",
    ],
    [
      "scene.timeline.invalidated",
      "scene_timeline",
      "default",
      "scene-timeline.v5",
    ],
    [
      "capability.request.invalidated",
      "capability_request",
      "018f47a6-7b2d-7c35-8b18-684e38ab6ef7",
      "capability-request.v4",
    ],
    [
      "operation.invalidated",
      "operation",
      "018f47a6-7b2d-7c35-8b18-684e38ab6ef8",
      "creator-operation.v1",
    ],
    [
      "effect.invalidated",
      "effect",
      "018f47a6-7b2d-7c35-8b18-684e38ab6ef9",
      "creator-effect.v2",
    ],
    [
      "subject.summary.invalidated",
      "subject_summary",
      "018f47a6-7b2d-7c35-8b18-684e38ab6efa",
      "subject-summary.v1",
    ],
  ] as const)(
    "accepts %s only with its exact resource binding",
    async (eventKind, resourceKind, resourceRef, projectionVersion) => {
      const data = JSON.stringify({
        contract_version: "1.0",
        event_id: EVENT_ID,
        event_kind: eventKind,
        resource_kind: resourceKind,
        resource_ref: resourceRef,
        projection_version: projectionVersion,
        occurred_at: "2026-07-30T10:00:00.000000Z",
      });
      const frame = `id: ${EVENT_ID}\nevent: ${eventKind}\ndata: ${data}\n\n`;
      await expect(read([new TextEncoder().encode(frame)])).resolves.toEqual([
        EVENT_ID,
      ]);
    },
  );

  it("parses the frozen frame across every byte boundary", async () => {
    const encoded = new TextEncoder().encode(FRAME);
    for (let boundary = 0; boundary <= encoded.length; boundary += 1) {
      const result = await read([
        encoded.slice(0, boundary),
        encoded.slice(boundary),
      ]);
      expect(result).toEqual([EVENT_ID]);
    }
  });

  it("accepts CRLF and keepalive comments", async () => {
    const crlf = FRAME.replaceAll("\n", "\r\n");
    await expect(read([new TextEncoder().encode(crlf)])).resolves.toEqual([
      EVENT_ID,
    ]);
  });

  it("rejects duplicate fields, unknown fields, mismatches, and invalid UTF-8", async () => {
    const invalid = [
      `id: ${EVENT_ID}\nid: ${EVENT_ID}\nevent: scene.timeline.invalidated\ndata: ${DATA}\n\n`,
      `future: value\n\n`,
      `id: ${EVENT_ID}\nevent: other\ndata: ${DATA}\n\n`,
    ];
    for (const value of invalid) {
      await expect(
        read([new TextEncoder().encode(value)]),
      ).rejects.toBeInstanceOf(EventStreamFailure);
    }
    await expect(read([new Uint8Array([0xc3, 0x28])])).rejects.toMatchObject({
      kind: "decode",
    });
  });

  it("classifies duplicate, forward, and inconsistent event IDs", () => {
    expect(compareEventIds(EVENT_ID, EVENT_ID)).toBe("duplicate");
    expect(compareEventIds(EVENT_ID, `sse-v1.${EPOCH}.2`)).toBe("forward");
    expect(compareEventIds(`sse-v1.${EPOCH}.2`, EVENT_ID)).toBe("inconsistent");
    expect(compareEventIds(EVENT_ID, `sse-v1.${"b".repeat(22)}.2`)).toBe(
      "inconsistent",
    );
  });
});
