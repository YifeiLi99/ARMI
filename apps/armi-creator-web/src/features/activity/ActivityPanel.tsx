import { useEffect, useState } from "react";
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";

import {
  ApiFailure,
  getCreatorActivities,
  getCreatorActivityTimeline,
} from "../../api/client";

type ActivityPanelProps = {
  token: string;
  environmentId: string;
  creatorPartyId: string;
  onUnauthorized: () => void;
};

const STATUS_LABELS: Record<string, string> = {
  considering: "正在考虑",
  ready: "已准备",
  in_progress: "推进中",
  waiting: "等待中",
  paused: "已暂停",
  resuming: "正在恢复",
  completed: "已完成",
  abandoned: "已放弃",
  failed: "技术失败",
};

const EVENT_LABELS: Record<string, string> = {
  created: "建立活动",
  engage: "投入注意",
  progress: "取得进展",
  wait: "开始等待",
  pause: "暂停活动",
  resume: "恢复活动",
  complete: "完成活动",
  abandon: "放弃活动",
  system_fail: "技术失败",
  no_action: "本轮不行动",
  defer: "延后考虑",
  need_information: "需要更多信息",
};

export function ActivityPanel({
  token,
  environmentId,
  creatorPartyId,
  onUnauthorized,
}: ActivityPanelProps) {
  const queryClient = useQueryClient();
  const [selectedActivityId, setSelectedActivityId] = useState<string | null>(
    null,
  );
  const listKey = ["activities", environmentId, creatorPartyId] as const;
  const activities = useInfiniteQuery({
    queryKey: listKey,
    queryFn: ({ signal, pageParam }) =>
      getCreatorActivities(token, 50, pageParam, signal),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
  });
  const timelineKey = [
    "activity-timeline",
    environmentId,
    creatorPartyId,
    selectedActivityId,
  ] as const;
  const timeline = useInfiniteQuery({
    queryKey: timelineKey,
    queryFn: ({ signal, pageParam }) =>
      getCreatorActivityTimeline(
        token,
        selectedActivityId!,
        50,
        pageParam,
        signal,
      ),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    enabled: selectedActivityId !== null,
  });
  const activityItems =
    activities.data?.pages.flatMap((page) => page.items) ?? [];
  const timelineItems =
    timeline.data?.pages.flatMap((page) => page.items) ?? [];

  useEffect(() => {
    if (
      (activities.error instanceof ApiFailure &&
        activities.error.status === 401) ||
      (timeline.error instanceof ApiFailure && timeline.error.status === 401)
    ) {
      onUnauthorized();
    }
  }, [activities.error, onUnauthorized, timeline.error]);

  return (
    <section
      className="authority-panel activity-panel"
      aria-labelledby="activity-heading"
    >
      <div className="panel-heading-row">
        <div>
          <p className="eyebrow">自主生活</p>
          <h2 id="activity-heading">当前 Activity</h2>
        </div>
        <button
          type="button"
          className="secondary"
          onClick={() => {
            void queryClient.resetQueries({ queryKey: listKey, exact: true });
            if (selectedActivityId !== null) {
              void queryClient.resetQueries({
                queryKey: timelineKey,
                exact: true,
              });
            }
          }}
        >
          刷新
        </button>
      </div>
      {activities.isPending ? <p role="status">正在读取活动</p> : null}
      {activities.isError ? <p role="status">当前无法读取 Activity。</p> : null}
      {activities.data !== undefined && activityItems.length === 0 ? (
        <p className="timeline-empty" role="status">
          当前没有已建立的 Activity
        </p>
      ) : null}
      {activityItems.length > 0 ? (
        <ol className="activity-list">
          {activityItems.map((activity) => (
            <li key={activity.activity_id}>
              <div className="activity-title-row">
                <strong>{activity.goal}</strong>
                {activity.is_focused ? (
                  <span className="activity-focus">当前焦点</span>
                ) : null}
              </div>
              <dl>
                <div>
                  <dt>状态</dt>
                  <dd>{STATUS_LABELS[activity.status] ?? activity.status}</dd>
                </div>
                {activity.progress_summary === null ? null : (
                  <div>
                    <dt>进度</dt>
                    <dd>{activity.progress_summary}</dd>
                  </div>
                )}
                {activity.waiting_summary === null ? null : (
                  <div>
                    <dt>等待</dt>
                    <dd>{activity.waiting_summary}</dd>
                  </div>
                )}
                {activity.resume_not_before === null ? null : (
                  <div>
                    <dt>最早恢复</dt>
                    <dd>{activity.resume_not_before}</dd>
                  </div>
                )}
                {activity.terminal_reason === null ? null : (
                  <div>
                    <dt>结束原因</dt>
                    <dd>{activity.terminal_reason}</dd>
                  </div>
                )}
              </dl>
              <button
                type="button"
                className="secondary"
                aria-pressed={selectedActivityId === activity.activity_id}
                onClick={() =>
                  setSelectedActivityId((current) =>
                    current === activity.activity_id
                      ? null
                      : activity.activity_id,
                  )
                }
              >
                {selectedActivityId === activity.activity_id
                  ? "收起活动记录"
                  : "查看活动记录"}
              </button>
              {selectedActivityId === activity.activity_id ? (
                <div className="activity-timeline" aria-live="polite">
                  {timeline.isPending ? (
                    <p role="status">正在读取活动记录</p>
                  ) : null}
                  {timeline.isError ? (
                    <p role="status">当前无法读取活动记录。</p>
                  ) : null}
                  {timeline.data !== undefined && timelineItems.length === 0 ? (
                    <p role="status">尚无活动变化记录。</p>
                  ) : null}
                  {timelineItems.length > 0 ? (
                    <ol>
                      {timelineItems.map((event) => (
                        <li key={event.event_id}>
                          <strong>
                            {EVENT_LABELS[event.event_kind] ?? event.event_kind}
                          </strong>
                          {event.summary === null ? null : (
                            <span>{event.summary}</span>
                          )}
                          <time dateTime={event.occurred_at}>
                            {event.occurred_at}
                          </time>
                        </li>
                      ))}
                    </ol>
                  ) : null}
                  {timeline.hasNextPage ? (
                    <button
                      type="button"
                      className="secondary"
                      disabled={timeline.isFetchingNextPage}
                      onClick={() => void timeline.fetchNextPage()}
                    >
                      {timeline.isFetchingNextPage
                        ? "正在加载"
                        : "加载更早记录"}
                    </button>
                  ) : null}
                </div>
              ) : null}
            </li>
          ))}
        </ol>
      ) : null}
      {activities.hasNextPage ? (
        <button
          type="button"
          className="secondary"
          disabled={activities.isFetchingNextPage}
          onClick={() => void activities.fetchNextPage()}
        >
          {activities.isFetchingNextPage ? "正在加载" : "加载更早记录"}
        </button>
      ) : null}
      <p className="boundary-note">
        这里是只读生活投影；改变注意和活动仍由 ARMI 自己决定。
      </p>
    </section>
  );
}
