import "@testing-library/jest-dom/vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
      projection_kind: "creator-effect",
      effect_id: EFFECT_ID,
      action_intent_ref: OPERATION_ID,
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
    expect(screen.getByText("Action Intent")).toBeInTheDocument();
    expect(screen.getByText("creator.scene.reply")).toBeInTheDocument();
    expect(screen.getByText(malicious)).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
    expect(document.querySelector("script")).toBeNull();
  });

  it("makes unknown highly visible without offering a retry action", async () => {
    showEffect({
      projection_kind: "creator-effect",
      effect_id: EFFECT_ID,
      action_intent_ref: OPERATION_ID,
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

  it.each([
    [200, "switch"],
    [401, "switch"],
    [503, "switch"],
    [503, "retry"],
    [401, "unmount"],
  ] as const)("ignores a late artifact %s after %s", async (status, change) => {
    const nextEffect = "018f47a6-7b2d-7c35-8b18-684e38ab6ef9";
    let settle!: (value: Response) => void;
    const pending = new Promise<Response>((resolve) => {
      settle = resolve;
    });
    let artifactRequests = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async (input) => {
        const path = String(input);
        if (path.endsWith("/artifacts/final_result")) {
          artifactRequests += 1;
          return artifactRequests === 1
            ? pending
            : new Response("当前效果的结果");
        }
        return Response.json({
          projection_kind: "creator-effect",
          effect_id: path.includes(EFFECT_ID) ? EFFECT_ID : nextEffect,
          action_intent_ref: OPERATION_ID,
          capability_kind: "codex.task",
          effect_kind: "codex_delegation",
          status: "completed",
          verification_status: "verified",
          attempt_count: 1,
        });
      }),
    );
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const unauthorized = vi.fn();
    const panel = (effectRef: string) => (
      <QueryClientProvider client={client}>
        <EffectDetail
          token={`browser-v1.${"a".repeat(43)}`}
          effectRef={effectRef}
          onClose={() => undefined}
          onUnauthorized={unauthorized}
        />
      </QueryClientProvider>
    );
    const view = render(panel(EFFECT_ID));
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "查看结果" }));
    if (change === "switch") {
      view.rerender(panel(nextEffect));
    }
    if (change !== "unmount") {
      await user.click(await screen.findByRole("button", { name: "查看结果" }));
      expect(await screen.findByText("当前效果的结果")).toBeInTheDocument();
    } else {
      view.unmount();
    }
    await act(async () => {
      settle(
        status === 200
          ? new Response("之前效果的结果")
          : Response.json({ error: { code: "TEST-FAILURE" } }, { status }),
      );
    });
    expect(unauthorized).not.toHaveBeenCalled();
    expect(screen.queryByText("之前效果的结果")).not.toBeInTheDocument();
    expect(screen.queryByText("当前无法核验该产物。")).not.toBeInTheDocument();
    if (change !== "unmount") {
      expect(screen.getByText("当前效果的结果")).toBeInTheDocument();
    }
  });
});
