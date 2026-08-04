import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  ApiFailure,
  getCreatorMaintenanceStatus,
  getCreatorMaintenanceTimeline,
  requestCreatorEmergencyWake,
} from "../../api/client";

type MaintenancePanelProps = {
  token: string;
  environmentId: string;
  creatorPartyId: string;
  onUnauthorized: () => void;
};

const PHASE_LABELS: Record<string, string> = {
  preparing: "技术准备",
  memory_maintenance: "记忆维护",
  self_check: "状态检查",
  life_quiet: "安静阶段",
  resume_check: "恢复检查",
  completed: "维护完成",
};

const RESULT_LABELS: Record<string, string> = {
  running: "正在维护",
  completed: "已完成",
  interrupted: "已安全中断",
  failed: "技术故障",
};

const TRANSITION_LABELS: Record<string, string> = {
  started: "建立维护会话",
  advanced: "进入下一阶段",
  completed: "维护完成",
  interrupted: "紧急唤醒后安全中断",
  system_failed: "维护发生技术故障",
};

export function MaintenancePanel({
  token,
  environmentId,
  creatorPartyId,
  onUnauthorized,
}: MaintenancePanelProps) {
  const queryClient = useQueryClient();
  const statusKey = [
    "maintenance-status",
    environmentId,
    creatorPartyId,
  ] as const;
  const status = useQuery({
    queryKey: statusKey,
    queryFn: ({ signal }) => getCreatorMaintenanceStatus(token, signal),
  });
  const session = status.data?.session ?? null;
  const timelineKey = [
    "maintenance-timeline",
    environmentId,
    creatorPartyId,
    session?.maintenance_session_id ?? null,
  ] as const;
  const timeline = useQuery({
    queryKey: timelineKey,
    queryFn: ({ signal }) =>
      getCreatorMaintenanceTimeline(
        token,
        session!.maintenance_session_id,
        signal,
      ),
    enabled: session !== null,
  });
  const wake = useMutation({
    mutationFn: (sessionId: string) =>
      requestCreatorEmergencyWake(token, sessionId),
    onSuccess: async () => {
      await queryClient.resetQueries({ queryKey: statusKey, exact: true });
      await queryClient.resetQueries({ queryKey: timelineKey, exact: true });
    },
  });

  useEffect(() => {
    if (
      (status.error instanceof ApiFailure && status.error.status === 401) ||
      (timeline.error instanceof ApiFailure && timeline.error.status === 401) ||
      (wake.error instanceof ApiFailure && wake.error.status === 401)
    ) {
      onUnauthorized();
    }
  }, [onUnauthorized, status.error, timeline.error, wake.error]);

  const active = session?.result_status === "running";
  const wakeAvailable = active && !session.wake_requested;
  const waitingInputCount = status.data?.waiting_input_count ?? 0;

  return (
    <section
      className="authority-panel maintenance-panel"
      aria-labelledby="maintenance-heading"
    >
      <div className="panel-heading-row">
        <div>
          <p className="eyebrow">睡眠与恢复</p>
          <h2 id="maintenance-heading">维护状态</h2>
        </div>
        <button
          type="button"
          className="secondary"
          onClick={() => {
            void queryClient.resetQueries({ queryKey: statusKey, exact: true });
            if (session !== null) {
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

      {status.isPending ? <p role="status">正在读取维护状态</p> : null}
      {status.isError ? <p role="status">当前无法读取维护状态。</p> : null}
      {status.data !== undefined && session === null ? (
        <p className="maintenance-state" role="status">
          当前没有进行中的睡眠维护
        </p>
      ) : null}

      {session === null ? null : (
        <div className="maintenance-session" aria-live="polite">
          <p className="maintenance-state" role="status">
            {RESULT_LABELS[session.result_status] ?? session.result_status} ·{" "}
            {PHASE_LABELS[session.phase] ?? session.phase}
          </p>
          <dl>
            <div>
              <dt>触发来源</dt>
              <dd>
                {session.trigger_kind === "subject_choice"
                  ? "ARMI 的睡眠决定"
                  : "系统最迟维护期限"}
              </dd>
            </div>
            <div>
              <dt>开始时间</dt>
              <dd>{session.started_at}</dd>
            </div>
            <div>
              <dt>最近变化</dt>
              <dd>{session.updated_at}</dd>
            </div>
            {session.finished_at === null ? null : (
              <div>
                <dt>结束时间</dt>
                <dd>{session.finished_at}</dd>
              </div>
            )}
          </dl>

          {active ? (
            <p className="field-note">
              普通消息仍会耐久接纳，并在恢复运行后继续处理。
              {waitingInputCount > 0
                ? ` 当前有 ${waitingInputCount} 条输入等待处理。`
                : ""}
            </p>
          ) : null}

          {session.wake_requested ? (
            <p role="status">紧急唤醒已登记，正在等待安全检查点。</p>
          ) : null}
          {wakeAvailable ? (
            <button
              type="button"
              disabled={wake.isPending}
              onClick={() => wake.mutate(session.maintenance_session_id)}
            >
              {wake.isPending ? "正在登记唤醒" : "紧急唤醒"}
            </button>
          ) : null}
          {wake.isError ? (
            <p role="status">
              {wake.error instanceof ApiFailure && wake.error.status === 409
                ? "维护状态已经变化，请刷新后确认。"
                : "当前无法登记紧急唤醒。"}
            </p>
          ) : null}

          <div className="maintenance-timeline">
            <h3>阶段记录</h3>
            {timeline.isPending ? <p role="status">正在读取阶段记录</p> : null}
            {timeline.isError ? (
              <p role="status">当前无法读取阶段记录。</p>
            ) : null}
            {timeline.data?.items.length === 0 ? (
              <p role="status">尚无阶段变化记录。</p>
            ) : null}
            {timeline.data !== undefined && timeline.data.items.length > 0 ? (
              <ol>
                {timeline.data.items.map((item) => (
                  <li key={item.revision_id}>
                    <strong>
                      {PHASE_LABELS[item.phase] ?? item.phase} ·{" "}
                      {RESULT_LABELS[item.result_status] ?? item.result_status}
                    </strong>
                    <span>
                      {TRANSITION_LABELS[item.transition_kind] ??
                        item.transition_kind}
                    </span>
                    <time dateTime={item.occurred_at}>{item.occurred_at}</time>
                  </li>
                ))}
              </ol>
            ) : null}
            {timeline.data?.truncated ? (
              <p className="field-note">这里只显示最近 100 条阶段记录。</p>
            ) : null}
          </div>
        </div>
      )}

      <p className="boundary-note">
        这里显示客观维护状态；紧急唤醒只恢复运行，不会强迫 ARMI 回应。
      </p>
    </section>
  );
}
