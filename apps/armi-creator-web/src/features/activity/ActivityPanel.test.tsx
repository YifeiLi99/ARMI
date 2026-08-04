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
  it("shows authoritative focus, waiting and terminal fields with a merged timeline", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      if (String(input) === "/v1/activities") {
        return jsonResponse({
          contract_version: "1.0",
          projection_version: "creator-activity.v1",
          truncated: false,
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
      if (String(input) === `/v1/activities/${ACTIVITY_ID}/timeline`) {
        return jsonResponse({
          contract_version: "1.0",
          projection_version: "creator-activity.v1",
          activity_id: ACTIVITY_ID,
          truncated: false,
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
