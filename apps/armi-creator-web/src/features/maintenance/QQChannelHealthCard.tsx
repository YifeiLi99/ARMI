import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";

import { ApiFailure, getQQChannelHealth } from "../../api/client";

type QQChannelHealthCardProps = {
  token: string;
  onUnauthorized: () => void;
};

const STATE_LABELS: Record<string, string> = {
  disabled: "未启用",
  starting: "正在启动",
  login_required: "等待 QQ 登录",
  ready: "可用",
  unavailable: "暂不可用",
  misconfigured: "配置不一致",
};

const REASON_LABELS: Record<string, string> = {
  NAPCAT_LOGIN_REQUIRED: "需要在 QQ 窗口完成登录或扫码。",
  NAPCAT_STATUS_UNHEALTHY: "NapCat 报告当前状态异常。",
  NAPCAT_ACCOUNT_MISMATCH: "当前登录账号与 ARMI 渠道配置不一致。",
  NAPCAT_HEALTH_AUTH_REJECTED: "NapCat API 凭据不一致。",
  NAPCAT_HEALTH_UNAVAILABLE: "无法连接本机 NapCat API。",
  NAPCAT_HEALTH_RESPONSE_INVALID: "NapCat 返回了无法识别的健康数据。",
  QQ_INGRESS_UNAVAILABLE: "ARMI 的 QQ 事件入口尚未就绪。",
};

function yesNo(value: boolean | null): string {
  return value === null ? "尚未确认" : value ? "是" : "否";
}

export function QQChannelHealthCard({
  token,
  onUnauthorized,
}: QQChannelHealthCardProps) {
  const health = useQuery({
    queryKey: ["qq-channel-health"],
    queryFn: ({ signal }) => getQQChannelHealth(token, signal),
    refetchInterval: 10_000,
  });

  useEffect(() => {
    if (health.error instanceof ApiFailure && health.error.status === 401) {
      onUnauthorized();
    }
  }, [health.error, onUnauthorized]);

  return (
    <section className="authority-panel" aria-labelledby="qq-health-heading">
      <div className="panel-heading-row">
        <div>
          <p className="eyebrow">外部渠道</p>
          <h2 id="qq-health-heading">QQ / NapCat</h2>
        </div>
        <button
          type="button"
          className="secondary"
          onClick={() => void health.refetch()}
        >
          刷新
        </button>
      </div>

      {health.isPending ? <p role="status">正在检查 QQ 渠道</p> : null}
      {health.isError ? <p role="status">当前无法检查 QQ 渠道。</p> : null}
      {health.data === undefined ? null : (
        <>
          <p className="maintenance-state" role="status">
            {STATE_LABELS[health.data.state] ?? health.data.state}
          </p>
          <dl>
            <div>
              <dt>ARMI 事件入口</dt>
              <dd>{health.data.ingress_ready ? "已就绪" : "未就绪"}</dd>
            </div>
            <div>
              <dt>NapCat API</dt>
              <dd>{health.data.api_reachable ? "可达" : "不可达"}</dd>
            </div>
            <div>
              <dt>QQ 在线</dt>
              <dd>{yesNo(health.data.account_online)}</dd>
            </div>
            <div>
              <dt>账号匹配</dt>
              <dd>{yesNo(health.data.account_matches)}</dd>
            </div>
            <div>
              <dt>最近检查</dt>
              <dd>{health.data.observed_at}</dd>
            </div>
          </dl>
          {(health.data.reason_codes ?? []).map((reason) => (
            <p className="field-note" key={reason}>
              {REASON_LABELS[reason] ?? `状态原因：${reason}`}
            </p>
          ))}
        </>
      )}
      <p className="boundary-note">
        QQ 渠道异常不会阻断 Creator；页面仅显示状态，不控制宿主进程。
      </p>
    </section>
  );
}
