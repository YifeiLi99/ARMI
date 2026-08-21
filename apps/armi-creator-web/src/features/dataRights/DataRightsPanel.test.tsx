import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DataRightsPanel } from "./DataRightsPanel";

const TOKEN = `browser-v1.${"a".repeat(43)}`;
const ORDER_ID = "0198a000-0000-7000-8000-000000000001";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Creator data rights panel", () => {
  it("requires deletion confirmation and shows partial settlement without bodies", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (_input, init) => {
      if (init?.method === "POST") {
        expect(JSON.parse(String(init.body))).toEqual({
          contract_version: "1.0",
          order_kind: "delete_related",
        });
        return new Response(
          JSON.stringify({
            contract_version: "1.0",
            projection_version: "data-rights-order-summary.v1",
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
          contract_version: "1.0",
          projection_version: "data-rights-order-collection.v1",
          orders: [
            {
              contract_version: "1.0",
              projection_version: "data-rights-order-detail.v1",
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
              remaining_locations: ["objective_history"],
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
        <DataRightsPanel
          token={TOKEN}
          environmentId={ORDER_ID}
          creatorPartyId={ORDER_ID}
          onUnauthorized={vi.fn()}
        />
      </QueryClientProvider>,
    );

    await screen.findByText("仍保留于：objective_history");
    await user.selectOptions(screen.getByLabelText("命令"), "delete_related");
    expect(
      screen.getByRole("button", { name: "执行删除相关本地数据" }),
    ).toBeDisabled();
    await user.click(screen.getByLabelText("我确认执行不可撤销的本地删除"));
    await user.click(
      screen.getByRole("button", { name: "执行删除相关本地数据" }),
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(screen.queryByText(/message body/i)).not.toBeInTheDocument();
  });
});
