import "@testing-library/jest-dom/vitest";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";

import type { SceneTimelinePage } from "../../api/client";
import { TimelinePanel } from "./TimelinePanel";

const EFFECT_ID = "018f47a6-7b2d-7c35-8b18-684e38ab6ef7";
const ITEM_ID = "018f47a6-7b2d-7c35-8b18-684e38ab6ef8";
const OCCURRED_AT = "2026-07-30T10:00:00.000000Z";
const NOOP = () => undefined;

function jsonResponse(value: object, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function timeline(item: SceneTimelinePage["items"][number]): SceneTimelinePage {
  return {
    projection_kind: "scene-timeline",
    scene_key: "default",
    items: [item],
    next_cursor: null,
  };
}

function showTimeline() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <TimelinePanel
        token={`browser-v1.${"a".repeat(43)}`}
        environmentId={EFFECT_ID}
        creatorPartyId={ITEM_ID}
        sceneKey="default"
        onUnauthorized={NOOP}
        onOperationSelected={NOOP}
        onEffectSelected={NOOP}
        registerStreamAbort={NOOP}
      />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it.each(["语音回复的完整正文", null])(
  "shows the authoritative voice reply or its unavailable state without fetching an effect",
  async (message) => {
    const page = timeline({
      timeline_item_id: ITEM_ID,
      source_kind: "creator_response",
      source_ref: EFFECT_ID,
      status: "completed",
      occurred_at: OCCURRED_AT,
      modality: "live_voice",
      message,
    });
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.startsWith("/v1/scenes/default/timeline?")) {
        return jsonResponse(page);
      }
      if (url === "/v1/scenes/default/events") {
        return new Response(new ReadableStream<Uint8Array>(), {
          headers: { "Content-Type": "text/event-stream" },
        });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    showTimeline();

    expect(
      await screen.findByText(message ?? "回复暂时不可见"),
    ).toBeInTheDocument();
    expect(screen.queryByText("正在组织回复…")).not.toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).startsWith("/v1/effects/"),
      ),
    ).toBe(false);
  },
);

it("refreshes a reply after effect invalidation when its first read failed", async () => {
  const page = timeline({
    timeline_item_id: ITEM_ID,
    source_kind: "creator_response",
    source_ref: EFFECT_ID,
    effect_ref: EFFECT_ID,
    status: "completed",
    occurred_at: OCCURRED_AT,
    modality: "text",
  });
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  let effectReads = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.startsWith("/v1/scenes/default/timeline?")) {
        return jsonResponse(page);
      }
      if (url === "/v1/scenes/default/events") {
        return new Response(
          new ReadableStream<Uint8Array>({
            start(value) {
              controller = value;
            },
          }),
          { headers: { "Content-Type": "text/event-stream" } },
        );
      }
      if (url === `/v1/effects/${EFFECT_ID}`) {
        effectReads += 1;
        if (effectReads === 1) {
          return jsonResponse(
            { error_code: "EFFECT-PAYLOAD-UNAVAILABLE" },
            503,
          );
        }
        return jsonResponse({
          projection_kind: "creator-effect",
          effect_id: EFFECT_ID,
          action_intent_ref: ITEM_ID,
          capability_kind: "creator.scene.reply",
          effect_kind: "creator_response",
          status: "completed",
          verification_status: "verified",
          registered_at: OCCURRED_AT,
          attempt_count: 1,
          response_text: "已核验的文字回复",
        });
      }
      throw new Error(`unexpected request: ${url}`);
    }),
  );
  showTimeline();
  expect(await screen.findByText("回复暂时不可见")).toBeInTheDocument();
  const eventId = `sse-v1.${"b".repeat(22)}.1`;
  await act(async () => {
    controller.enqueue(
      new TextEncoder().encode(
        `id: ${eventId}\nevent: effect.invalidated\ndata: ${JSON.stringify({
          event_id: eventId,
          event_kind: "effect.invalidated",
          resource_kind: "effect",
          resource_ref: EFFECT_ID,
          projection_kind: "creator-effect",
          occurred_at: OCCURRED_AT,
        })}\n\n`,
      ),
    );
  });
  expect(await screen.findByText("已核验的文字回复")).toBeInTheDocument();
  expect(effectReads).toBe(2);
});

it("keeps the shared notification stream alive after another scene changes", async () => {
  let timelineReads = 0;
  const frames = ["night-talk", "default"]
    .map((sceneKey, index) => {
      const eventId = `sse-v1.${"c".repeat(22)}.${index + 1}`;
      return `id: ${eventId}\nevent: scene.timeline.invalidated\ndata: ${JSON.stringify(
        {
          event_id: eventId,
          event_kind: "scene.timeline.invalidated",
          resource_kind: "scene_timeline",
          resource_ref: sceneKey,
          projection_kind: "scene-timeline",
          occurred_at: OCCURRED_AT,
        },
      )}\n\n`;
    })
    .join("");
  const fetchMock = vi.fn<typeof fetch>(async (input) => {
    const url = String(input);
    if (url.startsWith("/v1/scenes/default/timeline?")) {
      timelineReads += 1;
      return jsonResponse(
        timelineReads === 1
          ? {
              projection_kind: "scene-timeline",
              scene_key: "default",
              items: [],
              next_cursor: null,
            }
          : timeline({
              timeline_item_id: ITEM_ID,
              source_kind: "creator_response",
              source_ref: EFFECT_ID,
              status: "completed",
              occurred_at: OCCURRED_AT,
              modality: "live_voice",
              message: "当前场合的新回复",
            }),
      );
    }
    if (url === "/v1/scenes/default/events") {
      return new Response(
        new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(new TextEncoder().encode(frames));
          },
        }),
        { headers: { "Content-Type": "text/event-stream" } },
      );
    }
    throw new Error(`unexpected request: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  showTimeline();

  expect(await screen.findByText("当前场合的新回复")).toBeInTheDocument();
  expect(screen.getByText("实时")).toBeInTheDocument();
  expect(timelineReads).toBe(2);
  expect(fetchMock).toHaveBeenCalledTimes(3);
});

it("does not restart a rejected stream while its fallback refresh reloads the timeline", async () => {
  const page = {
    projection_kind: "scene-timeline",
    scene_key: "default",
    items: [],
    next_cursor: null,
  };
  let timelineReads = 0;
  let streamReads = 0;
  let finishRefresh!: (response: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.startsWith("/v1/scenes/default/timeline?")) {
        timelineReads += 1;
        if (timelineReads === 2) {
          return new Promise<Response>((resolve) => {
            finishRefresh = resolve;
          });
        }
        return jsonResponse(page);
      }
      if (url === "/v1/scenes/default/events") {
        streamReads += 1;
        return streamReads === 1
          ? jsonResponse({ error: "unsupported stream" })
          : new Response(new ReadableStream<Uint8Array>(), {
              headers: { "Content-Type": "text/event-stream" },
            });
      }
      throw new Error(`unexpected request: ${url}`);
    }),
  );
  showTimeline();
  await screen.findByText("正在读取对话…");
  // Wait for the fallback GET, so its pending state has reached the real panel.
  await waitFor(() => expect(timelineReads).toBe(2));
  await act(async () => finishRefresh(jsonResponse(page)));
  await screen.findByText("开始和 ARMI 对话");

  expect(timelineReads).toBe(2);
  expect(streamReads).toBe(1);
  expect(screen.getByText("定时刷新")).toBeInTheDocument();
});

it("reconnects after the established stream loses its network response", async () => {
  let streamReads = 0;
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.startsWith("/v1/scenes/default/timeline?")) {
        return jsonResponse({
          projection_kind: "scene-timeline",
          scene_key: "default",
          items: [],
          next_cursor: null,
        });
      }
      if (url === "/v1/scenes/default/events") {
        streamReads += 1;
        return new Response(
          new ReadableStream<Uint8Array>({
            start(value) {
              controller = value;
            },
          }),
          { headers: { "Content-Type": "text/event-stream" } },
        );
      }
      throw new Error(`unexpected request: ${url}`);
    }),
  );
  showTimeline();
  await screen.findByText("实时");
  vi.useFakeTimers();
  await act(async () => {
    controller.error(new TypeError("network response interrupted"));
    await vi.advanceTimersByTimeAsync(0);
  });
  expect(streamReads).toBe(1);

  await act(async () => vi.advanceTimersByTimeAsync(1000));
  expect(streamReads).toBe(2);
  expect(screen.getByText("实时")).toBeInTheDocument();
});

it("waits for a successful initial timeline read before starting its stream", async () => {
  const fetchMock = vi.fn<typeof fetch>(async () =>
    jsonResponse({ status: "unavailable" }, 503),
  );
  vi.stubGlobal("fetch", fetchMock);
  showTimeline();
  await screen.findByText("当前无法读取对话。");
  expect(fetchMock).toHaveBeenCalledOnce();
  expect(String(fetchMock.mock.calls[0]![0])).toMatch(
    /^\/v1\/scenes\/default\/timeline\?/,
  );
});
