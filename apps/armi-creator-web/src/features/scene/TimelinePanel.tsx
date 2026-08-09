import { useEffect, useMemo } from "react";
import {
  useInfiniteQuery,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import {
  ApiFailure,
  getEffectDetail,
  getSceneTimeline,
} from "../../api/client";
import type { SceneTimelinePage } from "../../api/client";
import { useSceneEventStream } from "./useSceneEventStream";

type TimelinePanelProps = {
  token: string;
  environmentId: string;
  creatorPartyId: string;
  sceneKey: string;
  onUnauthorized: () => void;
  onOperationSelected: (operationRef: string) => void;
  onEffectSelected: (effectRef: string) => void;
  registerStreamAbort: (abort: (() => void) | null) => void;
};

export function TimelinePanel({
  token,
  environmentId,
  creatorPartyId,
  sceneKey,
  onUnauthorized,
  onOperationSelected,
  onEffectSelected,
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
        <h2 id="timeline-heading" className="visually-hidden">
          对话
        </h2>
        <p className="chat-loading" role="status">
          正在读取对话…
        </p>
      </section>
    );
  }
  if (timeline.isError) {
    return (
      <section className="timeline-panel" aria-labelledby="timeline-heading">
        <h2 id="timeline-heading" className="visually-hidden">
          对话
        </h2>
        <p role="status">当前无法读取对话。</p>
        <button
          type="button"
          onClick={() =>
            void queryClient.resetQueries({ queryKey, exact: true })
          }
        >
          重新读取
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
      <div className="chat-utility-row">
        <h2 id="timeline-heading" className="visually-hidden">
          对话
        </h2>
        <p className={`live-update is-${liveUpdate}`} role="status">
          <span className="status-dot" aria-hidden="true" />
          {liveUpdate === "connected" ? "实时" : "连接中"}
        </p>
        <button
          type="button"
          className="secondary"
          onClick={() =>
            void queryClient.resetQueries({ queryKey, exact: true })
          }
        >
          刷新对话
        </button>
      </div>
      {items.length === 0 ? (
        <div className="chat-empty" role="status">
          <span className="armi-avatar" aria-hidden="true">
            A
          </span>
          <h3>开始和 ARMI 对话</h3>
          <p>消息会在这里按时间顺序显示。</p>
        </div>
      ) : (
        <ol className="chat-list">
          {items.map((item) => (
            <ChatTimelineItem
              key={item.timeline_item_id}
              item={item}
              token={token}
              onOperationSelected={onOperationSelected}
              onEffectSelected={onEffectSelected}
            />
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

type TimelineItem = SceneTimelinePage["items"][number];

function ChatTimelineItem({
  item,
  token,
  onOperationSelected,
  onEffectSelected,
}: {
  item: TimelineItem;
  token: string;
  onOperationSelected: (operationRef: string) => void;
  onEffectSelected: (effectRef: string) => void;
}) {
  const response = useQuery({
    queryKey: ["effect", item.effect_ref],
    queryFn: ({ signal }) => getEffectDetail(token, item.effect_ref!, signal),
    enabled:
      ["creator_response", "party_response"].includes(item.source_kind) &&
      Boolean(item.effect_ref),
    retry: false,
  });

  if (item.source_kind === "subject_commit") {
    return null;
  }
  const creatorInput = item.source_kind === "creator_input";
  const creatorResponse = ["creator_response", "party_response"].includes(
    item.source_kind,
  );
  const operationRef = item.operation_ref ?? undefined;
  const body = creatorInput
    ? (item.message ?? "消息正文不可用")
    : creatorResponse
      ? (response.data?.response_text ??
        (response.isPending ? "正在组织回复…" : "回复暂时不可见"))
      : item.source_kind;

  return (
    <li
      className={
        creatorInput ? "chat-message is-creator" : "chat-message is-armi"
      }
    >
      {!creatorInput ? (
        <span className="armi-avatar" aria-hidden="true">
          A
        </span>
      ) : null}
      <div className="chat-bubble">
        <p>{body}</p>
        <div className="chat-message-meta">
          <time dateTime={item.occurred_at}>
            {new Date(item.occurred_at).toLocaleTimeString("zh-CN", {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </time>
          {operationRef ? (
            <button
              type="button"
              onClick={() => onOperationSelected(operationRef)}
            >
              详情
            </button>
          ) : null}
          {item.effect_ref ? (
            <button
              type="button"
              onClick={() => onEffectSelected(item.effect_ref!)}
            >
              记录
            </button>
          ) : null}
        </div>
      </div>
    </li>
  );
}
