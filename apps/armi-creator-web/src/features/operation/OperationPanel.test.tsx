import "@testing-library/jest-dom/vitest";
import { createRef } from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OperationPanel } from "./OperationPanel";

const OPERATION_ID = "018f47a6-7b2d-7c35-8b18-684e38ab6ef7";
const EFFECT_ID = "018f47a6-7b2d-7c35-8b18-684e38ab6ef8";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function outcome(status: string, codex = false): object {
  const common = {
    contract_version: "1.0",
    status,
    trace_id: "a".repeat(32),
    occurred_at: "2026-07-30T10:00:00.000000Z",
    message: "safe",
    details: {
      projection_version: "creator-operation.v2",
      operation_ref: OPERATION_ID,
      operation_kind: codex
        ? "codex_delegation"
        : status === "completed"
          ? "formal_dialogue"
          : "creator_response",
      stage: status === "completed" ? "no_action" : "registered",
      outcome: status === "completed" ? "no_action" : "pending",
      ...(status === "accepted" ? { effect_ref: EFFECT_ID } : {}),
      ...(codex
        ? {
            codex_execution: {
              task_source_ref: "018f47a6-7b2d-7c35-8b18-684e38ab6efa",
              verification_ref: "018f47a6-7b2d-7c35-8b18-684e38ab6efb",
              execution_status: "verified",
              model_id: "gpt-5.6-sol",
              sdk_identity: "openai-codex/1",
              validator_id: "validator-v1",
              source_tree_digest: `sha256:${"a".repeat(64)}`,
              final_tree_digest: `sha256:${"b".repeat(64)}`,
            },
          }
        : {}),
    },
  };
  if (status === "accepted")
    return { ...common, result_ref: EFFECT_ID, custodian: "runtime" };
  if (status === "applied")
    return { ...common, result_ref: OPERATION_ID, state_version: 2 };
  if (status === "waiting")
    return {
      ...common,
      result_ref: OPERATION_ID,
      waiting_for: "effect_dispatch",
      resume_condition: "effect_settlement",
    };
  if (status === "rejected" || status === "unavailable")
    return {
      ...common,
      error: {
        category: status === "rejected" ? "policy" : "dependency",
        code:
          status === "rejected" ? "POLICY_DENIED" : "DEPENDENCY_UNAVAILABLE",
        error_instance_id: "018f47a6-7b2d-7c35-8b18-684e38ab6ef9",
      },
    };
  if (status === "failed")
    return {
      ...common,
      error: {
        category: "internal",
        code: "INTERNAL_FAILED",
        error_instance_id: "018f47a6-7b2d-7c35-8b18-684e38ab6ef9",
      },
    };
  if (status === "unknown")
    return {
      ...common,
      result_ref: EFFECT_ID,
      custodian: "runtime",
      verification_action: "verify_creator_inbox",
    };
  return {
    ...common,
    result_ref: OPERATION_ID,
  };
}

async function renderOutcome(status: string, codex = false) {
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(outcome(status, codex)), {
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const selected = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <OperationPanel
        token={`browser-v1.${"a".repeat(43)}`}
        operationRef={OPERATION_ID}
        onEffectSelected={selected}
        onUnauthorized={() => undefined}
        effectTriggerRef={createRef<HTMLButtonElement>()}
      />
    </QueryClientProvider>,
  );
  expect(await screen.findByText(status)).toBeInTheDocument();
  return selected;
}

describe("Creator operation projection", () => {
  it.each([
    "accepted",
    "applied",
    "waiting",
    "rejected",
    "unavailable",
    "failed",
    "unknown",
    "completed",
  ])("renders the authoritative %s outcome", async (status) => {
    await renderOutcome(status);
  });

  it("uses strict completion details and exposes an explicit effect action", async () => {
    const selected = await renderOutcome("accepted");
    expect(screen.getByText("Creator 回应")).toBeInTheDocument();
    screen.getByRole("button", { name: "查看效果详情" }).click();
    expect(selected).toHaveBeenCalledWith(EFFECT_ID);
  });

  it("renders the Codex owner execution summary", async () => {
    await renderOutcome("accepted", true);
    expect(screen.getByText("gpt-5.6-sol")).toBeInTheDocument();
    expect(screen.getByText("verified")).toBeInTheDocument();
    expect(screen.getByText(`sha256:${"b".repeat(64)}`)).toBeInTheDocument();
  });
});
