import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  LiveVisionStatus,
  LiveVoiceStatus,
  QQChannelHealth,
} from "../../api/client";
import { LiveVisionCard } from "./LiveVisionCard";
import { LiveVoiceCard } from "./LiveVoiceCard";
import { QQChannelHealthCard } from "./QQChannelHealthCard";

function voiceStatus(active: boolean, observedAt: string): LiveVoiceStatus {
  return {
    projection_kind: "creator-live-voice-status",
    state: active ? "listening" : "idle",
    enabled: true,
    input_device: "USB Microphone",
    output_device: "USB Speaker",
    asr_ready: true,
    llm_ready: true,
    tts_ready: true,
    recent_turn_ref: null,
    recent_turn_status: null,
    playback_extent: null,
    frames_written: null,
    last_error: null,
    observed_at: observedAt,
    reason_codes: [],
  };
}

function visionStatus(active: boolean, observedAt: string): LiveVisionStatus {
  return {
    projection_kind: "creator-live-vision-status",
    sources: [
      {
        projection_kind: "creator-live-vision-source-status",
        source_kind: "camera",
        state: active ? "observing" : "idle",
        enabled: true,
        expected_running: active,
        identity: "USB Camera",
        capture_ready: active,
        perception_ready: true,
        last_frame_at: null,
        last_observation_at: null,
        current_manual_observation_ref: null,
        observations_last_hour: 0,
        hourly_limit: 12,
        observed_at: observedAt,
        reason_codes: [],
      },
    ],
    observed_at: observedAt,
  };
}

function qqHealth(active: boolean, observedAt: string): QQChannelHealth {
  return {
    projection_kind: "creator-channel-health",
    channel: "qq",
    driver: "napcat",
    configured: true,
    enabled: active,
    state: active ? "ready" : "disabled",
    ingress_ready: active,
    api_reachable: active,
    account_online: active,
    account_matches: active,
    webui_url: null,
    observed_at: observedAt,
    reason_codes: [],
  };
}

function jsonResponse(value: object): Response {
  return new Response(JSON.stringify(value), {
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe.each([
  {
    name: "实时语音",
    Card: LiveVoiceCard,
    queryKey: ["live-voice-status"],
    snapshot: voiceStatus,
  },
  {
    name: "摄像头",
    Card: LiveVisionCard,
    queryKey: ["live-vision-status"],
    snapshot: visionStatus,
  },
  {
    name: "QQ 渠道",
    Card: QQChannelHealthCard,
    queryKey: ["qq-channel-health"],
    snapshot: qqHealth,
  },
])("$name control responses", ({ name, Card, queryKey, snapshot }) => {
  it.each([false, true])(
    "updates only its mounted card (unmounted=%s)",
    async (unmounted) => {
      let settle!: (value: Response) => void;
      const pending = new Promise<Response>((resolve) => {
        settle = resolve;
      });
      const initial = snapshot(false, "2026-08-19T08:00:00.000000Z");
      const late = snapshot(true, "2026-08-19T08:00:01.000000Z");
      const latest = snapshot(false, "2026-08-19T08:00:02.000000Z");
      let reads = 0;
      vi.stubGlobal(
        "fetch",
        vi.fn<typeof fetch>(async (_input, init) => {
          if (init?.method === "POST") return pending;
          reads += 1;
          return jsonResponse(reads === 1 ? initial : latest);
        }),
      );
      const client = new QueryClient({
        defaultOptions: {
          queries: { retry: false },
          mutations: { retry: false },
        },
      });
      const content = (
        <QueryClientProvider client={client}>
          <Card token="browser-token" onUnauthorized={vi.fn()} />
        </QueryClientProvider>
      );
      const panel = render(content);
      await waitFor(() =>
        expect(screen.getByRole("switch", { name })).toBeEnabled(),
      );
      await userEvent.click(screen.getByRole("switch", { name }));
      const mutation = client.getMutationCache().getAll()[0];
      expect(mutation?.state.status).toBe("pending");
      if (unmounted) {
        panel.unmount();
        client.clear();
        render(content);
        await waitFor(() =>
          expect(client.getQueryData(queryKey)).toEqual(latest),
        );
      }
      await act(async () => {
        settle(jsonResponse(late));
      });
      await waitFor(() => expect(mutation?.state.status).toBe("success"));
      expect(client.getQueryData(queryKey)).toEqual(unmounted ? latest : late);
      await waitFor(() =>
        expect(screen.getByRole("switch", { name })).toHaveAttribute(
          "aria-checked",
          String(!unmounted),
        ),
      );
    },
  );
});
