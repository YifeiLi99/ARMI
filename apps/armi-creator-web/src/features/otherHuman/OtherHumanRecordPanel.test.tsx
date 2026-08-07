import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OtherHumanRecordPanel } from "./OtherHumanRecordPanel";

const PARTY_ID = "01980f7d-7b8f-7e2a-8a11-2ab8e1234569";
const SCENE_ID = "01980f7d-7b8f-7e2a-8a11-2ab8e1234570";

afterEach(() => vi.restoreAllMocks());

describe("OtherHumanRecordPanel", () => {
  it("navigates party and scene records without offering write controls", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      const body = url.includes("/timeline?")
        ? {
            contract_version: "1.0",
            projection_version: "other-human-record.v1",
            party_id: PARTY_ID,
            scene_id: SCENE_ID,
            items: [
              {
                timeline_item_id: "01980f7d-7b8f-7e2a-8a11-2ab8e1234571",
                source_ref: "01980f7d-7b8f-7e2a-8a11-2ab8e1234572",
                direction: "received",
                status: "accepted",
                text: "你好",
                occurred_at: "2026-08-08T00:00:00.000000Z",
              },
            ],
          }
        : url.includes("/scenes?")
          ? {
              contract_version: "1.0",
              projection_version: "other-human-record.v1",
              party: {
                party_id: PARTY_ID,
                party_key: "friend-1",
                display_label: "朋友",
                scene_count: 1,
                record_count: 1,
              },
              items: [
                {
                  scene_id: SCENE_ID,
                  scene_key: "tea",
                  status: "open",
                  record_count: 1,
                },
              ],
            }
          : {
              contract_version: "1.0",
              projection_version: "other-human-record.v1",
              items: [
                {
                  party_id: PARTY_ID,
                  party_key: "friend-1",
                  display_label: "朋友",
                  scene_count: 1,
                  record_count: 1,
                },
              ],
            };
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    render(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <OtherHumanRecordPanel
          token="token"
          environmentId="env"
          creatorPartyId="creator"
          onUnauthorized={vi.fn()}
        />
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "查看交流记录" }));
    fireEvent.click(await screen.findByRole("button", { name: /朋友/ }));
    fireEvent.click(await screen.findByRole("button", { name: /tea/ }));
    expect(await screen.findByText("你好")).toBeInTheDocument();
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(3));
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });
});
