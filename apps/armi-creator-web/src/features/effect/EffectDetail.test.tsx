import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EffectDetail } from "./EffectDetail";

const EFFECT_ID = "018f47a6-7b2d-7c35-8b18-684e38ab6ef7";
const OPERATION_ID = "018f47a6-7b2d-7c35-8b18-684e38ab6ef8";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function showEffect(value: object) {
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(value), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <EffectDetail
        token={`browser-v1.${"a".repeat(43)}`}
        effectRef={EFFECT_ID}
        onClose={() => undefined}
        onUnauthorized={() => undefined}
      />
    </QueryClientProvider>,
  );
}

describe("Creator effect detail", () => {
  it("reveals verified completed text only as an inert text node", async () => {
    const malicious =
      '<img src="https://outside.invalid/x" onerror="alert(1)">';
    showEffect({
      contract_version: "1.0",
      projection_version: "creator-effect.v3",
      effect_id: EFFECT_ID,
      root_operation_ref: OPERATION_ID,
      capability_request_ref: OPERATION_ID,
      grant_ref: "018f47a6-7b2d-7c35-8b18-684e38ab6ef9",
      capability_kind: "creator.scene.reply",
      effect_kind: "creator_response",
      status: "completed",
      verification_status: "verified",
      attempt_count: 1,
      last_observation_kind: "receipt",
      last_observation_reliability: "reliable",
      registered_at: "2026-07-30T10:00:00.000000Z",
      settled_at: "2026-07-30T10:00:01.000000Z",
      response_text: malicious,
    });

    expect(await screen.findByText("已核验回应")).toBeInTheDocument();
    expect(screen.getByText("授权依据")).toBeInTheDocument();
    expect(screen.getByText("creator.scene.reply")).toBeInTheDocument();
    expect(screen.getByText(malicious)).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
    expect(document.querySelector("script")).toBeNull();
  });

  it("makes unknown highly visible without offering a retry action", async () => {
    showEffect({
      contract_version: "1.0",
      projection_version: "creator-effect.v3",
      effect_id: EFFECT_ID,
      root_operation_ref: OPERATION_ID,
      capability_request_ref: OPERATION_ID,
      grant_ref: "018f47a6-7b2d-7c35-8b18-684e38ab6ef9",
      capability_kind: "creator.scene.reply",
      effect_kind: "creator_response",
      status: "unknown",
      verification_status: "inconclusive",
      attempt_count: 1,
      last_observation_kind: "ambiguous",
      last_observation_reliability: "inconclusive",
      verification_action: "verify_creator_inbox",
      registered_at: "2026-07-30T10:00:00.000000Z",
      settled_at: "2026-07-30T10:00:01.000000Z",
    });

    expect(await screen.findByText(/结果未知/)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /重试/ }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("已核验回应")).not.toBeInTheDocument();
  });
});
