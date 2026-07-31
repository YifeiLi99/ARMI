import { useEffect, useMemo } from "react";
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";

import { ApiFailure, getSceneTimeline } from "../../api/client";
import { useSceneEventStream } from "./useSceneEventStream";

type TimelinePanelProps = {
  token: string;
  environmentId: string;
  creatorPartyId: string;
  sceneKey: string;
  onUnauthorized: () => void;
  onOperationSelected: (operationRef: string) => void;
  registerStreamAbort: (abort: (() => void) | null) => void;
};

export function TimelinePanel({
  token,
  environmentId,
  creatorPartyId,
  sceneKey,
  onUnauthorized,
  onOperationSelected,
  registerStreamAbort,
}: TimelinePanelProps) {
  const queryClient = useQueryClient();
  const queryKey = useMemo(
    () => ["scene-timeline", environmentId, creatorPartyId, sceneKey] as const,
    [creatorPartyId, environmentId, sceneKey],
  );
  const timeline = useInfiniteQuery({
    queryKey,
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) =>
      getSceneTimeline(token, sceneKey, 50, pageParam, signal),
    getNextPageParam: (lastPage) => lastPage.next_cursor,
  });

  useEffect(() => {
    if (timeline.error instanceof ApiFailure && timeline.error.status === 401) {
      onUnauthorized();
    }
  }, [onUnauthorized, timeline.error]);
  const liveUpdate = useSceneEventStream({
    enabled: timeline.isSuccess,
    token,
    sceneKey,
    queryClient,
    queryKey,
    onUnauthorized,
    registerAbort: registerStreamAbort,
  });

  if (timeline.isPending) {
    return (
      <section className="timeline-panel" aria-labelledby="timeline-heading">
        <h2 id="timeline-heading">耐久可见记录</h2>
        <p role="status">正在读取权威 timeline</p>
      </section>
    );
  }
  if (timeline.isError) {
    return (
      <section className="timeline-panel" aria-labelledby="timeline-heading">
        <h2 id="timeline-heading">耐久可见记录</h2>
        <p role="status">当前无法核验权威 timeline。</p>
        <button
          type="button"
          onClick={() =>
            void queryClient.resetQueries({ queryKey, exact: true })
          }
        >
          重新读取 timeline
        </button>
      </section>
    );
  }

  const seen = new Set<string>();
  const items = [...timeline.data.pages]
    .reverse()
    .flatMap((page) => page.items)
    .filter((item) => {
      if (seen.has(item.timeline_item_id)) {
        return false;
      }
      seen.add(item.timeline_item_id);
      return true;
    });

  return (
    <section className="timeline-panel" aria-labelledby="timeline-heading">
      <div className="timeline-heading-row">
        <h2 id="timeline-heading">耐久可见记录</h2>
        <button
          type="button"
          className="secondary"
          onClick={() =>
            void queryClient.resetQueries({ queryKey, exact: true })
          }
        >
          刷新
        </button>
      </div>
      <p className={`live-update is-${liveUpdate}`} role="status">
        {liveUpdate === "connecting"
          ? "正在建立实时更新"
          : liveUpdate === "connected"
            ? "实时更新已连接"
            : "实时更新已断开，正在定期核验"}
      </p>
      {items.length === 0 ? (
        <p className="timeline-empty" role="status">
          尚无耐久可见记录
        </p>
      ) : (
        <ol className="timeline-list">
          {items.map((item) => (
            <li key={item.timeline_item_id}>
              <span>{item.source_kind}</span>
              <strong>{item.status}</strong>
              <time dateTime={item.occurred_at}>{item.occurred_at}</time>
              {item.operation_ref === undefined ||
              item.operation_ref === null ? null : (
                <button
                  type="button"
                  className="secondary timeline-operation"
                  onClick={() => onOperationSelected(item.operation_ref!)}
                >
                  查看 operation
                </button>
              )}
            </li>
          ))}
        </ol>
      )}
      {timeline.hasNextPage ? (
        <button
          type="button"
          disabled={timeline.isFetchingNextPage}
          onClick={() => void timeline.fetchNextPage()}
        >
          {timeline.isFetchingNextPage ? "正在读取" : "加载更早记录"}
        </button>
      ) : null}
    </section>
  );
}
