import "@testing-library/jest-dom/vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient } from "@tanstack/react-query";
import { StrictMode } from "react";
import { afterEach, expect, it, vi } from "vitest";

import { MessageComposer } from "./MessageComposer";

const OPERATION_ID = "018f47a6-7b2d-7c35-8b18-684e38ab6ef7";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it.each([
  [201, false],
  [201, true],
  [401, false],
  [401, true],
] as const)(
  "settles a %s response only while its composer is mounted (unmounted=%s)",
  async (status, unmounted) => {
    let settle!: (response: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(
        () =>
          new Promise<Response>((resolve) => {
            settle = resolve;
          }),
      ),
    );
    const client = new QueryClient();
    const reset = vi.spyOn(client, "resetQueries");
    const onUnauthorized = vi.fn();
    const onOperationAccepted = vi.fn();
    const user = userEvent.setup();
    const view = render(
      <StrictMode>
        <MessageComposer
          token={`browser-v1.${"a".repeat(43)}`}
          sceneKey="default"
          sceneOpen={true}
          queryClient={client}
          timelineQueryKey={["scene-timeline", "default"]}
          onUnauthorized={onUnauthorized}
          onOperationAccepted={onOperationAccepted}
        />
      </StrictMode>,
    );
    await user.type(
      screen.getByLabelText("输入内容"),
      "这是一条正在发送的消息。",
    );
    await user.click(screen.getByRole("button", { name: "提交输入" }));
    expect(screen.getByRole("button", { name: "提交输入" })).toBeDisabled();
    if (unmounted) view.unmount();

    await act(async () => {
      settle(
        Response.json(
          status === 201
            ? {
                status: "accepted",
                trace_id: "a".repeat(32),
                occurred_at: "2026-08-08T05:00:00.000000Z",
                message: "The Creator input is durably accepted.",
                result_ref: OPERATION_ID,
                custodian: "runtime",
                details: {},
              }
            : {
                status: "rejected",
                error: { code: "CREATOR-SESSION-EXPIRED" },
              },
          { status },
        ),
      );
    });

    expect(onOperationAccepted).toHaveBeenCalledTimes(
      status === 201 && !unmounted ? 1 : 0,
    );
    expect(onUnauthorized).toHaveBeenCalledTimes(
      status === 401 && !unmounted ? 1 : 0,
    );
    expect(reset).toHaveBeenCalledTimes(status === 201 && !unmounted ? 1 : 0);
  },
);
