import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
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
  status: "pending" | "limited" | "revoked",
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
    workspace_scope:
      capability === "codex.delegated-work" ? "isolated_ephemeral" : null,
    artifact_scope:
      capability === "codex.delegated-work" ? "explicit_only" : null,
    network_access: capability === "codex.delegated-work" ? false : null,
    max_uses: capability === "codex.delegated-work" ? 1 : 4,
    max_payload_bytes: capability === "creator.scene.reply" ? 4096 : null,
    status,
    capability_availability: "available",
    resolution_reason_code: null,
    request_version: status === "pending" ? 1 : status === "limited" ? 2 : 3,
    created_at: "2026-07-30T10:00:00.000000Z",
    status_changed_at: "2026-07-30T10:00:01.000000Z",
    ...(status !== "pending"
      ? {
          effective_grant: {
            scope_kind: "creator_scene_reply",
            grant_ref: "018f47a6-7b2d-7c35-8b18-684e38ab6efc",
            status: status === "limited" ? "active" : "revoked",
            valid_from: "2026-07-30T10:00:00.000000Z",
            valid_until: "2026-07-30T10:05:00.000000Z",
            ended_at:
              status === "limited" ? null : "2026-07-30T10:04:00.000000Z",
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
  it("shows both grantable scopes without offering a Codex execute action", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        new Response(
          JSON.stringify({
            contract_version: "1.0",
            projection_version: "capability-request.v4",
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
    expect(
      screen.getAllByRole("button", { name: "允许申请范围" }),
    ).toHaveLength(2);
    expect(
      screen.getAllByRole("button", { name: "设置更严格限制" }),
    ).toHaveLength(2);
    expect(screen.getAllByRole("button", { name: "拒绝申请" })).toHaveLength(2);
    expect(
      screen.getByRole("button", { name: "撤回当前 grant" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("1/2 次 · 至 2026-07-30T10:05:00.000000Z"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /执行/ }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/系统权限，不替 ARMI 决定/)).toBeInTheDocument();
    expect(screen.getAllByText(new RegExp(SUBJECT_ID)).length).toBeGreaterThan(
      0,
    );
    expect(
      screen.getAllByText("creator_visible_response").length,
    ).toBeGreaterThan(0);
  });

  it("states the non-retroactive boundary of an authoritative revocation", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        new Response(
          JSON.stringify({
            contract_version: "1.0",
            projection_version: "capability-request.v4",
            items: [item("fb", "creator.scene.reply", "revoked")],
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

    expect(await screen.findByText(/授权已撤回/)).toHaveTextContent(
      /只阻止尚未派发的使用/,
    );
    expect(
      screen.queryByRole("button", { name: "撤回当前 grant" }),
    ).not.toBeInTheDocument();
  });

  it("submits an explicit narrower limit without changing the fixed scope", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (_input, init) => {
      if (init?.method === "POST") {
        return new Response(
          JSON.stringify({
            contract_version: "1.0",
            status: "applied",
            trace_id: "a".repeat(32),
            occurred_at: "2026-07-30T10:00:02.000000Z",
            message: "applied",
            result_ref: "018f47a6-7b2d-7c35-8b18-684e38ab6ef9",
            state_version: 2,
          }),
          { headers: { "Content-Type": "application/json" } },
        );
      }
      return new Response(
        JSON.stringify({
          contract_version: "1.0",
          projection_version: "capability-request.v4",
          items: [item("f9", "creator.scene.reply", "pending")],
        }),
        { headers: { "Content-Type": "application/json" } },
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const user = userEvent.setup();
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

    await user.click(
      await screen.findByRole("button", { name: "设置更严格限制" }),
    );
    const uses = screen.getByLabelText("最大次数");
    await user.clear(uses);
    await user.type(uses, "2");
    await user.click(screen.getByRole("button", { name: "应用更严格限制" }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([, init]) => init?.method === "POST"),
      ).toBe(true);
    });
    const post = fetchMock.mock.calls.find(
      ([, init]) => init?.method === "POST",
    );
    const body = JSON.parse(String(post?.[1]?.body)) as Record<string, unknown>;
    expect(body).toMatchObject({
      decision: "limit",
      expected_request_version: 1,
      valid_for_seconds: 600,
      max_uses: 2,
      max_payload_bytes: 4096,
    });
    expect(body).not.toHaveProperty("workspace_scope");
  });
});
