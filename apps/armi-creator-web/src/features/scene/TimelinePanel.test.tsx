import "@testing-library/jest-dom/vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
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
