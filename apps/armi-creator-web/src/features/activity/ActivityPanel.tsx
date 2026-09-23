import { useEffect, useRef, useState } from "react";
import {
  useInfiniteQuery,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import {
  ApiFailure,
  getCreatorActivities,
  getCreatorActivityTimeline,
  getAutonomyStatus,
  getAutonomyHistory,
} from "../../api/client";
import { OperationPanel } from "../operation/OperationPanel";
import { EffectDetail } from "../effect/EffectDetail";

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

const AUTONOMY_CATEGORIES = {
  continue_activity: "继续活动",
  explore: "探索与思考",
  communicate: "主动交流",
  reflect: "回顾与整理",
  wait: "暂不行动",
};

const AUTONOMY_LABELS: Record<string, string> = {
  not_initialized: "尚未建立自主计划",
  disabled: "自主生活未开启",
  runtime_stopped: "Runtime 已停止",
  sleeping: "睡眠维护中",
  blocked: "自主判断等待配置修正",
  thinking: "正在自主考虑",
  resource_busy: "等待认知资源",
  scheduled: "等待下次考虑时间",
  ready: "等待调度",
};

function localTime(value: string) {
  return new Date(value).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" });
}

const EVENT_LABELS: Record<string, string> = {
  created: "建立活动",
  admin_update: "管理员修改",
  admin_delete: "管理员删除",
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
  const [historyOpen, setHistoryOpen] = useState(false);
  const [operationRef, setOperationRef] = useState<string | null>(null);
  const [effectRef, setEffectRef] = useState<string | null>(null);
  const effectTriggerRef = useRef<HTMLButtonElement>(null);
  const autonomyKey = ["autonomy", environmentId, creatorPartyId] as const;
  const autonomy = useQuery({
    queryKey: autonomyKey,
    queryFn: ({ signal }) => getAutonomyStatus(token, signal),
    refetchInterval: 30_000,
  });
  const historyKey = [
    "autonomy-history",
    environmentId,
    creatorPartyId,
  ] as const;
  const history = useInfiniteQuery({
    queryKey: historyKey,
    queryFn: ({ signal, pageParam }) =>
      getAutonomyHistory(token, pageParam, signal),
    initialPageParam: 0,
    getNextPageParam: (page) =>
      page.offset + page.items.length < page.total
        ? page.offset + page.limit
        : undefined,
    enabled: historyOpen,
  });
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
      (timeline.error instanceof ApiFailure && timeline.error.status === 401) ||
      (autonomy.error instanceof ApiFailure && autonomy.error.status === 401) ||
      (history.error instanceof ApiFailure && history.error.status === 401)
    ) {
      onUnauthorized();
    }
  }, [
    activities.error,
    autonomy.error,
    history.error,
    onUnauthorized,
    timeline.error,
  ]);

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
            void queryClient.resetQueries({
              queryKey: autonomyKey,
              exact: true,
            });
            void queryClient.resetQueries({
              queryKey: historyKey,
              exact: true,
            });
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
      <section aria-label="自主计划">
        {autonomy.isPending ? <p role="status">正在读取自主计划</p> : null}
        {autonomy.isError ? <p role="status">当前无法读取自主计划。</p> : null}
        {autonomy.data ? (
          <>
            <h3>{AUTONOMY_LABELS[autonomy.data.state]}</h3>
            {autonomy.data.next_consideration_at ? (
              <p>
                下次检查时间：
                {localTime(
                  autonomy.data.effective_consideration_at ??
                    autonomy.data.next_consideration_at,
                )}
                （北京时间）
              </p>
            ) : null}
            {autonomy.data.policy ? (
              <p>
                主动出口：
                {autonomy.data.policy.outlet === "qq" ? "QQ" : "Creator 网页"}
              </p>
            ) : null}
            {autonomy.data.outlet_state &&
            autonomy.data.outlet_state !== "ready" ? (
              <p role="status">
                主动出口暂不可用：
                {autonomy.data.outlet_reason_code ?? autonomy.data.outlet_state}
                。仍可自主思考，不切换渠道。
              </p>
            ) : null}
            <p>
              当前阶段：
              {autonomy.data.phase === "check"
                ? "轻量判断"
                : autonomy.data.phase === "execute"
                  ? "完整认知"
                  : autonomy.data.phase === "blocked"
                    ? "等待配置修正"
                    : "等待"}
              ；正常检查间隔：60 秒；失败退避档位：
              {autonomy.data.failure_streak ?? 0}
            </p>
            <p>
              最近判断：
              {autonomy.data.last_engage == null
                ? "尚无判断"
                : autonomy.data.last_engage
                  ? "进入完整认知"
                  : "继续等待"}
            </p>
            {autonomy.data.blocked_reason_code ? (
              <p>{autonomy.data.blocked_reason_code}</p>
            ) : null}
            {Object.entries(autonomy.data.stage_usage ?? {}).map(
              ([stage, usage]) => (
                <p key={stage}>
                  {stage === "check" ? "轻判" : "完整认知"}：{usage.calls}{" "}
                  次调用，输入 {usage.input_tokens} / 输出 {usage.output_tokens}{" "}
                  tokens，累计 {(usage.elapsed_ms / 1000).toFixed(1)}{" "}
                  秒；用量或结果未知 {usage.unknown_calls} 次
                </p>
              ),
            )}
          </>
        ) : null}
        <button
          type="button"
          className="secondary"
          aria-expanded={historyOpen}
          onClick={() => setHistoryOpen(!historyOpen)}
        >
          {historyOpen ? "收起自主记录" : "查看自主记录"}
        </button>
        {historyOpen ? (
          <div aria-live="polite">
            {history.isPending ? <p role="status">正在读取自主记录</p> : null}
            {history.isError ? (
              <p role="status">当前无法读取自主记录。</p>
            ) : null}
            {history.data?.pages[0]?.total === 0 ? (
              <p>尚无自主机会记录。</p>
            ) : null}
            <ol>
              {history.data?.pages
                .flatMap((page) => page.items)
                .map((item) => (
                  <li key={item.operation_id}>
                    <time dateTime={item.available_after}>
                      {localTime(item.available_after)}
                    </time>
                    <p>
                      {item.stage === "check" &&
                      item.cognition_status === "completed"
                        ? "轻量判断已完成"
                        : item.effect_status === "unknown"
                          ? "发送结果未知"
                          : item.failure_code
                            ? "执行失败"
                            : item.effect_status
                              ? `表达交付：${item.effect_status}`
                              : item.final_disposition === "no_change" ||
                                  item.final_disposition === "no_action"
                                ? "本轮自主沉默"
                                : item.final_disposition === "defer"
                                  ? "本轮延期"
                                  : item.cognition_status === null
                                    ? "尚未开始认知"
                                    : item.current_disposition === "resolved"
                                      ? "本轮决定已结算"
                                      : "正在处理"}
                    </p>
                    {item.autonomy_category ? (
                      <p>自主方向：{AUTONOMY_CATEGORIES[item.autonomy_category]}</p>
                    ) : null}
                    {item.consideration_signals === null ? (
                      <p>本轮未记录考虑信号明细</p>
                    ) : item.consideration_signals ? (
                      <p>
                        纳入考虑的信号：
                        {item.consideration_signals.frozen_at
                          ? item.consideration_signals.signals.length
                          : "尚未冻结"}
                      </p>
                    ) : null}
                    {item.failure_code || item.resolution_reason_code ? (
                      <p>{item.failure_code ?? item.resolution_reason_code}</p>
                    ) : null}
                    <details>
                      <summary>操作引用</summary>
                      <code>{item.operation_id}</code>
                      <p>
                        同次自主机会：<code>{item.root_opportunity_id}</code>
                      </p>
                      {item.episode_id ? (
                        <p>
                          认知：<code>{item.episode_id}</code>
                        </p>
                      ) : null}
                    </details>
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => {
                        setOperationRef(item.root_opportunity_id);
                        setEffectRef(null);
                      }}
                    >
                      查看操作与用量
                    </button>
                  </li>
                ))}
            </ol>
            {history.hasNextPage ? (
              <button
                type="button"
                className="secondary"
                disabled={history.isFetchingNextPage}
                onClick={() => void history.fetchNextPage()}
              >
                加载更早自主记录
              </button>
            ) : null}
          </div>
        ) : null}
      </section>
      <OperationPanel
        token={token}
        operationRef={operationRef}
        onEffectSelected={setEffectRef}
        onUnauthorized={onUnauthorized}
        effectTriggerRef={effectTriggerRef}
      />
      <EffectDetail
        token={token}
        effectRef={effectRef}
        onUnauthorized={onUnauthorized}
        onClose={() => {
          setEffectRef(null);
          effectTriggerRef.current?.focus();
        }}
      />
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
