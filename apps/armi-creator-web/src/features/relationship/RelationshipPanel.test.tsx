import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RelationshipPanel } from "./RelationshipPanel";

const RELATIONSHIP_ID = "018f47a6-7b2d-7c35-8b18-684e38ab6ef7";
const REVISION_ID = "018f47a6-7b2d-7c35-8b18-684e38ab6ef8";
const OPERATION_ID = "018f47a6-7b2d-7c35-8b18-684e38ab6ef9";

function jsonResponse(value: object, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function currentRelationship() {
  return {
    contract_version: "1.0",
    projection_version: "creator-relationship.v2",
    relationship: {
      relationship_id: RELATIONSHIP_ID,
      current_revision_id: REVISION_ID,
      head_version: 1,
      created_at: "2026-08-05T10:00:00.000000Z",
      current: {
        relationship_revision_id: REVISION_ID,
        revision_no: 1,
        facts: [
          {
            fact_id: "018f47a6-7b2d-7c35-8b18-684e38ab6efb",
            kind: "party_expression",
            summary: "Creator 表达了联系限制",
          },
        ],
        interpretation: "我会尊重这项边界",
        boundaries: [
          {
            party_role: "other",
            kind: "contact",
            action: "restrict",
            summary: "不要在深夜联系",
          },
        ],
        commitments: [
          {
            commitment_id: "018f47a6-7b2d-7c35-8b18-684e38ab6efa",
            party_role: "subject",
            scope: "联系时间",
            content: "不会在深夜主动联系",
            status: "active",
            last_event_kind: "established",
            last_event_summary: "已建立承诺",
          },
        ],
        open_issues: [],
        commitment_event: {
          commitment_id: "018f47a6-7b2d-7c35-8b18-684e38ab6efa",
          kind: "established",
          summary: "已建立承诺",
          related_commitment_id: null,
        },
        issue_resolution: null,
        status: "active",
        occurred_at: "2026-08-05T10:00:00.000000Z",
      },
    },
  };
}

function renderPanel(
  onUnauthorized = () => undefined,
  onOperationAccepted = () => undefined,
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <RelationshipPanel
        token={`browser-v1.${"a".repeat(43)}`}
        environmentId={RELATIONSHIP_ID}
        creatorPartyId={REVISION_ID}
        onUnauthorized={onUnauthorized}
        onOperationAccepted={onOperationAccepted}
      />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Creator relationship panel", () => {
  it("shows only structured projection and submits a formal boundary expression", async () => {
    const requests: RequestInit[] = [];
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const path = String(input);
      if (path === "/v1/relationships/current") {
        return jsonResponse(currentRelationship());
      }
      if (path === `/v1/relationships/${RELATIONSHIP_ID}/timeline`) {
        return jsonResponse({
          contract_version: "1.0",
          projection_version: "creator-relationship.v2",
          relationship_id: RELATIONSHIP_ID,
          items: [currentRelationship().relationship.current],
          truncated: false,
        });
      }
      if (path === "/v1/relationships/current/boundaries") {
        requests.push(init ?? {});
        return jsonResponse(
          {
            contract_version: "1.0",
            status: "accepted",
            trace_id: "0123456789abcdef0123456789abcdef",
            occurred_at: "2026-08-05T10:00:00.000000Z",
            message: "accepted",
            result_ref: OPERATION_ID,
            custodian: "runtime",
            details: {
              interaction_id: REVISION_ID,
              evidence_id: RELATIONSHIP_ID,
              opportunity_id: OPERATION_ID,
              operation_url: `/v1/operations/${OPERATION_ID}`,
            },
          },
          202,
        );
      }
      throw new Error(`unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const onOperationAccepted = vi.fn();
    const user = userEvent.setup();
    renderPanel(() => undefined, onOperationAccepted);

    expect(await screen.findByText("我会尊重这项边界")).toBeInTheDocument();
    expect(screen.getByText("不会在深夜主动联系")).toBeInTheDocument();
    expect(screen.queryByText(/其他场景原文内容/)).toBeNull();
    await user.click(screen.getByRole("button", { name: "查看关系变化" }));
    expect(await screen.findByText("建立承诺：已建立承诺")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("范围"), "privacy");
    await user.selectOptions(screen.getByLabelText("要求"), "refuse");
    await user.type(screen.getByLabelText("具体说明"), "不要披露我的私密信息");
    await user.click(screen.getByRole("button", { name: "提交边界表达" }));

    expect(
      await screen.findByText("边界表达已进入正式对话处理。"),
    ).toBeInTheDocument();
    expect(onOperationAccepted).toHaveBeenCalledWith(OPERATION_ID);
    expect(requests).toHaveLength(1);
    expect(JSON.parse(String(requests[0]?.body))).toEqual({
      contract_version: "1.0",
      kind: "privacy",
      action: "refuse",
      summary: "不要披露我的私密信息",
    });
  });

  it("allows the first boundary before a relationship exists", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        jsonResponse({
          contract_version: "1.0",
          projection_version: "creator-relationship.v2",
          relationship: null,
        }),
      ),
    );
    renderPanel();

    expect(
      await screen.findByText(
        "当前还没有形成关系理解；仍可在下方表达第一项边界。",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "提交边界表达" })).toBeEnabled();
  });

  it("clears an unauthorized session", async () => {
    const onUnauthorized = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockResolvedValue(new Response(null, { status: 401 })),
    );
    renderPanel(onUnauthorized);

    expect(await screen.findByText("当前无法读取关系。")).toBeInTheDocument();
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });
});
