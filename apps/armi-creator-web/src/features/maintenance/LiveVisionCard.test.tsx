import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LiveVisionCard } from "./LiveVisionCard";

function response(state: string): Response {
  return new Response(
    JSON.stringify({
      contract_version: "1.0",
      projection_version: "creator-live-vision-status.v1",
      state,
      enabled: true,
      expected_running: state === "observing",
      device: "USB Camera / USB\\VID_1234 / Port_#0002.Hub_#0001",
      capture_ready: state === "observing",
      perception_ready: true,
      last_frame_at: "2026-08-19T08:00:00.000000Z",
      last_observation_at: null,
      observations_last_hour: 2,
      hourly_limit: 12,
      observed_at: "2026-08-19T08:00:01.000000Z",
      reason_codes: [],
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
      <LiveVisionCard token="browser-token" onUnauthorized={() => undefined} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("live vision card", () => {
  it("shows exact-device state and the private preview boundary", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => response("observing")),
    );
    renderCard();

    expect(await screen.findByText("正在观察")).toBeInTheDocument();
    expect(screen.getByText(/USB\\VID_1234/)).toBeInTheDocument();
    expect(screen.getByText(/浏览器不会申请摄像头权限/)).toBeInTheDocument();
    expect(screen.getByText("2 / 12")).toBeInTheDocument();
  });

  it("sends explicit observe and stop controls", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response("observing"))
      .mockResolvedValue(response("observing"));
    vi.stubGlobal("fetch", fetchMock);
    renderCard();

    await userEvent.click(
      await screen.findByRole("button", { name: "立即观察" }),
    );
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/v1/vision/observe",
      expect.objectContaining({ method: "POST" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "暂停" }));
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/v1/vision/stop",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("does not request a preview without a captured frame", async () => {
    const fetchMock = vi.fn(async () => response("idle"));
    vi.stubGlobal("fetch", fetchMock);
    renderCard();

    expect(
      await screen.findByRole("button", { name: "单帧取景检查" }),
    ).toBeDisabled();
  });
});
