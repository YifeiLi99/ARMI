import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DataRightsPanel } from "./DataRightsPanel";
import { MaterialPanel } from "../material/MaterialPanel";

const TOKEN = `browser-v1.${"a".repeat(43)}`;
const ORDER_ID = "0198a000-0000-7000-8000-000000000001";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Creator data rights panel", () => {
  it.each([401, 503])("handles a %s when reading orders", async (status) => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () =>
        Response.json(
          { status: "rejected", error: { code: "CREATOR-READ-FAILED" } },
          { status },
        ),
      ),
    );
    const onUnauthorized = vi.fn();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <DataRightsPanel
          token={TOKEN}
          environmentId={ORDER_ID}
          creatorPartyId={ORDER_ID}
          onUnauthorized={onUnauthorized}
        />
      </QueryClientProvider>,
    );

    await screen.findByText("当前无法读取数据权利结果。");
    expect(onUnauthorized).toHaveBeenCalledTimes(status === 401 ? 1 : 0);
  });

  it("requires deletion confirmation and shows partial settlement without bodies", async () => {
    let deleted = false;
    const body = "这段已打开的正文应在删除生效后消失。";
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/v1/life-records?limit=20&kind=material") {
        return new Response(
          JSON.stringify({
            projection_kind: "life-record-query",
            retrieval_kind: "creator_view",
            next_cursor: null,
            items: deleted
              ? []
              : [
                  {
                    record_ref: ORDER_ID,
                    record_kind: "material",
                    summary: "待删除资料",
                    source_kind: "life_material_current",
                    occurred_at: "2026-08-08T05:00:00.000000Z",
                    naturally_recallable: null,
                    retrieval_kind: "creator_view",
                  },
                ],
          }),
        );
      }
      if (url === `/v1/materials/${ORDER_ID}`) {
        return deleted
          ? new Response(
              JSON.stringify({
                status: "rejected",
                error: { code: "SCOPE_LIFE_MATERIAL_NOT_VISIBLE" },
              }),
              { status: 404 },
            )
          : new Response(
              JSON.stringify({
                projection_kind: "creator-life-material",
                material_id: ORDER_ID,
                material_kind: "diary",
                revision_no: 1,
                title: "待删除资料",
                body,
                metadata: {},
                material_status: "active",
                privacy_status: "creator_visible",
                created_at: "2026-08-08T05:00:00.000000Z",
                updated_at: "2026-08-08T05:00:00.000000Z",
              }),
            );
      }
      if (init?.method === "POST") {
        expect(JSON.parse(String(init.body))).toEqual({
          order_kind: "delete_related",
        });
        deleted = true;
        return new Response(
          JSON.stringify({
            projection_kind: "data-rights-order-summary",
            order_id: ORDER_ID,
            requester_party_id: ORDER_ID,
            requester_kind: "creator",
            order_kind: "delete_related",
            scope_kind: "party_local_data",
            scope_party_id: ORDER_ID,
            status: "effective",
            execution_status: "partial",
            request_digest: `sha256:${"1".repeat(64)}`,
            effective_at: "2026-08-08T05:00:00.000000Z",
            completed_at: "2026-08-08T05:00:01.000000Z",
            newly_created: true,
          }),
          { status: 201 },
        );
      }
      return new Response(
        JSON.stringify({
          projection_kind: "data-rights-order-collection",
          orders: [
            {
              projection_kind: "data-rights-order-detail",
              order_id: ORDER_ID,
              requester_party_id: ORDER_ID,
              requester_kind: "creator",
              order_kind: "delete_related",
              scope_kind: "party_local_data",
              scope_party_id: ORDER_ID,
              status: "effective",
              execution_status: "partial",
              request_digest: `sha256:${"1".repeat(64)}`,
              effective_at: "2026-08-08T05:00:00.000000Z",
              completed_at: "2026-08-08T05:00:01.000000Z",
              newly_created: false,
              items: [],
              retention_reasons: ["objective_history"],
              timeline: [
                {
                  event_kind: "order_effective",
                  occurred_at: "2026-08-08T05:00:00.000000Z",
                  item_id: null,
                  status: "effective",
                },
              ],
            },
          ],
        }),
        { status: 200 },
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={queryClient}>
        <MaterialPanel
          token={TOKEN}
          environmentId={ORDER_ID}
          creatorPartyId={ORDER_ID}
          onUnauthorized={vi.fn()}
        />
        <DataRightsPanel
          token={TOKEN}
          environmentId={ORDER_ID}
          creatorPartyId={ORDER_ID}
          onUnauthorized={vi.fn()}
        />
      </QueryClientProvider>,
    );

    await screen.findByText("保留理由：objective_history");
    await user.click(await screen.findByRole("button", { name: "查看正文" }));
    await screen.findByText(body);
    await user.selectOptions(screen.getByLabelText("命令"), "delete_related");
    expect(
      screen.getByRole("button", { name: "执行删除相关本地数据" }),
    ).toBeDisabled();
    await user.click(screen.getByLabelText("我确认执行不可撤销的本地删除"));
    await user.click(
      screen.getByRole("button", { name: "执行删除相关本地数据" }),
    );
    await screen.findByText("删除命令已立即生效", { exact: false });
    await waitFor(() =>
      expect(screen.queryByText(body)).not.toBeInTheDocument(),
    );
    expect(
      queryClient.getQueryData(["life-material", ORDER_ID, ORDER_ID, ORDER_ID]),
    ).toBeUndefined();
    expect(screen.queryByText(/message body/i)).not.toBeInTheDocument();
  });
});
