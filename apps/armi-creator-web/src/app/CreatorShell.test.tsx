import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CreatorShell } from "./CreatorShell";

const TOKEN = `browser-v1.${"a".repeat(43)}`;
const CODE = `bootstrap-v1.${"b".repeat(22)}`;
const ENVIRONMENT_ID = "018f47a6-7b2d-7c35-8b18-684e38ab6ef7";
const CREATOR_ID = "018f47a6-7b2d-7c35-8b18-684e38ab6ef8";
const OPPORTUNITY_ID = "018f47a6-7b2d-7c35-8b18-684e38ab6ef9";

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

function acceptedOperation(): object {
  return {
    contract_version: "1.0",
    status: "accepted",
    trace_id: "a".repeat(32),
    occurred_at: "2026-07-30T10:02:00.000000Z",
    message: "The Creator input is durably accepted.",
    result_ref: OPPORTUNITY_ID,
    custodian: "runtime",
    details: {
      interaction_id: "018f47a6-7b2d-7c35-8b18-684e38ab6efa",
      evidence_id: "018f47a6-7b2d-7c35-8b18-684e38ab6efb",
      opportunity_id: OPPORTUNITY_ID,
      operation_url: `/v1/operations/${OPPORTUNITY_ID}`,
    },
  };
}

function preparedContextOperation(): object {
  return {
    contract_version: "1.0",
    status: "waiting",
    trace_id: "b".repeat(32),
    occurred_at: "2026-07-30T10:02:01.000000Z",
    message: "The prepared Context is waiting for a model attempt.",
    result_ref: OPPORTUNITY_ID,
    waiting_for: "model_attempt",
    resume_condition: "model_step_available",
  };
}

function subjectSummaryResponse(): object {
  return {
    contract_version: "1.0",
    subject_version: 0,
    components: [
      {
        kind: "self",
        version: 1,
        schema_version: "armi.self.v1",
        content_visibility: "private",
      },
      {
        kind: "mind",
        version: 1,
        schema_version: "armi.mind.v1",
        content_visibility: "private",
      },
      {
        kind: "life_mode",
        version: 1,
        schema_version: "armi.life-mode.v1",
        content_visibility: "private",
      },
    ],
    latest_commit_ref: null,
    observed_at: "2026-07-30T10:00:01.000000Z",
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
          projection_version: "scene-timeline.v3",
          scene_key: "default",
          items: [],
        }),
      )
      .mockResolvedValueOnce(jsonResponse(subjectSummaryResponse()))
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
    expect(fetchMock).toHaveBeenCalledTimes(6);
    expect(screen.getByText("权威版本")).toBeInTheDocument();
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
          projection_version: "scene-timeline.v3",
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
      .mockResolvedValueOnce(jsonResponse(subjectSummaryResponse()))
      .mockResolvedValueOnce(streamResponse())
      .mockResolvedValueOnce(
        jsonResponse({
          contract_version: "1.0",
          projection_version: "scene-timeline.v3",
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
      projection_version: "scene-timeline.v3",
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
          projection_version: "scene-timeline.v3",
          scene_key: "default",
          items: [],
        }),
      )
      .mockResolvedValueOnce(jsonResponse(subjectSummaryResponse()))
      .mockResolvedValueOnce(
        finiteStreamResponse(
          `retry: 1000\n\nid: ${eventId}\nevent: scene.timeline.invalidated\ndata: ${event}\n\n`,
        ),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          contract_version: "1.0",
          projection_version: "scene-timeline.v3",
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
      )
      .mockResolvedValueOnce(jsonResponse(subjectSummaryResponse()));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<CreatorShell />);

    await user.type(await screen.findByLabelText("Bootstrap code"), CODE);
    await user.click(screen.getByRole("button", { name: "建立浏览器会话" }));

    expect(await screen.findByText("authoritative.event")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(8);
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
          projection_version: "scene-timeline.v3",
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

  it("accepts an input, clears its body, and verifies the operation", async () => {
    let accepted = false;
    const keys: string[] = [];
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/v1/browser-sessions" && init?.method === "POST") {
        return jsonResponse(sessionResponse(true));
      }
      if (url === "/v1/browser-sessions/current") {
        return jsonResponse(sessionResponse(false));
      }
      if (url === "/v1/runtime/status") {
        return jsonResponse({
          contract_version: "1.0",
          environment_id: ENVIRONMENT_ID,
          runtime_state: "ready",
          readiness: "ready",
          reason_codes: [],
          observed_at: "2026-07-30T10:00:01.000000Z",
        });
      }
      if (url === "/v1/subject/summary") {
        return jsonResponse(subjectSummaryResponse());
      }
      if (url.includes("/timeline?")) {
        return jsonResponse({
          contract_version: "1.0",
          projection_version: "scene-timeline.v3",
          scene_key: "default",
          items: accepted
            ? [
                {
                  timeline_item_id: "018f47a6-7b2d-7c35-8b18-684e38ab6efc",
                  source_kind: "creator_input",
                  source_ref: "018f47a6-7b2d-7c35-8b18-684e38ab6efa",
                  status: "accepted",
                  occurred_at: "2026-07-30T10:02:00.000000Z",
                  operation_ref: OPPORTUNITY_ID,
                },
              ]
            : [],
        });
      }
      if (url.endsWith("/events")) {
        return streamResponse();
      }
      if (url.endsWith("/messages")) {
        const headers = new Headers(init?.headers);
        keys.push(headers.get("Idempotency-Key") ?? "");
        accepted = true;
        return jsonResponse(acceptedOperation(), 202);
      }
      if (url === `/v1/operations/${OPPORTUNITY_ID}`) {
        return jsonResponse(preparedContextOperation());
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<CreatorShell />);

    await user.type(await screen.findByLabelText("Bootstrap code"), CODE);
    await user.click(screen.getByRole("button", { name: "建立浏览器会话" }));
    const composer = await screen.findByLabelText("输入内容");
    await user.type(composer, "  保留原样\n内容  ");
    await user.click(screen.getByRole("button", { name: "提交输入" }));

    expect(
      await screen.findByText("输入已由 Runtime 耐久接纳，可在下方核验责任。"),
    ).toBeInTheDocument();
    expect(composer).toHaveValue("");
    expect(await screen.findByText(OPPORTUNITY_ID)).toBeInTheDocument();
    expect(
      await screen.findByText("Context 已准备，等待模型步骤"),
    ).toBeInTheDocument();
    expect(keys).toHaveLength(1);
    expect(keys[0]).toMatch(/^creator-input-v1\.[A-Za-z0-9_-]{22}$/);
    expect(document.body.textContent).not.toContain("保留原样");
  });

  it("retries an unconfirmed result with the exact same intent key", async () => {
    const keys: string[] = [];
    let messageAttempts = 0;
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/v1/browser-sessions" && init?.method === "POST") {
        return jsonResponse(sessionResponse(true));
      }
      if (url === "/v1/browser-sessions/current") {
        return jsonResponse(sessionResponse(false));
      }
      if (url === "/v1/runtime/status") {
        return jsonResponse({
          contract_version: "1.0",
          environment_id: ENVIRONMENT_ID,
          runtime_state: "ready",
          readiness: "ready",
          reason_codes: [],
          observed_at: "2026-07-30T10:00:01.000000Z",
        });
      }
      if (url === "/v1/subject/summary") {
        return jsonResponse(subjectSummaryResponse());
      }
      if (url.includes("/timeline?")) {
        return jsonResponse({
          contract_version: "1.0",
          projection_version: "scene-timeline.v3",
          scene_key: "default",
          items: [],
        });
      }
      if (url.endsWith("/events")) {
        return streamResponse();
      }
      if (url.endsWith("/messages")) {
        keys.push(new Headers(init?.headers).get("Idempotency-Key") ?? "");
        messageAttempts += 1;
        if (messageAttempts === 1) {
          throw new TypeError("connection interrupted");
        }
        return jsonResponse(acceptedOperation(), 202);
      }
      if (url === `/v1/operations/${OPPORTUNITY_ID}`) {
        return jsonResponse(acceptedOperation());
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<CreatorShell />);

    await user.type(await screen.findByLabelText("Bootstrap code"), CODE);
    await user.click(screen.getByRole("button", { name: "建立浏览器会话" }));
    await user.type(await screen.findByLabelText("输入内容"), "需要确认");
    await user.click(screen.getByRole("button", { name: "提交输入" }));
    expect(await screen.findByText(/结果尚未确认/)).toBeInTheDocument();
    expect(screen.getByLabelText("输入内容")).toHaveValue("需要确认");
    await user.click(screen.getByRole("button", { name: "核验同一次输入" }));
    expect(
      await screen.findByText(/输入已由 Runtime 耐久接纳/),
    ).toBeInTheDocument();
    expect(keys).toHaveLength(2);
    expect(keys[1]).toBe(keys[0]);
  });
});
