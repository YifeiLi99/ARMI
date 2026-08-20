import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LiveVoiceCard } from "./LiveVoiceCard";

function response(state: string, reasons: string[] = []): Response {
  return new Response(
    JSON.stringify({
      contract_version: "1.0",
      projection_version: "live-voice-status.v1",
      state,
      enabled: true,
      input_device: "Windows WASAPI / USB Audio",
      output_device: "Windows WASAPI / USB Audio",
      asr_ready: state === "idle",
      llm_ready: state === "idle",
      tts_ready: state === "idle",
      observed_at: "2026-08-19T08:00:00.000000Z",
      reason_codes: reasons,
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

function renderCard(): void {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <LiveVoiceCard token="browser-token" onUnauthorized={() => undefined} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("live voice card", () => {
  it("shows the exact host devices and keeps browser microphone out of scope", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => response("idle")),
    );
    renderCard();

    expect(await screen.findByText("已停止")).toBeInTheDocument();
    expect(screen.getAllByText("Windows WASAPI / USB Audio")).toHaveLength(2);
    expect(screen.getByText(/浏览器麦克风权限保持关闭/)).toBeInTheDocument();
  });

  it("does not enable start while the pipeline is unavailable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        response("unavailable", ["VOICE_PIPELINE_UNAVAILABLE"]),
      ),
    );
    renderCard();

    expect(
      await screen.findByText("实时语音配置或凭据当前不可用。"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始语音" })).toBeDisabled();
  });

  it("sends an explicit start request", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response("idle"))
      .mockResolvedValueOnce(response("listening"));
    vi.stubGlobal("fetch", fetchMock);
    renderCard();

    await userEvent.click(
      await screen.findByRole("button", { name: "开始语音" }),
    );
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/v1/voice/start",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
