import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CreatorShell } from "./CreatorShell";

const TOKEN = `browser-v1.${"a".repeat(43)}`;
const ENVIRONMENT_ID = "018f47a6-7b2d-7c35-8b18-684e38ab6ef7";
const CREATOR_ID = "018f47a6-7b2d-7c35-8b18-684e38ab6ef8";
const OPPORTUNITY_ID = "018f47a6-7b2d-7c35-8b18-684e38ab6ef9";
const EFFECT_ID = "018f47a6-7b2d-7c35-8b18-684e38ab6efd";

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

function acceptedOperationProjection(): object {
  return {
    contract_version: "1.0",
    status: "accepted",
    trace_id: "a".repeat(32),
    occurred_at: "2026-07-30T10:02:00.000000Z",
    message: "The responsibility remains durably accepted.",
    result_ref: OPPORTUNITY_ID,
    custodian: "runtime",
    details: {
      projection_version: "creator-operation.v1",
      root_operation_ref: OPPORTUNITY_ID,
      completion_kind: "cognition",
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
    details: {
      projection_version: "creator-operation.v1",
      root_operation_ref: OPPORTUNITY_ID,
      completion_kind: "cognition",
    },
  };
}

function capabilityPageResponse(): object {
  return {
    contract_version: "1.0",
    projection_version: "capability-request.v4",
    items: [],
  };
}

function activityPageResponse(goal?: string): object {
  return {
    contract_version: "1.0",
    projection_version: "creator-activity.v1",
    items:
      goal === undefined
        ? []
        : [
            {
              activity_id: ENVIRONMENT_ID,
              activity_kind: "self_directed",
              status: "ready",
              goal,
              progress_summary: null,
              waiting_kind: null,
              waiting_summary: null,
              resume_not_before: null,
              terminal_reason: null,
              transition_kind: "created",
              revision_no: 1,
              head_version: 1,
              is_focused: false,
              created_at: "2026-07-30T10:00:00.000000Z",
              updated_at: "2026-07-30T10:00:00.000000Z",
            },
          ],
    truncated: false,
  };
}

function lifeRecordPageResponse(): object {
  return {
    contract_version: "1.0",
    projection_version: "life-record-query.v2",
    retrieval_kind: "creator_view",
    items: [],
    next_cursor: null,
  };
}

function memoryPageResponse(): object {
  return {
    contract_version: "1.0",
    projection_version: "creator-memory.v1",
    retrieval_kind: "creator_view",
    items: [],
    next_cursor: null,
  };
}

function relationshipCurrentResponse(): object {
  return {
    contract_version: "1.0",
    projection_version: "creator-relationship.v1",
    relationship: null,
  };
}

function promptResponse(): object {
  return {
    contract_version: "1.0",
    projection_version: "creator-prompt.v1",
    prompt_document_id: ENVIRONMENT_ID,
    prompt_kind: "creator_guidance",
    status: "active",
    current_revision_id: null,
    revision_no: null,
    previous_revision_id: null,
    revision_kind: null,
    content: null,
    content_digest: null,
    activated_at: null,
  };
}

function dataRightsResponse(): object {
  return {
    contract_version: "1.0",
    projection_version: "data-rights-order.v2",
    orders: [],
  };
}

function optionalLifeProjectionResponse(url: string): Response | undefined {
  if (url === "/v1/scenes") {
    return jsonResponse({
      contract_version: "1.0",
      projection_version: "creator-scenes.v1",
      scenes: [
        {
          contract_version: "1.0",
          projection_version: "creator-scenes.v1",
          scene_id: ENVIRONMENT_ID,
          scene_key: "default",
          status: "open",
          opened_at: "2026-07-30T09:00:00.000000Z",
          is_default: true,
        },
      ],
    });
  }
  if (url.startsWith("/v1/life-records?")) {
    return jsonResponse(lifeRecordPageResponse());
  }
  if (url.startsWith("/v1/memories?")) {
    return jsonResponse(memoryPageResponse());
  }
  if (url === "/v1/relationships/current") {
    return jsonResponse(relationshipCurrentResponse());
  }
  if (url === "/v1/prompts/creator-guidance") {
    return jsonResponse(promptResponse());
  }
  return undefined;
}

function maintenanceStatusResponse(): object {
  return {
    contract_version: "1.0",
    projection_version: "creator-maintenance.v2",
    session: null,
    waiting_input_count: 0,
  };
}

function subjectSummaryResponse(): object {
  return {
    contract_version: "1.0",
    projection_version: "subject-summary.v1",
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

describe("Creator local connection shell", () => {
  it("shows a retry state instead of a login form when Runtime is unavailable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockRejectedValue(new Error("down")),
    );
    render(<CreatorShell />);

    expect(
      await screen.findByText("当前无法连接本机 Runtime，请稍后重试。"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "重新连接" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });

  it("connects automatically, stores the local token, and reads status", async () => {
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
          projection_version: "scene-timeline.v4",
          scene_key: "default",
          items: [],
        }),
      )
      .mockResolvedValueOnce(jsonResponse(promptResponse()))
      .mockResolvedValueOnce(jsonResponse(dataRightsResponse()))
      .mockResolvedValueOnce(jsonResponse(maintenanceStatusResponse()))
      .mockResolvedValueOnce(jsonResponse(activityPageResponse()))
      .mockResolvedValueOnce(jsonResponse(lifeRecordPageResponse()))
      .mockResolvedValueOnce(jsonResponse(memoryPageResponse()))
      .mockResolvedValueOnce(jsonResponse(lifeRecordPageResponse()))
      .mockResolvedValueOnce(jsonResponse(relationshipCurrentResponse()))
      .mockResolvedValueOnce(jsonResponse(capabilityPageResponse()))
      .mockResolvedValueOnce(jsonResponse(subjectSummaryResponse()))
      .mockResolvedValueOnce(streamResponse());
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<CreatorShell />);

    expect(await screen.findByText("本机连接正常")).toBeInTheDocument();
    expect(screen.getAllByText("ready")).toHaveLength(3);
    const stored = sessionStorage.getItem("armi.browser-session.v1");
    expect(stored).toContain(TOKEN);
    expect(document.body.textContent).not.toContain(TOKEN);
    expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(3);
    expect(
      screen.getByRole("navigation", { name: "Creator 功能" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("权威版本")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "主体状态" }));
    expect(await screen.findByText("权威版本")).toBeVisible();
  });

  it("clears an invalid restored connection and retries automatically", async () => {
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
      await screen.findByText("本机连接已失效，正在重新连接。"),
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
          projection_version: "scene-timeline.v4",
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
      .mockResolvedValueOnce(jsonResponse(promptResponse()))
      .mockResolvedValueOnce(jsonResponse(dataRightsResponse()))
      .mockResolvedValueOnce(jsonResponse(maintenanceStatusResponse()))
      .mockResolvedValueOnce(jsonResponse(activityPageResponse()))
      .mockResolvedValueOnce(jsonResponse(lifeRecordPageResponse()))
      .mockResolvedValueOnce(jsonResponse(memoryPageResponse()))
      .mockResolvedValueOnce(jsonResponse(lifeRecordPageResponse()))
      .mockResolvedValueOnce(jsonResponse(relationshipCurrentResponse()))
      .mockResolvedValueOnce(jsonResponse(capabilityPageResponse()))
      .mockResolvedValueOnce(jsonResponse(subjectSummaryResponse()))
      .mockResolvedValueOnce(streamResponse())
      .mockResolvedValueOnce(
        jsonResponse({
          contract_version: "1.0",
          projection_version: "scene-timeline.v4",
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

    expect(await screen.findByText("newer.event")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "加载更早记录" }));
    expect(await screen.findByText("older.event")).toBeInTheDocument();
    expect(screen.getByText("newer.event")).toBeInTheDocument();
  });

  it("reconnects when the timeline rejects the local token", async () => {
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
    render(<CreatorShell />);

    expect(
      await screen.findByText("当前无法连接本机 Runtime，请稍后重试。"),
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
      projection_version: "scene-timeline.v4",
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
          projection_version: "scene-timeline.v4",
          scene_key: "default",
          items: [],
        }),
      )
      .mockResolvedValueOnce(jsonResponse(promptResponse()))
      .mockResolvedValueOnce(jsonResponse(dataRightsResponse()))
      .mockResolvedValueOnce(jsonResponse(maintenanceStatusResponse()))
      .mockResolvedValueOnce(jsonResponse(activityPageResponse()))
      .mockResolvedValueOnce(jsonResponse(lifeRecordPageResponse()))
      .mockResolvedValueOnce(jsonResponse(memoryPageResponse()))
      .mockResolvedValueOnce(jsonResponse(lifeRecordPageResponse()))
      .mockResolvedValueOnce(jsonResponse(relationshipCurrentResponse()))
      .mockResolvedValueOnce(jsonResponse(capabilityPageResponse()))
      .mockResolvedValueOnce(jsonResponse(subjectSummaryResponse()))
      .mockResolvedValueOnce(
        finiteStreamResponse(
          `retry: 1000\n\nid: ${eventId}\nevent: scene.timeline.invalidated\ndata: ${event}\n\n`,
        ),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          contract_version: "1.0",
          projection_version: "scene-timeline.v4",
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
    render(<CreatorShell />);

    expect(await screen.findByText("authoritative.event")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(16);
  });

  it("uses an Activity invalidation only to refetch its read projection", async () => {
    const eventId = `sse-v1.${"f".repeat(22)}.1`;
    const event = JSON.stringify({
      contract_version: "1.0",
      event_id: eventId,
      event_kind: "activity.invalidated",
      resource_kind: "activity",
      resource_ref: ENVIRONMENT_ID,
      projection_version: "creator-activity.v1",
      occurred_at: "2026-07-30T10:02:00.000000Z",
    });
    let activityReads = 0;
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      const optionalProjection = optionalLifeProjectionResponse(url);
      if (optionalProjection !== undefined) {
        return optionalProjection;
      }
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
      if (url === "/v1/activities") {
        activityReads += 1;
        return jsonResponse(
          activityPageResponse(
            activityReads === 1 ? "旧活动投影" : "新活动投影",
          ),
        );
      }
      if (url.includes("/timeline?")) {
        return jsonResponse({
          contract_version: "1.0",
          projection_version: "scene-timeline.v4",
          scene_key: "default",
          items: [],
        });
      }
      if (url.startsWith("/v1/capability-requests?")) {
        return jsonResponse(capabilityPageResponse());
      }
      if (url === "/v1/subject/summary") {
        return jsonResponse(subjectSummaryResponse());
      }
      if (url.endsWith("/events")) {
        return new Response(
          new ReadableStream<Uint8Array>({
            start(controller) {
              controller.enqueue(
                new TextEncoder().encode(
                  `retry: 1000\n\nid: ${eventId}\nevent: activity.invalidated\ndata: ${event}\n\n`,
                ),
              );
            },
          }),
          { headers: { "Content-Type": "text/event-stream; charset=utf-8" } },
        );
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<CreatorShell />);

    expect(await screen.findByText("新活动投影")).toBeInTheDocument();
    expect(screen.queryByText("旧活动投影")).toBeNull();
    expect(activityReads).toBe(2);
  });

  it("uses a maintenance invalidation to recover the current phase", async () => {
    const eventId = `sse-v1.${"g".repeat(22)}.1`;
    const event = JSON.stringify({
      contract_version: "1.0",
      event_id: eventId,
      event_kind: "maintenance.invalidated",
      resource_kind: "maintenance",
      resource_ref: ENVIRONMENT_ID,
      projection_version: "creator-maintenance.v2",
      occurred_at: "2026-07-30T10:02:00.000000Z",
    });
    let maintenanceReads = 0;
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      const optionalProjection = optionalLifeProjectionResponse(url);
      if (optionalProjection !== undefined) {
        return optionalProjection;
      }
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
      if (url.startsWith("/v1/scenes/default/timeline")) {
        return jsonResponse({
          contract_version: "1.0",
          projection_version: "scene-timeline.v4",
          scene_key: "default",
          items: [],
        });
      }
      if (url === "/v1/activities") {
        return jsonResponse(activityPageResponse());
      }
      if (url === "/v1/maintenance/status") {
        maintenanceReads += 1;
        return jsonResponse(
          maintenanceReads === 1
            ? maintenanceStatusResponse()
            : {
                contract_version: "1.0",
                projection_version: "creator-maintenance.v2",
                session: {
                  maintenance_session_id: ENVIRONMENT_ID,
                  trigger_kind: "system_deadline",
                  phase: "self_check",
                  result_status: "running",
                  revision_no: 3,
                  head_version: 3,
                  wake_requested: false,
                  started_at: "2026-07-30T09:00:00.000000Z",
                  updated_at: "2026-07-30T10:02:00.000000Z",
                  finished_at: null,
                },
                waiting_input_count: 1,
              },
        );
      }
      if (url === `/v1/maintenance/${ENVIRONMENT_ID}/timeline`) {
        return jsonResponse({
          contract_version: "1.0",
          projection_version: "creator-maintenance.v2",
          maintenance_session_id: ENVIRONMENT_ID,
          items: [],
          truncated: false,
        });
      }
      if (url.startsWith("/v1/capability-requests")) {
        return jsonResponse(capabilityPageResponse());
      }
      if (url === "/v1/subject/summary") {
        return jsonResponse(subjectSummaryResponse());
      }
      if (url === "/v1/scenes/default/events") {
        return new Response(
          new ReadableStream<Uint8Array>({
            start(controller) {
              controller.enqueue(
                new TextEncoder().encode(
                  `retry: 1000\n\nid: ${eventId}\nevent: maintenance.invalidated\ndata: ${event}\n\n`,
                ),
              );
            },
          }),
          { headers: { "Content-Type": "text/event-stream; charset=utf-8" } },
        );
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<CreatorShell />);

    expect(await screen.findByText(/正在维护 · 状态检查/)).toBeInTheDocument();
    expect(screen.getByText(/当前有 1 条输入等待处理/)).toBeInTheDocument();
    expect(maintenanceReads).toBe(2);
  });

  it("reconnects when the event stream rejects the local token", async () => {
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
          projection_version: "scene-timeline.v4",
          scene_key: "default",
          items: [],
        }),
      )
      .mockResolvedValueOnce(jsonResponse(promptResponse()))
      .mockResolvedValueOnce(jsonResponse(maintenanceStatusResponse()))
      .mockResolvedValueOnce(jsonResponse(activityPageResponse()))
      .mockResolvedValueOnce(jsonResponse(lifeRecordPageResponse()))
      .mockResolvedValueOnce(jsonResponse(memoryPageResponse()))
      .mockResolvedValueOnce(jsonResponse(lifeRecordPageResponse()))
      .mockResolvedValueOnce(jsonResponse(relationshipCurrentResponse()))
      .mockResolvedValueOnce(jsonResponse(capabilityPageResponse()))
      .mockResolvedValueOnce(jsonResponse(subjectSummaryResponse()))
      .mockResolvedValueOnce(new Response(null, { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<CreatorShell />);

    expect(
      await screen.findByText("当前无法连接本机 Runtime，请稍后重试。"),
    ).toBeInTheDocument();
    expect(sessionStorage.getItem("armi.browser-session.v1")).toBeNull();
  });

  it("accepts an input, clears its body, and verifies the operation", async () => {
    let accepted = false;
    const keys: string[] = [];
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      const optionalProjection = optionalLifeProjectionResponse(url);
      if (optionalProjection !== undefined) {
        return optionalProjection;
      }
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
      if (url === "/v1/activities") {
        return jsonResponse(activityPageResponse());
      }
      if (url.startsWith("/v1/capability-requests?")) {
        return jsonResponse(capabilityPageResponse());
      }
      if (url.includes("/timeline?")) {
        return jsonResponse({
          contract_version: "1.0",
          projection_version: "scene-timeline.v4",
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
                {
                  timeline_item_id: "018f47a6-7b2d-7c35-8b18-684e38ab6eff",
                  source_kind: "creator_response",
                  source_ref: EFFECT_ID,
                  status: "completed",
                  occurred_at: "2026-07-30T10:02:01.000000Z",
                  effect_ref: EFFECT_ID,
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
      if (url.endsWith("/codex-tasks")) {
        const headers = new Headers(init?.headers);
        keys.push(headers.get("Idempotency-Key") ?? "");
        return jsonResponse(acceptedOperation(), 202);
      }
      if (url === `/v1/operations/${OPPORTUNITY_ID}`) {
        return jsonResponse(preparedContextOperation());
      }
      if (url === `/v1/effects/${EFFECT_ID}`) {
        return jsonResponse({
          contract_version: "1.0",
          projection_version: "creator-effect.v2",
          effect_id: EFFECT_ID,
          root_operation_ref: OPPORTUNITY_ID,
          capability_request_ref: "018f47a6-7b2d-7c35-8b18-684e38ab6efb",
          grant_ref: "018f47a6-7b2d-7c35-8b18-684e38ab6efc",
          capability_kind: "creator.scene.reply",
          effect_kind: "creator_response",
          status: "completed",
          verification_status: "verified",
          registered_at: "2026-07-30T10:02:00.000000Z",
          attempt_count: 1,
          last_observation_kind: "receipt",
          last_observation_reliability: "reliable",
          settled_at: "2026-07-30T10:02:01.000000Z",
          response_text: "已核验回应",
        });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<CreatorShell />);

    const composer = await screen.findByLabelText("输入内容");
    await user.type(composer, "  保留原样\n内容  ");
    await user.click(screen.getByRole("button", { name: "提交输入" }));

    expect(await screen.findByText("消息已发送")).toBeInTheDocument();
    expect(composer).toHaveValue("");
    await user.click(await screen.findByRole("button", { name: "详情" }));
    expect(await screen.findByText(OPPORTUNITY_ID)).toBeInTheDocument();
    expect(
      await screen.findByText("Context 已准备，等待模型步骤"),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "对话" }));
    await user.click(screen.getByRole("button", { name: "记录" }));
    expect(await screen.findByText("授权依据")).toBeInTheDocument();
    expect(screen.getByText("creator.scene.reply")).toBeInTheDocument();
    expect(keys).toHaveLength(1);
    expect(keys[0]).toMatch(/^creator-input-v1\.[A-Za-z0-9_-]{22}$/);
    expect(document.body.textContent).toContain("保留原样");

    await user.click(screen.getByRole("button", { name: "对话" }));
    await user.type(composer, "生成一份明确的 Codex 交付物");
    await user.click(screen.getByRole("button", { name: "委托 Codex" }));
    expect(
      await screen.findByText(
        "Codex 委托请求已由 Runtime 耐久接纳；若 ARMI 形成正式委托，你仍须在权限区批准。",
      ),
    ).toBeInTheDocument();
    expect(keys).toHaveLength(2);
    expect(document.body.textContent).toContain("生成一份明确的 Codex 交付物");
  });

  it("retries an unconfirmed result with the exact same intent key", async () => {
    const keys: string[] = [];
    let messageAttempts = 0;
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      const optionalProjection = optionalLifeProjectionResponse(url);
      if (optionalProjection !== undefined) {
        return optionalProjection;
      }
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
      if (url === "/v1/activities") {
        return jsonResponse(activityPageResponse());
      }
      if (url.startsWith("/v1/capability-requests?")) {
        return jsonResponse(capabilityPageResponse());
      }
      if (url.includes("/timeline?")) {
        return jsonResponse({
          contract_version: "1.0",
          projection_version: "scene-timeline.v4",
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
        return jsonResponse(acceptedOperationProjection());
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<CreatorShell />);

    await user.type(await screen.findByLabelText("输入内容"), "需要确认");
    await user.click(screen.getByRole("button", { name: "提交输入" }));
    expect(await screen.findByText(/结果尚未确认/)).toBeInTheDocument();
    expect(screen.getByLabelText("输入内容")).toHaveValue("需要确认");
    await user.click(screen.getByRole("button", { name: "核验同一次输入" }));
    expect(await screen.findByText("消息已发送")).toBeInTheDocument();
    expect(keys).toHaveLength(2);
    expect(keys[1]).toBe(keys[0]);
  });
});
