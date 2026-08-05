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
      await queryClient.resetQueries({
        predicate: (query) =>
          [
            "scene-timeline",
            "activities",
            "activity-timeline",
            "life-records",
            "memories",
            "memory-timeline",
            "maintenance-status",
            "maintenance-timeline",
            "relationship-current",
            "relationship-timeline",
            "capability-requests",
            "creator-operation",
            "creator-effect",
            "subject-summary",
          ].includes(String(query.queryKey[0])),
      });
    }

    async function invalidateResource(
      resourceKind: string,
      resourceRef: string,
    ): Promise<void> {
      if (resourceKind === "scene_timeline") {
        if (resourceRef !== sceneKey) {
          throw new EventStreamFailure("event");
        }
        await queryClient.resetQueries({ queryKey, exact: true });
        return;
      }
      if (resourceKind === "activity") {
        await queryClient.resetQueries({
          predicate: (query) =>
            query.queryKey[0] === "activities" ||
            (query.queryKey[0] === "activity-timeline" &&
              query.queryKey.includes(resourceRef)),
        });
        return;
      }
      if (resourceKind === "memory") {
        await queryClient.resetQueries({
          predicate: (query) =>
            query.queryKey[0] === "life-records" ||
            query.queryKey[0] === "memories" ||
            (query.queryKey[0] === "memory-timeline" &&
              query.queryKey.includes(resourceRef)),
        });
        return;
      }
      if (resourceKind === "maintenance") {
        await queryClient.resetQueries({
          predicate: (query) =>
            query.queryKey[0] === "maintenance-status" ||
            (query.queryKey[0] === "maintenance-timeline" &&
              query.queryKey.includes(resourceRef)),
        });
        return;
      }
      if (resourceKind === "relationship") {
        await queryClient.resetQueries({
          predicate: (query) =>
            query.queryKey[0] === "relationship-current" ||
            (query.queryKey[0] === "relationship-timeline" &&
              query.queryKey.includes(resourceRef)),
        });
        return;
      }
      const prefix = {
        capability_request: "capability-requests",
        operation: "creator-operation",
        effect: "creator-effect",
        subject_summary: "subject-summary",
      }[resourceKind];
      if (prefix === undefined) {
        throw new EventStreamFailure("event");
      }
      await queryClient.resetQueries({
        predicate: (query) =>
          query.queryKey[0] === prefix &&
          (prefix === "capability-requests" ||
            prefix === "subject-summary" ||
            query.queryKey.includes(resourceRef)),
      });
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
              await invalidateResource(event.resource_kind, event.resource_ref);
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
      () =>
        void queryClient.resetQueries({
          predicate: (query) =>
            [
              "scene-timeline",
              "activities",
              "activity-timeline",
              "life-records",
              "memories",
              "memory-timeline",
              "maintenance-status",
              "maintenance-timeline",
              "relationship-current",
              "relationship-timeline",
              "capability-requests",
              "creator-operation",
              "creator-effect",
              "subject-summary",
            ].includes(String(query.queryKey[0])),
        }),
      POLLING_MILLISECONDS,
    );
    return () => window.clearInterval(interval);
  }, [enabled, queryClient, queryKey, state]);

  return state;
}
