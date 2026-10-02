import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LiveVisionCard } from "./LiveVisionCard";

function response(state: string): Response {
  return new Response(
    JSON.stringify({
      projection_kind: "creator-live-vision-status",
      sources: [
        {
          projection_kind: "creator-live-vision-source-status",
          source_kind: "camera",
          state,
          enabled: true,
          expected_running: state === "observing",
          identity: "USB Camera / USB\\VID_1234 / Port_#0002.Hub_#0001",
          capture_ready: state === "observing",
          perception_ready: true,
          last_frame_at: "2026-08-19T08:00:00.000000Z",
          last_observation_at: null,
          current_manual_observation_ref: null,
          observations_last_hour: 2,
          hourly_limit: 12,
          observed_at: "2026-08-19T08:00:01.000000Z",
          reason_codes: [],
        },
      ],
      observed_at: "2026-08-19T08:00:01.000000Z",
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

function observationResponse(): Response {
  return new Response(
    JSON.stringify({
      projection_kind: "creator-live-vision-observation",
      observation_id: "018f47a6-7b2d-7c35-8b18-684e38ab6ef7",
      source_kind: "camera",
      origin_kind: "creator",
      trigger: "manual",
      status: "capture_pending",
      registered_at: "2026-08-19T08:00:01.000000Z",
      change_score: null,
      summary: null,
      error_code: null,
    }),
    { status: 202, headers: { "Content-Type": "application/json" } },
  );
}

function renderCard(strict = false) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const content = (
    <QueryClientProvider client={client}>
      <LiveVisionCard token="browser-token" onUnauthorized={() => undefined} />
    </QueryClientProvider>
  );
  return render(strict ? <StrictMode>{content}</StrictMode> : content);
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
    expect(screen.getByText(/预览只读取 Runtime 内存/)).toBeInTheDocument();
    expect(screen.getByText("2 / 12")).toBeInTheDocument();
  });

  it("sends explicit observe and stop controls", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response("observing"))
      .mockResolvedValueOnce(observationResponse())
      .mockResolvedValue(response("observing"));
    vi.stubGlobal("fetch", fetchMock);
    renderCard();

    await userEvent.click(
      await screen.findByRole("button", { name: "立即观察" }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/v1/vision/observe",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "Idempotency-Key": expect.any(String),
        }),
        body: JSON.stringify({
          source_kind: "camera",
        }),
      }),
    );
    await userEvent.click(screen.getByRole("switch", { name: "摄像头" }));
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/v1/vision/sources/camera/stop",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("does not request a preview without a captured frame", async () => {
    const fetchMock = vi.fn(async () => response("idle"));
    vi.stubGlobal("fetch", fetchMock);
    renderCard();

    expect(await screen.findByRole("button", { name: "预览" })).toBeDisabled();
  });

  it("retains only the displayed preview URL in StrictMode and releases it on unmount", async () => {
    const active = new Set<string>();
    let sequence = 0;
    class PreviewURL extends URL {
      static override createObjectURL = vi.fn(() => {
        const url = `blob:preview-${++sequence}`;
        active.add(url);
        return url;
      });
      static override revokeObjectURL = vi.fn((url: string) => {
        active.delete(url);
      });
    }
    vi.stubGlobal("URL", PreviewURL);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) =>
        String(input).includes("/preview")
          ? new Response("preview", {
              headers: { "Content-Type": "image/png" },
            })
          : response("observing"),
      ),
    );
    const view = renderCard(true);
    const button = await screen.findByRole("button", { name: "预览" });
    await userEvent.click(button);
    const first = await screen.findByRole("img", { name: "摄像头当前帧预览" });
    const firstUrl = first.getAttribute("src");
    await userEvent.click(button);
    await screen.findByRole("img", { name: "摄像头当前帧预览" });
    const currentUrl = screen.getByRole("img").getAttribute("src");
    expect(currentUrl).not.toBe(firstUrl);
    expect(active).toEqual(new Set([currentUrl]));
    view.unmount();
    expect(active.size).toBe(0);
  });

  it("does not create a preview URL for a response received after unmount", async () => {
    const create = vi.fn(() => "blob:preview");
    class PreviewURL extends URL {
      static override createObjectURL = create;
      static override revokeObjectURL = vi.fn();
    }
    vi.stubGlobal("URL", PreviewURL);
    let resolvePreview!: (value: Response) => void;
    const pending = new Promise<Response>((resolve) => {
      resolvePreview = resolve;
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) =>
        String(input).includes("/preview") ? pending : response("observing"),
      ),
    );
    const view = renderCard(true);
    await userEvent.click(await screen.findByRole("button", { name: "预览" }));
    view.unmount();
    await act(async () => {
      resolvePreview(
        new Response("preview", { headers: { "Content-Type": "image/png" } }),
      );
    });
    expect(create).not.toHaveBeenCalled();
  });
});
