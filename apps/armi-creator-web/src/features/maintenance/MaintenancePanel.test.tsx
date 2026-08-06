import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MaintenancePanel } from "./MaintenancePanel";

const SESSION_ID = "018f47a6-7b2d-7c35-8b18-684e38ab6ef7";
const REVISION_ID = "018f47a6-7b2d-7c35-8b18-684e38ab6ef8";

function jsonResponse(value: object, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderPanel(onUnauthorized = () => undefined) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MaintenancePanel
        token={`browser-v1.${"a".repeat(43)}`}
        environmentId={SESSION_ID}
        creatorPartyId="018f47a6-7b2d-7c35-8b18-684e38ab6ef9"
        onUnauthorized={onUnauthorized}
      />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Creator maintenance panel", () => {
  it("shows objective phases, waiting input and a durable emergency wake", async () => {
    let wakeRequested = false;
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/v1/maintenance/status") {
        return jsonResponse({
          contract_version: "1.0",
          projection_version: "creator-maintenance.v2",
          session: {
            maintenance_session_id: SESSION_ID,
            trigger_kind: "system_deadline",
            phase: "self_check",
            result_status: "running",
            revision_no: 3,
            head_version: 3,
            wake_requested: wakeRequested,
            started_at: "2026-08-04T10:00:00.000000Z",
            updated_at: "2026-08-04T11:00:00.000000Z",
            finished_at: null,
          },
          waiting_input_count: 2,
        });
      }
      if (url === `/v1/maintenance/${SESSION_ID}/timeline`) {
        return jsonResponse({
          contract_version: "1.0",
          projection_version: "creator-maintenance.v2",
          maintenance_session_id: SESSION_ID,
          truncated: false,
          items: [
            {
              revision_id: REVISION_ID,
              revision_no: 3,
              phase: "self_check",
              result_status: "running",
              transition_kind: "advanced",
              occurred_at: "2026-08-04T11:00:00.000000Z",
              work_outcome: "issue_found",
              problem_summary: "关系边界存在尚未处理的冲突。",
            },
          ],
        });
      }
      if (
        url === `/v1/maintenance/${SESSION_ID}/wake` &&
        init?.method === "POST"
      ) {
        wakeRequested = true;
        return new Response(null, { status: 204 });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderPanel();

    expect(await screen.findByText(/正在维护 · 状态检查/)).toBeInTheDocument();
    expect(screen.getByText("系统最迟维护期限")).toBeInTheDocument();
    expect(screen.getByText(/当前有 2 条输入等待处理/)).toBeInTheDocument();
    expect(await screen.findByText("进入下一阶段")).toBeInTheDocument();
    expect(screen.getByText("自检发现问题")).toBeInTheDocument();
    expect(screen.getByText(/关系边界存在尚未处理的冲突/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "紧急唤醒" }));
    expect(
      await screen.findByText("紧急唤醒已登记，正在等待安全检查点。"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/^我/)).toBeNull();
  });

  it("shows the awake state and clears an unauthorized session", async () => {
    const onUnauthorized = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockResolvedValue(new Response(null, { status: 401 })),
    );
    renderPanel(onUnauthorized);

    expect(
      await screen.findByText("当前无法读取维护状态。"),
    ).toBeInTheDocument();
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });
});
