import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MaterialPanel } from "./MaterialPanel";

const MATERIAL_ID = "018f47a6-7b2d-7c35-8b18-684e38ab6ef7";
const TOKEN = `browser-v1.${"a".repeat(43)}`;

function jsonResponse(value: object, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function materialList(): object {
  return {
    contract_version: "1.0",
    projection_version: "life-record-query.v2",
    retrieval_kind: "creator_view",
    next_cursor: null,
    items: [
      {
        record_ref: MATERIAL_ID,
        record_kind: "material",
        summary: "雨天随记",
        source_kind: "life_material_current",
        occurred_at: "2026-08-05T10:00:00.000000Z",
        naturally_recallable: null,
        retrieval_kind: "creator_view",
      },
    ],
  };
}

function renderPanel(onUnauthorized = () => undefined): QueryClient {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MaterialPanel
        token={TOKEN}
        environmentId={MATERIAL_ID}
        creatorPartyId="018f47a6-7b2d-7c35-8b18-684e38ab6ef8"
        onUnauthorized={onUnauthorized}
      />
    </QueryClientProvider>,
  );
  return client;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Creator life material panel", () => {
  it("loads current Creator-visible body only after an explicit open", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === "/v1/life-records?limit=20&kind=material") {
        return jsonResponse(materialList());
      }
      if (url === `/v1/materials/${MATERIAL_ID}`) {
        return jsonResponse({
          contract_version: "1.0",
          projection_version: "creator-life-material.v1",
          material_id: MATERIAL_ID,
          material_kind: "diary",
          revision_no: 2,
          title: "雨天随记",
          body: "这段正文只在打开后进入页面内存。",
          metadata: { mood: "quiet" },
          material_status: "active",
          privacy_status: "creator_visible",
          created_at: "2026-08-05T09:00:00.000000Z",
          updated_at: "2026-08-05T10:00:00.000000Z",
        });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderPanel();

    expect(await screen.findByText("雨天随记")).toBeInTheDocument();
    expect(
      screen.queryByText("这段正文只在打开后进入页面内存。"),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "查看正文" }));
    expect(
      await screen.findByText("这段正文只在打开后进入页面内存。"),
    ).toBeInTheDocument();
    expect(screen.getByText("日记 · 当前使用")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "关闭正文" }));
    expect(
      screen.queryByText("这段正文只在打开后进入页面内存。"),
    ).not.toBeInTheDocument();
  });

  it("treats private, deleted, and unknown identities as the same hidden result", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === "/v1/life-records?limit=20&kind=material") {
        return jsonResponse(materialList());
      }
      if (url === `/v1/materials/${MATERIAL_ID}`) {
        return jsonResponse(
          {
            contract_version: "1.0",
            status: "rejected",
            error: { code: "SCOPE_LIFE_MATERIAL_NOT_VISIBLE" },
          },
          404,
        );
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "查看正文" }));
    expect(
      await screen.findByText("已变为私人、被删除或当前不可用", {
        exact: false,
      }),
    ).toBeInTheDocument();
    expect(screen.queryByText("隐藏正文")).not.toBeInTheDocument();
  });
});
