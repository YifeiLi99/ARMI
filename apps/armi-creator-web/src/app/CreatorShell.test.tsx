import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CreatorShell } from "./CreatorShell";

const TOKEN = `browser-v1.${"a".repeat(43)}`;
const CODE = `bootstrap-v1.${"b".repeat(22)}`;
const ENVIRONMENT_ID = "018f47a6-7b2d-7c35-8b18-684e38ab6ef7";
const CREATOR_ID = "018f47a6-7b2d-7c35-8b18-684e38ab6ef8";

function jsonResponse(value: object, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function streamResponse(): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode("retry: 1000\n\n"));
    },
  });
  return new Response(stream, {
    headers: { "Content-Type": "text/event-stream; charset=utf-8" },
  });
}

function finiteStreamResponse(value: string): Response {
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(value));
        controller.close();
      },
    }),
    { headers: { "Content-Type": "text/event-stream; charset=utf-8" } },
  );
}

function sessionResponse(includeToken: boolean): object {
  return {
    contract_version: "1.0",
    environment_id: ENVIRONMENT_ID,
    creator_party_id: CREATOR_ID,
    default_scene_key: "default",
    issued_at: "2026-07-30T10:00:00.000000Z",
    expires_at: "2026-07-30T18:00:00.000000Z",
    ...(includeToken ? { browser_session_token: TOKEN } : {}),
  };
}

afterEach(() => {
  cleanup();
  sessionStorage.clear();
  vi.unstubAllGlobals();
});

describe("Creator browser session shell", () => {
  it("starts with only the manual bootstrap form", async () => {
    render(<CreatorShell />);

    expect(
      await screen.findByRole("heading", { level: 1, name: "ARMI Creator" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Bootstrap code")).toHaveAttribute(
      "type",
      "password",
    );
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    expect(screen.queryByText(/timeline/i)).not.toBeInTheDocument();
  });

  it("exchanges a code, stores only the short session, and reads status", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(sessionResponse(true)))
      .mockResolvedValueOnce(jsonResponse(sessionResponse(false)))
      .mockResolvedValueOnce(
        jsonResponse({
          contract_version: "1.0",
          environment_id: ENVIRONMENT_ID,
          runtime_state: "ready",
          readiness: "ready",
          reason_codes: [],
          observed_at: "2026-07-30T10:00:01.000000Z",
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          contract_version: "1.0",
          projection_version: "scene-timeline.v1",
          scene_key: "default",
          items: [],
        }),
      )
      .mockResolvedValueOnce(streamResponse());
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<CreatorShell />);

    await user.type(await screen.findByLabelText("Bootstrap code"), CODE);
    await user.click(screen.getByRole("button", { name: "建立浏览器会话" }));

    expect(await screen.findByText("浏览器会话已建立")).toBeInTheDocument();
    expect(screen.getAllByText("ready")).toHaveLength(2);
    const stored = sessionStorage.getItem("armi.browser-session.v1");
    expect(stored).toContain(TOKEN);
    expect(stored).not.toContain(CODE);
    expect(document.body.textContent).not.toContain(TOKEN);
    expect(screen.getByText("尚无耐久可见记录")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(5);
  });

  it("clears an invalid restored session after a 401", async () => {
    sessionStorage.setItem(
      "armi.browser-session.v1",
      JSON.stringify({
        token: TOKEN,
        expiresAt: "2026-07-30T18:00:00.000000Z",
        environmentId: ENVIRONMENT_ID,
      }),
    );
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockResolvedValue(new Response(null, { status: 401 })),
    );
    render(<CreatorShell />);

    expect(
      await screen.findByText("会话已失效，请使用新的 bootstrap code。"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(sessionStorage.getItem("armi.browser-session.v1")).toBeNull(),
    );
  });

  it("retains the restored session when the Runtime is temporarily unreachable", async () => {
    sessionStorage.setItem(
      "armi.browser-session.v1",
      JSON.stringify({
        token: TOKEN,
        expiresAt: "2026-07-30T18:00:00.000000Z",
        environmentId: ENVIRONMENT_ID,
      }),
    );
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockRejectedValue(new TypeError("network")),
    );
    render(<CreatorShell />);

    expect(
      await screen.findByText("当前无法连接本机 Runtime，请稍后重试。"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "重新连接" }),
    ).toBeInTheDocument();
    expect(sessionStorage.getItem("armi.browser-session.v1")).toContain(TOKEN);
    expect(
      screen.queryByRole("button", { name: "建立浏览器会话" }),
    ).not.toBeInTheDocument();
  });

  it("loads older authoritative pages without inventing timeline content", async () => {
    const cursor = `v1.${"c".repeat(32)}.${"d".repeat(43)}`;
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(sessionResponse(true)))
      .mockResolvedValueOnce(jsonResponse(sessionResponse(false)))
      .mockResolvedValueOnce(
        jsonResponse({
          contract_version: "1.0",
          environment_id: ENVIRONMENT_ID,
          runtime_state: "ready",
          readiness: "ready",
          reason_codes: [],
          observed_at: "2026-07-30T10:00:01.000000Z",
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          contract_version: "1.0",
          projection_version: "scene-timeline.v1",
          scene_key: "default",
          items: [
            {
              timeline_item_id: "018f47a6-7b2d-7c35-8b18-684e38ab6efa",
              source_kind: "newer.event",
              source_ref: "018f47a6-7b2d-7c35-8b18-684e38ab6efb",
              status: "completed",
              occurred_at: "2026-07-30T10:01:00.000000Z",
            },
          ],
          next_cursor: cursor,
        }),
      )
      .mockResolvedValueOnce(streamResponse())
      .mockResolvedValueOnce(
        jsonResponse({
          contract_version: "1.0",
          projection_version: "scene-timeline.v1",
          scene_key: "default",
          items: [
            {
              timeline_item_id: "018f47a6-7b2d-7c35-8b18-684e38ab6ef9",
              source_kind: "older.event",
              source_ref: "018f47a6-7b2d-7c35-8b18-684e38ab6ef8",
              status: "accepted",
              occurred_at: "2026-07-30T10:00:00.000000Z",
            },
          ],
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<CreatorShell />);

    await user.type(await screen.findByLabelText("Bootstrap code"), CODE);
    await user.click(screen.getByRole("button", { name: "建立浏览器会话" }));
    expect(await screen.findByText("newer.event")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "加载更早记录" }));
    expect(await screen.findByText("older.event")).toBeInTheDocument();
    expect(screen.getByText("newer.event")).toBeInTheDocument();
  });

  it("clears the whole session when the timeline rejects authentication", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(sessionResponse(true)))
      .mockResolvedValueOnce(jsonResponse(sessionResponse(false)))
      .mockResolvedValueOnce(
        jsonResponse({
          contract_version: "1.0",
          environment_id: ENVIRONMENT_ID,
          runtime_state: "ready",
          readiness: "ready",
          reason_codes: [],
          observed_at: "2026-07-30T10:00:01.000000Z",
        }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<CreatorShell />);

    await user.type(await screen.findByLabelText("Bootstrap code"), CODE);
    await user.click(screen.getByRole("button", { name: "建立浏览器会话" }));
    expect(
      await screen.findByText("会话已失效，请使用新的 bootstrap code。"),
    ).toBeInTheDocument();
    expect(sessionStorage.getItem("armi.browser-session.v1")).toBeNull();
  });

  it("uses an invalidation only to refetch the authoritative timeline", async () => {
    const eventId = `sse-v1.${"e".repeat(22)}.1`;
    const event = JSON.stringify({
      contract_version: "1.0",
      event_id: eventId,
      event_kind: "scene.timeline.invalidated",
      resource_kind: "scene_timeline",
      resource_ref: "default",
      projection_version: "scene-timeline.v1",
      occurred_at: "2026-07-30T10:02:00.000000Z",
    });
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(sessionResponse(true)))
      .mockResolvedValueOnce(jsonResponse(sessionResponse(false)))
      .mockResolvedValueOnce(
        jsonResponse({
          contract_version: "1.0",
          environment_id: ENVIRONMENT_ID,
          runtime_state: "ready",
          readiness: "ready",
          reason_codes: [],
          observed_at: "2026-07-30T10:00:01.000000Z",
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          contract_version: "1.0",
          projection_version: "scene-timeline.v1",
          scene_key: "default",
          items: [],
        }),
      )
      .mockResolvedValueOnce(
        finiteStreamResponse(
          `retry: 1000\n\nid: ${eventId}\nevent: scene.timeline.invalidated\ndata: ${event}\n\n`,
        ),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          contract_version: "1.0",
          projection_version: "scene-timeline.v1",
          scene_key: "default",
          items: [
            {
              timeline_item_id: "018f47a6-7b2d-7c35-8b18-684e38ab6efa",
              source_kind: "authoritative.event",
              source_ref: "018f47a6-7b2d-7c35-8b18-684e38ab6efb",
              status: "completed",
              occurred_at: "2026-07-30T10:02:00.000000Z",
            },
          ],
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<CreatorShell />);

    await user.type(await screen.findByLabelText("Bootstrap code"), CODE);
    await user.click(screen.getByRole("button", { name: "建立浏览器会话" }));

    expect(await screen.findByText("authoritative.event")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(6);
  });

  it("clears session state when the authenticated stream returns 401", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(sessionResponse(true)))
      .mockResolvedValueOnce(jsonResponse(sessionResponse(false)))
      .mockResolvedValueOnce(
        jsonResponse({
          contract_version: "1.0",
          environment_id: ENVIRONMENT_ID,
          runtime_state: "ready",
          readiness: "ready",
          reason_codes: [],
          observed_at: "2026-07-30T10:00:01.000000Z",
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          contract_version: "1.0",
          projection_version: "scene-timeline.v1",
          scene_key: "default",
          items: [],
        }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<CreatorShell />);

    await user.type(await screen.findByLabelText("Bootstrap code"), CODE);
    await user.click(screen.getByRole("button", { name: "建立浏览器会话" }));

    expect(
      await screen.findByText("会话已失效，请使用新的 bootstrap code。"),
    ).toBeInTheDocument();
    expect(sessionStorage.getItem("armi.browser-session.v1")).toBeNull();
  });
});
