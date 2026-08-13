import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";

import type { CreatorProjectionEvent } from "../../api/eventStream";
import { EventStreamFailure } from "../../api/eventStream";
import { useSceneEventStream } from "./useSceneEventStream";

const consumeMock = vi.hoisted(() => vi.fn());

vi.mock("../../api/eventStream", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api/eventStream")>()),
  consumeCreatorEventStream: consumeMock,
}));

const MATERIAL_ID = "018f47a6-7b2d-7c35-8b18-684e38ab6ef7";
const STREAM_QUERY_KEY = ["scene-timeline", "creator.default"] as const;
const NOOP = () => undefined;

function StreamHarness({
  client,
  onUnauthorized = NOOP,
}: {
  client: QueryClient;
  onUnauthorized?: () => void;
}) {
  const state = useSceneEventStream({
    enabled: true,
    token: `browser-v1.${"a".repeat(43)}`,
    sceneKey: "creator.default",
    queryClient: client,
    queryKey: STREAM_QUERY_KEY,
    onUnauthorized,
    registerAbort: NOOP,
  });
  return <div data-testid="stream-state" data-state={state} />;
}

afterEach(() => {
  cleanup();
  consumeMock.mockReset();
  vi.useRealTimers();
});

it.each([
  new EventStreamFailure("content-type"),
  new EventStreamFailure("decode"),
  new EventStreamFailure("syntax"),
  new EventStreamFailure("event"),
  new EventStreamFailure("http", 400),
])(
  "stops automatic reconnect for deterministic stream failures",
  async (error) => {
    consumeMock.mockRejectedValue(error);
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(<StreamHarness client={client} />);

    await waitFor(() => {
      expect(
        screen.getByTestId("stream-state").getAttribute("data-state"),
      ).toBe("disconnected");
    });
    expect(consumeMock).toHaveBeenCalledTimes(1);
  },
);

it("hands 401 to the authentication owner without reconnecting", async () => {
  const onUnauthorized = vi.fn();
  consumeMock.mockRejectedValue(new EventStreamFailure("http", 401));
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  render(<StreamHarness client={client} onUnauthorized={onUnauthorized} />);

  await waitFor(() => expect(onUnauthorized).toHaveBeenCalledOnce());
  expect(consumeMock).toHaveBeenCalledTimes(1);
});

it.each([
  ["network", new TypeError("network")],
  ["server", new EventStreamFailure("http", 503)],
  ["gap", new EventStreamFailure("http", 409)],
  ["eof", undefined],
] as const)(
  "reconnects after a recoverable %s result",
  async (_kind, error) => {
    vi.useFakeTimers();
    if (error === undefined) {
      consumeMock.mockResolvedValueOnce(undefined);
    } else {
      consumeMock.mockRejectedValueOnce(error);
    }
    consumeMock.mockRejectedValueOnce(new EventStreamFailure("event"));
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(<StreamHarness client={client} />);
    await act(async () => Promise.resolve());
    act(() => vi.advanceTimersByTime(1000));
    await act(async () => Promise.resolve());

    expect(consumeMock).toHaveBeenCalledTimes(2);
  },
);

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
