import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ActivityPanel } from "./ActivityPanel";

const ACTIVITY_ID = "018f47a6-7b2d-7c35-8b18-684e38ab6ef7";

function jsonResponse(value: object, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderPanel(onUnauthorized = () => undefined) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ActivityPanel
        token={`browser-v1.${"a".repeat(43)}`}
        environmentId={ACTIVITY_ID}
        creatorPartyId="018f47a6-7b2d-7c35-8b18-684e38ab6ef8"
        onUnauthorized={onUnauthorized}
      />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Creator Activity panel", () => {
  it("paginates autonomous history and distinguishes silence from delivered expression and unknown", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      if (path === "/v1/autonomy/status") {
        return jsonResponse({
          state: "blocked",
          phase: "blocked",
          idle_streak: 2,
          failure_streak: 1,
          last_engage: false,
          policy: { enabled: true, outlet: "qq" },
        });
      }
      if (path.startsWith("/v1/activities?")) {
        return jsonResponse({ items: [], next_cursor: null });
      }
      if (path.startsWith("/v1/autonomy/history?")) {
        const offset = Number(
          new URL(path, "http://localhost").searchParams.get("offset"),
        );
        return jsonResponse({
          offset,
          limit: 1,
          total: 3,
          items: [
            {
              operation_id: `${ACTIVITY_ID}-${offset}`,
              available_after: "2026-09-16T10:00:00Z",
              current_disposition: "resolved",
              resolution_reason_code: null,
              episode_id: null,
              cognition_status: "completed",
              final_disposition: "no_change",
              failure_code: null,
              effect_id: offset ? ACTIVITY_ID : null,
              effect_status:
                offset === 0 ? null : offset === 1 ? "completed" : "unknown",
            },
          ],
        });
      }
      throw new Error(`unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPanel();
    expect(await screen.findByText("自主判断等待配置修正")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "查看自主记录" }));
    expect(await screen.findByText("本轮自主沉默")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "加载更早自主记录" }));
    expect(await screen.findByText("表达交付：completed")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "加载更早自主记录" }));
    expect(await screen.findByText("发送结果未知")).toBeInTheDocument();
    expect(screen.getAllByText("本轮自主沉默")).toHaveLength(1);
    expect(
      screen.queryByRole("button", { name: "加载更早自主记录" }),
    ).toBeNull();
    expect(
      screen.getAllByRole("button", { name: "查看操作与用量" }),
    ).toHaveLength(3);
  });

  it("shows authoritative focus, waiting and terminal fields with a merged timeline", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      if (String(input) === "/v1/autonomy/status") {
        return jsonResponse({
          state: "scheduled",
          next_consideration_at: "2026-08-04T12:00:00Z",
          phase: "waiting",
          policy: { enabled: true, outlet: "qq" },
        });
      }
      if (String(input).startsWith("/v1/activities?")) {
        return jsonResponse({
          contract_version: "1.0",
          projection_version: "creator-activity.v3",
          next_cursor: null,
          items: [
            {
              activity_id: ACTIVITY_ID,
              activity_kind: "self_directed",
              status: "waiting",
              goal: "整理下一步生活安排",
              progress_summary: "已经收敛候选事项",
              waiting_kind: "creator_input",
              waiting_summary: "等待创造者补充偏好",
              resume_not_before: "2026-08-04T12:00:00.000000Z",
              terminal_reason: null,
              transition_kind: "wait",
              revision_no: 3,
              head_version: 3,
              is_focused: true,
              created_at: "2026-08-04T10:00:00.000000Z",
              updated_at: "2026-08-04T11:00:00.000000Z",
            },
          ],
        });
      }
      if (String(input).startsWith(`/v1/activities/${ACTIVITY_ID}/timeline?`)) {
        return jsonResponse({
          contract_version: "1.0",
          projection_version: "creator-activity.v3",
          activity_id: ACTIVITY_ID,
          next_cursor: null,
          items: [
            {
              event_id: "018f47a6-7b2d-7c35-8b18-684e38ab6ef9",
              event_kind: "defer",
              resulting_status: null,
              summary: "稍后再考虑",
              review_not_before: "2026-08-04T11:01:00.000000Z",
              occurred_at: "2026-08-04T11:00:30.000000Z",
            },
          ],
        });
      }
      throw new Error(`unexpected request: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderPanel();

    expect(await screen.findByText("整理下一步生活安排")).toBeInTheDocument();
    expect(screen.getByText("当前焦点")).toBeInTheDocument();
    expect(screen.getByText("等待创造者补充偏好")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "查看活动记录" }));
    expect(await screen.findByText("延后考虑")).toBeInTheDocument();
    expect(screen.getByText("稍后再考虑")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /暂停|完成|切换/ })).toBeNull();
  });

  it("shows the empty state and clears an unauthorized session", async () => {
    const onUnauthorized = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockResolvedValue(new Response(null, { status: 401 })),
    );
    renderPanel(onUnauthorized);

    expect(
      await screen.findByText("当前无法读取 Activity。"),
    ).toBeInTheDocument();
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });
});
