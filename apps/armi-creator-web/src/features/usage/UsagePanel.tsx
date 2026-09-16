import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ApiFailure,
  getUsageSummary,
  listUsageCalls,
  readUsageCall,
  type UsageFilters,
  type UsageCall,
} from "../../api/client";
import "./usage.css";

const units: Record<string, string> = {
  input_tokens: "输入 token",
  output_tokens: "输出 token",
  cached_input_tokens: "缓存 token",
  audio_milliseconds: "语音时长（毫秒）",
  text_characters: "合成字符",
  web_search_calls: "搜索次数",
};
const statuses: Record<string, string> = {
  estimated: "估算完整",
  partial: "部分估算",
  unpriced: "待计价",
  usage_unknown: "用量未确认",
  legacy: "旧口径",
  not_billable: "辅助请求",
  pending: "处理中",
  returned: "已返回",
  unknown: "结果未确认",
  failed: "失败",
};
export function money(value: number | null) {
  return value === null ? "未确认" : `¥${(value / 1_000_000).toFixed(6)}`;
}
function beijingDate(now = new Date()) {
  return new Date(now.getTime() + 8 * 3600_000).toISOString().slice(0, 10);
}
export function usageRange(
  period: "month" | "today" | "week",
  now = new Date(),
) {
  const end = beijingDate(now);
  const start =
    period === "month"
      ? `${end.slice(0, 7)}-01`
      : period === "week"
        ? beijingDate(new Date(now.getTime() - 6 * 86400_000))
        : end;
  return { start, end };
}
function filtersFor(
  start: string,
  end: string,
  extra: Record<string, string>,
): UsageFilters | null {
  if (
    !/^\d{4}-\d{2}-\d{2}$/.test(start) ||
    !/^\d{4}-\d{2}-\d{2}$/.test(end) ||
    start > end
  )
    return null;
  const next = new Date(`${end}T00:00:00+08:00`);
  if (!Number.isFinite(next.getTime())) return null;
  next.setTime(next.getTime() + 86400_000);
  return {
    start: `${start}T00:00:00+08:00`,
    end: next.toISOString(),
    ...extra,
  };
}
function UsageError({ error }: { error: unknown }) {
  return (
    <p role="alert">
      {error instanceof ApiFailure && [401, 403].includes(error.status)
        ? "没有权限读取用量记录，请重新建立 Creator 会话。"
        : "用量查询失败。请刷新重试；当前数值不代表完整统计。"}
    </p>
  );
}
function Quantities({ values }: { values: Record<string, number> }) {
  return (
    <span>
      {Object.entries(values)
        .map(
          ([unit, value]) =>
            `${units[unit] ?? unit}：${value.toLocaleString("zh-CN")}`,
        )
        .join(" · ") || "用量未确认"}
    </span>
  );
}

function CallDetail({
  token,
  callId,
  onOperation,
}: {
  token: string;
  callId: string;
  onOperation: (id: string) => void;
}) {
  const query = useQuery({
    queryKey: ["usage-call", callId],
    queryFn: ({ signal }) => readUsageCall(token, callId, signal),
  });
  if (query.isPending) return <p role="status">正在读取调用详情…</p>;
  if (query.isError) return <UsageError error={query.error} />;
  const call = query.data;
  const receipt = call.receipt;
  return (
    <div className="usage-detail">
      <dl>
        <dt>调用 ID</dt>
        <dd>{receipt.call_id}</dd>
        <dt>供应商请求 ID</dt>
        <dd>{receipt.provider_request_id ?? "未取得"}</dd>
        <dt>实际模型</dt>
        <dd>{receipt.response_model ?? "未取得"}</dd>
        <dt>业务结果</dt>
        <dd>{call.business_result ?? "尚未结算"}</dd>
        <dt>关联证据</dt>
        <dd>
          {call.reference_kind} / {call.reference_id}
        </dd>
        <dt>错误原因</dt>
        <dd>{receipt.error_code ?? "无已记录错误"}</dd>
        <dt>价格快照</dt>
        <dd>
          {receipt.price?.snapshot_id ??
            (call.historical_incomplete
              ? "保留历史原估算，旧记录不完整"
              : "没有匹配单价")}
        </dd>
        <dt>舍入规则</dt>
        <dd>
          {receipt.cost.rounding === "ceil_microyuan_per_component"
            ? "各分项向上取整到 0.000001 元"
            : "历史口径"}
        </dd>
      </dl>
      {receipt.price && (
        <p>
          <a href={receipt.price.source_url} target="_blank" rel="noreferrer">
            官方价格来源
          </a>{" "}
          · 核对时间：{receipt.price.verified_at}
        </p>
      )}
      {receipt.quantities.some(
        (item) => item.source === "local_measurement",
      ) && <p>包含本地测量估算，不是供应商结算用量。</p>}
      <ul>
        {receipt.cost.components.map((item) => (
          <li key={item.unit}>
            {units[item.unit] ?? item.unit}：{item.quantity} ×{" "}
            {money(item.price.microyuan)} / {item.price.per_quantity}
            {" = "}
            {money(item.estimated_microyuan)}
          </li>
        ))}
      </ul>
      {receipt.cost.missing_usage.length > 0 && (
        <p>
          缺少用量：
          {receipt.cost.missing_usage
            .map((unit) => units[unit] ?? unit)
            .join("、")}
        </p>
      )}
      {receipt.cost.missing_prices.length > 0 && (
        <p>
          缺少单价：
          {receipt.cost.missing_prices
            .map((unit) => units[unit] ?? unit)
            .join("、")}
        </p>
      )}
      {call.operation_id && (
        <button
          type="button"
          className="secondary"
          onClick={() => onOperation(call.operation_id!)}
        >
          打开原操作
        </button>
      )}
      {(call.auxiliary_requests ?? []).length > 0 && (
        <details>
          <summary>辅助请求（不重复计费）</summary>
          <ul>
            {call.auxiliary_requests?.map((item) => (
              <li key={item.call_id}>
                {item.service} · {statuses[item.outcome]} · 请求 ID：
                {item.provider_request_id ?? "未取得"} ·{" "}
                {item.error_code ?? "无已记录错误"}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

export function UsagePanel({
  token,
  onUnauthorized,
  onOperation,
}: {
  token: string;
  onUnauthorized: () => void;
  onOperation: (id: string) => void;
}) {
  const initial = usageRange("month");
  const [range, setRange] = useState(initial);
  const [extra, setExtra] = useState<Record<string, string>>({});
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const filters = filtersFor(range.start, range.end, extra);
  const summary = useQuery({
    queryKey: ["usage-summary", filters],
    enabled: filters !== null,
    queryFn: ({ signal }) => getUsageSummary(token, filters!, signal),
  });
  const calls = useQuery({
    queryKey: ["usage-calls", filters, offset],
    enabled: filters !== null,
    queryFn: ({ signal }) => listUsageCalls(token, filters!, offset, signal),
  });
  useEffect(() => {
    if (
      [summary.error, calls.error].some(
        (error) => error instanceof ApiFailure && error.status === 401,
      )
    )
      onUnauthorized();
  }, [summary.error, calls.error, onUnauthorized]);
  function changeFilter(key: string, value: string) {
    setExtra((previous) => ({ ...previous, [key]: value }));
    setOffset(0);
    setSelected(null);
  }
  const data = summary.data;
  const peak = Math.max(
    1,
    ...(data?.daily.map((day) => day.totals.known_microyuan ?? 0) ?? []),
  );
  function callRow(call: UsageCall) {
    const receipt = call.receipt;
    return (
      <li key={receipt.call_id} className="usage-call">
        <div className="usage-call-heading">
          <time dateTime={receipt.started_at}>
            {new Date(receipt.started_at).toLocaleString("zh-CN", {
              timeZone: "Asia/Shanghai",
            })}
          </time>
          <strong>{money(receipt.cost.known_microyuan)}</strong>
        </div>
        <p>
          {receipt.purpose} · {receipt.service} / {receipt.model}
        </p>
        <p>
          {statuses[receipt.outcome] ?? receipt.outcome} ·{" "}
          {statuses[receipt.cost.status] ?? receipt.cost.status}
        </p>
        <p>
          <Quantities
            values={Object.fromEntries(
              receipt.quantities.map((item) => [item.unit, item.quantity]),
            )}
          />
        </p>
        <button
          type="button"
          className="secondary"
          aria-expanded={selected === receipt.call_id}
          onClick={() =>
            setSelected(selected === receipt.call_id ? null : receipt.call_id)
          }
        >
          调用详情
        </button>
        {selected === receipt.call_id && (
          <CallDetail
            token={token}
            callId={selected}
            onOperation={onOperation}
          />
        )}
      </li>
    );
  }
  return (
    <section
      className="content-panel usage-panel"
      aria-labelledby="usage-heading"
    >
      <div className="timeline-heading-row">
        <h2 id="usage-heading">用量与费用</h2>
        <button
          type="button"
          className="secondary"
          disabled={filters === null}
          onClick={() => {
            void summary.refetch();
            void calls.refetch();
          }}
        >
          刷新
        </button>
      </div>
      <p>
        官方单价估算，不是云端实际扣款。日期按北京时间划分；Codex 订阅不折算为
        API 费用。
      </p>
      <div className="usage-filters">
        {(["month", "today", "week"] as const).map((period, index) => (
          <button
            key={period}
            type="button"
            className="secondary"
            onClick={() => {
              setRange(usageRange(period));
              setOffset(0);
            }}
          >
            {["本月", "今天", "近七天"][index]}
          </button>
        ))}
        <label>
          开始日期
          <input
            type="date"
            value={range.start}
            onChange={(event) => {
              setRange({ ...range, start: event.target.value });
              setOffset(0);
            }}
          />
        </label>
        <label>
          结束日期
          <input
            type="date"
            value={range.end}
            onChange={(event) => {
              setRange({ ...range, end: event.target.value });
              setOffset(0);
            }}
          />
        </label>
        <label>
          服务
          <select
            value={extra.service ?? ""}
            onChange={(event) => changeFilter("service", event.target.value)}
          >
            <option value="">全部</option>
            <option value="generation">模型生成</option>
            <option value="web_search">Web 搜索</option>
            <option value="asr">语音识别</option>
            <option value="tts">语音合成</option>
          </select>
        </label>
        <label>
          模型
          <input
            value={extra.model ?? ""}
            onChange={(event) => changeFilter("model", event.target.value)}
            placeholder="完整模型名称"
          />
        </label>
        <label>
          用途
          <input
            value={extra.purpose ?? ""}
            onChange={(event) => changeFilter("purpose", event.target.value)}
            placeholder="用途标识"
          />
        </label>
        <label>
          原操作 ID
          <input
            value={extra.operation_id ?? ""}
            onChange={(event) =>
              changeFilter("operation_id", event.target.value)
            }
            placeholder="可选的操作 UUID"
          />
        </label>
        <label>
          调用结果
          <select
            value={extra.outcome ?? ""}
            onChange={(event) => changeFilter("outcome", event.target.value)}
          >
            <option value="">全部</option>
            {["pending", "returned", "failed", "unknown"].map((value) => (
              <option key={value} value={value}>
                {statuses[value]}
              </option>
            ))}
          </select>
        </label>
        <label>
          计价状态
          <select
            value={extra.cost_status ?? ""}
            onChange={(event) =>
              changeFilter("cost_status", event.target.value)
            }
          >
            <option value="">全部</option>
            {[
              "estimated",
              "partial",
              "unpriced",
              "usage_unknown",
              "legacy",
            ].map((value) => (
              <option key={value} value={value}>
                {statuses[value]}
              </option>
            ))}
          </select>
        </label>
      </div>
      {filters === null ? (
        <p role="alert">请选择有效日期，结束日期不得早于开始日期。</p>
      ) : summary.isPending ? (
        <p role="status">正在汇总用量…</p>
      ) : summary.isError ? (
        <UsageError error={summary.error} />
      ) : (
        data && (
          <>
            <div className="usage-overview">
              <article>
                <span>收费请求</span>
                <strong>{data.totals.billable_calls}</strong>
              </article>
              <article>
                <span>已知估算费用</span>
                <strong>{money(data.totals.known_microyuan)}</strong>
              </article>
              <article>
                <span>已知输入 / 输出 / 缓存 token</span>
                <strong>
                  {data.units.input_tokens ?? "—"} /{" "}
                  {data.units.output_tokens ?? "—"} /{" "}
                  {data.units.cached_input_tokens ?? "—"}
                </strong>
              </article>
              <article>
                <span>用量未确认 / 待计价</span>
                <strong>
                  {data.totals.usage_unconfirmed_calls} /{" "}
                  {data.totals.unpriced_calls}
                </strong>
              </article>
            </div>
            {data.totals.incomplete_calls > 0 && (
              <p role="status">
                这里只是已知费用，另有 {data.totals.incomplete_calls}{" "}
                项未完整确认。
              </p>
            )}
            {data.totals.historical_incomplete_calls > 0 && (
              <p>
                包含 {data.totals.historical_incomplete_calls}{" "}
                项旧口径记录。历史覆盖不完整，未补造缺失调用，也未重算历史价格。
              </p>
            )}
            {data.totals.billable_calls === 0 ? (
              <p>所选范围暂无收费调用记录。</p>
            ) : (
              <>
                <h3>每日费用与用量</h3>
                <ul className="usage-trend">
                  {data.daily.map((day) => (
                    <li key={day.date}>
                      <div>
                        <time>{day.date}</time>
                        <strong>{money(day.totals.known_microyuan)}</strong>
                      </div>
                      <meter
                        min={0}
                        max={peak}
                        value={day.totals.known_microyuan ?? 0}
                        aria-label={`${day.date} 已知估算费用`}
                      />
                      <small>
                        <Quantities values={day.units} />
                      </small>
                    </li>
                  ))}
                </ul>
                <h3>服务与模型构成</h3>
                <ul>
                  {data.groups.map((group) => (
                    <li key={`${group.service}/${group.model}`}>
                      {group.service} / {group.model}：
                      {money(group.totals.known_microyuan)} ·{" "}
                      <Quantities values={group.units} />
                    </li>
                  ))}
                </ul>
              </>
            )}
          </>
        )
      )}
      <h3>调用明细</h3>
      {filters &&
        (calls.isPending ? (
          <p role="status">正在读取调用记录…</p>
        ) : calls.isError ? (
          <UsageError error={calls.error} />
        ) : (
          <>
            <ul className="usage-calls">{calls.data.items.map(callRow)}</ul>
            <nav className="usage-pagination" aria-label="用量记录分页">
              <button
                type="button"
                className="secondary"
                disabled={offset === 0}
                onClick={() => {
                  setOffset(Math.max(0, offset - 25));
                  setSelected(null);
                }}
              >
                上一页
              </button>
              <span>
                共 {calls.data.total} 条 · 第 {Math.floor(offset / 25) + 1} 页
              </span>
              <button
                type="button"
                className="secondary"
                disabled={offset + 25 >= calls.data.total}
                onClick={() => {
                  setOffset(offset + 25);
                  setSelected(null);
                }}
              >
                下一页
              </button>
            </nav>
          </>
        ))}
    </section>
  );
}
