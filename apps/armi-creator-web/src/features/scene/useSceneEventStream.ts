import { useEffect, useRef, useState } from "react";
import type { QueryKey, QueryClient } from "@tanstack/react-query";

import {
  compareEventIds,
  consumeCreatorEventStream,
  EventStreamFailure,
} from "../../api/eventStream";

export type LiveUpdateState = "connecting" | "connected" | "disconnected";

type SceneEventStreamOptions = {
  enabled: boolean;
  token: string;
  sceneKey: string;
  queryClient: QueryClient;
  queryKey: QueryKey;
  onUnauthorized: () => void;
  registerAbort: (abort: (() => void) | null) => void;
};

const RECONNECT_SECONDS = [1, 2, 4, 8, 10] as const;
const POLLING_MILLISECONDS = 10_000;

function wait(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) {
      resolve();
      return;
    }
    const timeout = window.setTimeout(resolve, milliseconds);
    signal.addEventListener(
      "abort",
      () => {
        window.clearTimeout(timeout);
        resolve();
      },
      { once: true },
    );
  });
}

export function useSceneEventStream({
  enabled,
  token,
  sceneKey,
  queryClient,
  queryKey,
  onUnauthorized,
  registerAbort,
}: SceneEventStreamOptions): LiveUpdateState {
  const [state, setState] = useState<LiveUpdateState>("connecting");
  const lastEventId = useRef<string | undefined>(undefined);

  useEffect(() => {
    if (!enabled) {
      return;
    }
    const controller = new AbortController();
    registerAbort(() => controller.abort());

    async function fullRefetch(): Promise<void> {
      lastEventId.current = undefined;
      await queryClient.resetQueries({ queryKey, exact: true });
    }

    async function run(): Promise<void> {
      let reconnectIndex = 0;
      while (!controller.signal.aborted) {
        setState("connecting");
        try {
          await consumeCreatorEventStream(
            token,
            sceneKey,
            lastEventId.current,
            controller.signal,
            () => {
              reconnectIndex = 0;
              setState("connected");
            },
            async (event) => {
              if (event.resource_ref !== sceneKey) {
                await fullRefetch();
                throw new EventStreamFailure("event");
              }
              if (lastEventId.current !== undefined) {
                const order = compareEventIds(
                  lastEventId.current,
                  event.event_id,
                );
                if (order === "duplicate") {
                  return;
                }
                if (order === "inconsistent") {
                  await fullRefetch();
                  throw new EventStreamFailure("event");
                }
              }
              lastEventId.current = event.event_id;
              await queryClient.resetQueries({ queryKey, exact: true });
            },
          );
        } catch (error) {
          if (controller.signal.aborted) {
            return;
          }
          if (error instanceof EventStreamFailure && error.status === 401) {
            controller.abort();
            onUnauthorized();
            return;
          }
          if (
            error instanceof EventStreamFailure &&
            (error.status === 409 ||
              error.kind === "decode" ||
              error.kind === "syntax" ||
              error.kind === "event")
          ) {
            await fullRefetch();
          }
        }
        if (controller.signal.aborted) {
          return;
        }
        setState("disconnected");
        const seconds =
          RECONNECT_SECONDS[
            Math.min(reconnectIndex, RECONNECT_SECONDS.length - 1)
          ];
        reconnectIndex += 1;
        await wait(seconds! * 1000, controller.signal);
      }
    }

    void run();
    return () => {
      controller.abort();
      registerAbort(null);
    };
  }, [
    enabled,
    onUnauthorized,
    queryClient,
    queryKey,
    registerAbort,
    sceneKey,
    token,
  ]);

  useEffect(() => {
    if (!enabled || state !== "disconnected") {
      return;
    }
    const interval = window.setInterval(
      () => void queryClient.resetQueries({ queryKey, exact: true }),
      POLLING_MILLISECONDS,
    );
    return () => window.clearInterval(interval);
  }, [enabled, queryClient, queryKey, state]);

  return state;
}
