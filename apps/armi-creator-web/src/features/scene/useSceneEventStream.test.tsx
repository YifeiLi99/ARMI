import { cleanup, render, waitFor } from "@testing-library/react";
import { QueryClient } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";

import type { CreatorProjectionEvent } from "../../api/eventStream";
import { useSceneEventStream } from "./useSceneEventStream";

const consumeMock = vi.hoisted(() => vi.fn());

vi.mock("../../api/eventStream", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api/eventStream")>()),
  consumeCreatorEventStream: consumeMock,
}));

const MATERIAL_ID = "018f47a6-7b2d-7c35-8b18-684e38ab6ef7";

function StreamHarness({ client }: { client: QueryClient }) {
  const state = useSceneEventStream({
    enabled: true,
    token: `browser-v1.${"a".repeat(43)}`,
    sceneKey: "creator.default",
    queryClient: client,
    queryKey: ["scene-timeline", "creator.default"],
    onUnauthorized: () => undefined,
    registerAbort: () => undefined,
  });
  return <div data-state={state} />;
}

afterEach(() => {
  cleanup();
  consumeMock.mockReset();
});

it("removes an opened material body before refetching summaries on invalidation", async () => {
  consumeMock.mockImplementation(
    async (
      _token: string,
      _sceneKey: string,
      _lastEventId: string | undefined,
      signal: AbortSignal,
      onConnected: () => void,
      onEvent: (event: CreatorProjectionEvent) => Promise<void>,
    ) => {
      onConnected();
      await onEvent({
        contract_version: "1.0",
        event_id: `sse-v1.${"b".repeat(22)}.1`,
        event_kind: "material.invalidated",
        resource_kind: "material",
        resource_ref: MATERIAL_ID,
        projection_version: "life-record-query.v2",
        occurred_at: "2026-08-05T10:00:00.000000Z",
      });
      await new Promise<void>((resolve) =>
        signal.addEventListener("abort", () => resolve(), { once: true }),
      );
    },
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  client.setQueryData(["life-material", MATERIAL_ID], { body: "private body" });
  client.setQueryData(["life-records", "material"], { items: [] });
  const removeSpy = vi.spyOn(client, "removeQueries");
  const resetSpy = vi.spyOn(client, "resetQueries");

  render(<StreamHarness client={client} />);

  await waitFor(() => {
    expect(removeSpy).toHaveBeenCalled();
    expect(client.getQueryData(["life-material", MATERIAL_ID])).toBeUndefined();
    expect(resetSpy).toHaveBeenCalled();
  });
});
