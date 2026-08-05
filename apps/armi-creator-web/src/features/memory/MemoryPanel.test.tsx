import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MemoryPanel } from "./MemoryPanel";

const MEMORY_ID = "018f47a6-7b2d-7c35-8b18-684e38ab6ef7";
const REVISION_ID = "018f47a6-7b2d-7c35-8b18-684e38ab6ef8";

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
      <MemoryPanel
        token={`browser-v1.${"a".repeat(43)}`}
        environmentId={MEMORY_ID}
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

describe("Creator memory panel", () => {
  it("separates exact evidence from natural recall and shows memory history", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === "/v1/life-records?limit=20") {
        return jsonResponse({
          contract_version: "1.0",
          projection_version: "life-record-query.v2",
          retrieval_kind: "creator_view",
          next_cursor: null,
          items: [
            {
              record_ref: MEMORY_ID,
              record_kind: "memory",
              summary: "一次已经淡忘的旧理解",
              source_kind: "reported",
              occurred_at: "2026-08-04T10:00:00.000000Z",
              naturally_recallable: false,
              retrieval_kind: "creator_view",
            },
          ],
        });
      }
      if (url === "/v1/memories?limit=20") {
        return jsonResponse({
          contract_version: "1.0",
          projection_version: "creator-memory.v1",
          retrieval_kind: "creator_view",
          next_cursor: null,
          items: [
            {
              memory_id: MEMORY_ID,
              summary: "一次已经淡忘的旧理解",
              uncertainty: "来源是转述",
              source_kind: "reported",
              source_fact_class: "external_claim",
              accessibility: "forgotten",
              revision_kind: "forgotten",
              revision_no: 2,
              head_version: 2,
              created_at: "2026-08-04T09:00:00.000000Z",
              updated_at: "2026-08-04T10:00:00.000000Z",
            },
          ],
        });
      }
      if (url === `/v1/memories/${MEMORY_ID}/timeline?limit=20`) {
        return jsonResponse({
          contract_version: "1.0",
          projection_version: "creator-memory.v1",
          retrieval_kind: "creator_view",
          memory_id: MEMORY_ID,
          next_cursor: null,
          items: [
            {
              revision_id: REVISION_ID,
              revision_no: 2,
              revision_kind: "forgotten",
              accessibility: "forgotten",
              summary: "一次已经淡忘的旧理解",
              uncertainty: "来源是转述",
              source_kind: "reported",
              source_fact_class: "external_claim",
              relation_kind: null,
              related_memory_id: null,
              occurred_at: "2026-08-04T10:00:00.000000Z",
            },
          ],
        });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderPanel();

    expect(screen.getByRole("option", { name: "关系理解" })).toHaveValue(
      "relationship",
    );
    expect(screen.getByRole("option", { name: "生活资料" })).toHaveValue(
      "material",
    );
    expect(
      await screen.findByText("本次从权威生活记录取得的证据", {
        exact: false,
      }),
    ).toBeInTheDocument();
    expect(await screen.findAllByText("当前无法自然回忆")).toHaveLength(2);
    await user.click(screen.getByRole("button", { name: "查看记忆变化" }));
    expect(await screen.findByText("遗忘")).toBeInTheDocument();
    expect(
      screen.getByText("来源是转述", { exact: false }),
    ).toBeInTheDocument();
  });

  it("submits a bounded record search and clears an unauthorized session", async () => {
    const onUnauthorized = vi.fn();
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === "/v1/life-records?limit=20") {
        return jsonResponse({
          contract_version: "1.0",
          projection_version: "life-record-query.v2",
          retrieval_kind: "creator_view",
          next_cursor: null,
          items: [],
        });
      }
      if (url === "/v1/memories?limit=20") {
        return new Response(null, { status: 401 });
      }
      if (
        url === "/v1/life-records?limit=20&kind=activity&q=%E6%95%B4%E7%90%86"
      ) {
        return jsonResponse({
          contract_version: "1.0",
          projection_version: "life-record-query.v2",
          retrieval_kind: "creator_view",
          next_cursor: null,
          items: [],
        });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderPanel(onUnauthorized);

    expect(await screen.findByText("当前无法读取记忆。")).toBeInTheDocument();
    expect(onUnauthorized).toHaveBeenCalledOnce();
    await user.type(screen.getByLabelText("查询生活记录"), "整理");
    await user.selectOptions(screen.getByLabelText("范围"), "activity");
    await user.click(screen.getByRole("button", { name: "查询" }));
    expect(fetchMock).toHaveBeenCalledWith(
      "/v1/life-records?limit=20&kind=activity&q=%E6%95%B4%E7%90%86",
      expect.objectContaining({ credentials: "omit" }),
    );
  });
});
