import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CapabilityInbox } from "./CapabilityInbox";

const SUBJECT_ID = "018f47a6-7b2d-7c35-8b18-684e38ab6ef7";
const SCENE_ID = "018f47a6-7b2d-7c35-8b18-684e38ab6ef8";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function item(
  suffix: string,
  capability: "creator.scene.reply" | "codex.delegated-work",
  status: "pending" | "limited",
) {
  return {
    capability_request_id: `018f47a6-7b2d-7c35-8b18-684e38ab6e${suffix}`,
    capability_kind: capability,
    operation: capability === "creator.scene.reply" ? "send" : "execute",
    subject_id: SUBJECT_ID,
    scene_id: SCENE_ID,
    purpose:
      capability === "creator.scene.reply"
        ? "respond_to_creator"
        : "delegate_codex_work",
    audience_scope: capability === "creator.scene.reply" ? "creator" : null,
    data_scope:
      capability === "creator.scene.reply" ? "creator_visible_response" : null,
    valid_for_seconds: 600,
    max_uses: 4,
    max_payload_bytes: 4096,
    status,
    capability_availability:
      capability === "creator.scene.reply" ? "available" : "unavailable",
    resolution_reason_code:
      capability === "creator.scene.reply" ? null : "CAPABILITY-NOT-ACTIVE",
    request_version: status === "pending" ? 1 : 2,
    created_at: "2026-07-30T10:00:00.000000Z",
    ...(status === "limited"
      ? {
          effective_grant: {
            grant_ref: "018f47a6-7b2d-7c35-8b18-684e38ab6efc",
            status: "active",
            valid_from: "2026-07-30T10:00:00.000000Z",
            valid_until: "2026-07-30T10:05:00.000000Z",
            max_uses: 2,
            consumed_uses: 1,
            remaining_uses: 1,
            max_payload_bytes: 2048,
          },
        }
      : {}),
  };
}

describe("Creator capability inbox", () => {
  it("shows requested and effective scope without offering unavailable grants", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        new Response(
          JSON.stringify({
            contract_version: "1.0",
            projection_version: "capability-request.v2",
            items: [
              item("f9", "creator.scene.reply", "pending"),
              item("fa", "codex.delegated-work", "pending"),
              item("fb", "creator.scene.reply", "limited"),
            ],
          }),
          { headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <CapabilityInbox
          token={`browser-v1.${"a".repeat(43)}`}
          environmentId={SUBJECT_ID}
          creatorPartyId={SCENE_ID}
          onUnauthorized={() => undefined}
        />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("codex.delegated-work")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "允许" })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "限制" })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "拒绝" })).toHaveLength(2);
    expect(
      screen.getByRole("button", { name: "撤回 grant" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("1/2 次 · 至 2026-07-30T10:05:00.000000Z"),
    ).toBeInTheDocument();
    expect(screen.getByText("CAPABILITY-NOT-ACTIVE")).toBeInTheDocument();
  });
});
