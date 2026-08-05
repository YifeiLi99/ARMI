import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";

import {
  ApiFailure,
  decideCapabilityRequest,
  getCapabilityRequests,
} from "../../api/client";
import type { CapabilityDecision, CapabilityRequest } from "../../api/client";
import { createDecision } from "./decisionCommand";

type CapabilityInboxProps = {
  token: string;
  environmentId: string;
  creatorPartyId: string;
  onUnauthorized: () => void;
};

type PendingCommand = {
  requestId: string;
  body: CapabilityDecision;
};

function CapabilityItem({
  item,
  busy,
  onDecide,
}: {
  item: CapabilityRequest;
  busy: boolean;
  onDecide: (body: CapabilityDecision) => void;
}) {
  const [showLimit, setShowLimit] = useState(false);
  const [validForSeconds, setValidForSeconds] = useState(
    item.valid_for_seconds,
  );
  const [maxUses, setMaxUses] = useState(item.max_uses);
  const [maxPayloadBytes, setMaxPayloadBytes] = useState(
    item.max_payload_bytes ?? 1,
  );
  const [limitError, setLimitError] = useState<string | null>(null);
  const pending = item.status === "pending";
  const active = item.status === "granted" || item.status === "limited";
  const unavailable = item.capability_availability === "unavailable";
  const isCodex = item.capability_kind === "codex.delegated-work";
  const canLimit = isCodex
    ? item.valid_for_seconds > 60
    : item.valid_for_seconds > 60 ||
      item.max_uses > 1 ||
      (item.max_payload_bytes ?? 1) > 1;

  function submitLimit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const payloadLimit = item.max_payload_bytes;
    const narrows = isCodex
      ? validForSeconds < item.valid_for_seconds
      : validForSeconds < item.valid_for_seconds ||
        maxUses < item.max_uses ||
        (payloadLimit !== undefined && payloadLimit !== null
          ? maxPayloadBytes < payloadLimit
          : false);
    if (!narrows) {
      setLimitError("至少缩短有效期、次数或字节上限之一；不能扩大申请范围。");
      return;
    }
    setLimitError(null);
    onDecide(
      createDecision(item.request_version, "limit", {
        validForSeconds,
        ...(isCodex ? {} : { maxUses }),
        ...(isCodex || payloadLimit === undefined || payloadLimit === null
          ? {}
          : { maxPayloadBytes }),
      }),
    );
  }

  return (
    <li className="capability-item">
      <div className="capability-title-row">
        <strong>{item.capability_kind}</strong>
        <span>{item.status}</span>
      </div>
      <dl>
        <div>
          <dt>操作</dt>
          <dd>{item.operation}</dd>
        </div>
        <div>
          <dt>目的</dt>
          <dd>{item.purpose}</dd>
        </div>
        <div>
          <dt>对象</dt>
          <dd>主体 {item.subject_id}</dd>
        </div>
        <div>
          <dt>场景</dt>
          <dd>{item.scene_id}</dd>
        </div>
        {isCodex ? null : (
          <>
            <div>
              <dt>受众</dt>
              <dd>{item.audience_scope}</dd>
            </div>
            <div>
              <dt>数据范围</dt>
              <dd>{item.data_scope}</dd>
            </div>
          </>
        )}
        <div>
          <dt>申请上限</dt>
          <dd>
            授权后最多 {item.valid_for_seconds}s · {item.max_uses} 次
            {item.max_payload_bytes === undefined ||
            item.max_payload_bytes === null
              ? ""
              : ` · ${item.max_payload_bytes} bytes`}
          </dd>
        </div>
        {isCodex ? (
          <div>
            <dt>隔离范围</dt>
            <dd>
              {item.workspace_scope} · {item.artifact_scope} · 网络关闭
            </dd>
          </div>
        ) : null}
        <div>
          <dt>可用性</dt>
          <dd>{item.capability_availability}</dd>
        </div>
        <div>
          <dt>申请时间</dt>
          <dd>{item.created_at}</dd>
        </div>
        <div>
          <dt>状态更新时间</dt>
          <dd>{item.status_changed_at}</dd>
        </div>
        {item.resolution_reason_code === undefined ||
        item.resolution_reason_code === null ? null : (
          <div>
            <dt>安全原因</dt>
            <dd>{item.resolution_reason_code}</dd>
          </div>
        )}
        {item.effective_grant === undefined ||
        item.effective_grant === null ? null : (
          <>
            <div>
              <dt>实际 grant</dt>
              <dd>
                {item.effective_grant.status} · {item.effective_grant.grant_ref}
              </dd>
            </div>
            <div>
              <dt>剩余</dt>
              <dd>
                {item.effective_grant.remaining_uses}/
                {item.effective_grant.max_uses} 次 · 至{" "}
                {item.effective_grant.valid_until}
              </dd>
            </div>
            {item.effective_grant.ended_at === undefined ||
            item.effective_grant.ended_at === null ? null : (
              <div>
                <dt>终止时间</dt>
                <dd>{item.effective_grant.ended_at}</dd>
              </div>
            )}
            <div>
              <dt>最终字节限制</dt>
              <dd>
                {item.effective_grant.scope_kind === "creator_scene_reply"
                  ? item.effective_grant.max_payload_bytes
                  : "不适用"}
              </dd>
            </div>
            {item.effective_grant.scope_kind === "codex_delegated_work" ? (
              <div>
                <dt>Codex 隔离</dt>
                <dd>
                  {item.effective_grant.workspace_scope} ·{" "}
                  {item.effective_grant.artifact_scope} · 网络关闭
                </dd>
              </div>
            ) : null}
          </>
        )}
      </dl>
      {active ? (
        <p className="authority-note">
          当前 grant 只表示系统许可，不表示 ARMI
          想使用，也不表示现实效果已经发生。
        </p>
      ) : null}
      {item.status === "revoked" || item.status === "expired" ? (
        <p className="critical-note" role="status">
          {item.status === "revoked" ? "授权已撤回" : "授权已过期"}
          ：只阻止尚未派发的使用；已派发、已完成或结果未知的效果不会被改写，请从
          operation/effect 详情继续核验。
        </p>
      ) : null}
      {pending ? (
        <div className="decision-actions">
          {!unavailable ? (
            <>
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  onDecide(createDecision(item.request_version, "grant"))
                }
              >
                允许申请范围
              </button>
              {canLimit ? (
                <button
                  type="button"
                  className="secondary"
                  disabled={busy}
                  onClick={() => {
                    setLimitError(null);
                    setShowLimit((value) => !value);
                  }}
                >
                  设置更严格限制
                </button>
              ) : null}
            </>
          ) : null}
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={() =>
              onDecide(createDecision(item.request_version, "deny"))
            }
          >
            拒绝申请
          </button>
        </div>
      ) : null}
      {active ? (
        <button
          type="button"
          className="secondary"
          disabled={busy}
          onClick={() =>
            onDecide(createDecision(item.request_version, "revoke"))
          }
        >
          撤回当前 grant
        </button>
      ) : null}
      {showLimit && pending && !unavailable ? (
        <form className="limit-form" onSubmit={submitLimit}>
          <label>
            有效秒数
            <input
              type="number"
              min={60}
              max={item.valid_for_seconds}
              value={validForSeconds}
              onChange={(event) =>
                setValidForSeconds(event.currentTarget.valueAsNumber)
              }
            />
          </label>
          {isCodex ? null : (
            <label>
              最大次数
              <input
                type="number"
                min={1}
                max={item.max_uses}
                value={maxUses}
                onChange={(event) =>
                  setMaxUses(event.currentTarget.valueAsNumber)
                }
              />
            </label>
          )}
          {isCodex ||
          item.max_payload_bytes === undefined ||
          item.max_payload_bytes === null ? null : (
            <label>
              最大字节
              <input
                type="number"
                min={1}
                max={item.max_payload_bytes}
                value={maxPayloadBytes}
                onChange={(event) =>
                  setMaxPayloadBytes(event.currentTarget.valueAsNumber)
                }
              />
            </label>
          )}
          <button type="submit" disabled={busy}>
            应用更严格限制
          </button>
          {limitError === null ? null : (
            <p role="alert" className="form-error">
              {limitError}
            </p>
          )}
        </form>
      ) : null}
    </li>
  );
}

export function CapabilityInbox({
  token,
  environmentId,
  creatorPartyId,
  onUnauthorized,
}: CapabilityInboxProps) {
  const queryClient = useQueryClient();
  const queryKey = useMemo(
    () => ["capability-requests", environmentId, creatorPartyId] as const,
    [creatorPartyId, environmentId],
  );
  const [pendingCommand, setPendingCommand] = useState<PendingCommand | null>(
    null,
  );
  const [message, setMessage] = useState<string | null>(null);
  const requests = useInfiniteQuery({
    queryKey,
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) =>
      getCapabilityRequests(token, 50, pageParam, signal),
    getNextPageParam: (page) => page.next_cursor,
  });

  useEffect(() => {
    if (requests.error instanceof ApiFailure && requests.error.status === 401) {
      onUnauthorized();
    }
  }, [onUnauthorized, requests.error]);

  async function submit(command: PendingCommand): Promise<void> {
    setPendingCommand(command);
    setMessage(null);
    try {
      await decideCapabilityRequest(token, command.requestId, command.body);
      setPendingCommand(null);
      setMessage(
        command.body.decision === "revoke"
          ? "撤回决定已由 Runtime 应用；正在核验 grant 与相关效果的权威状态。"
          : "决定已由 Runtime 应用，正在重取权威状态。",
      );
      await queryClient.resetQueries({ queryKey, exact: true });
    } catch (error) {
      if (error instanceof ApiFailure && error.status === 401) {
        onUnauthorized();
        return;
      }
      if (error instanceof ApiFailure && error.status === 409) {
        setPendingCommand(null);
        setMessage("申请版本已变化，已丢弃旧决定并重取当前状态。");
        await queryClient.resetQueries({ queryKey, exact: true });
        return;
      }
      setMessage("决定结果尚未确认；可用同一决定身份核验重试。");
    }
  }

  const items =
    requests.data?.pages.flatMap((page) =>
      Array.isArray(page.items) ? page.items : [],
    ) ?? [];
  return (
    <section className="authority-panel" aria-labelledby="capability-heading">
      <div className="timeline-heading-row">
        <h2 id="capability-heading">Capability 申请</h2>
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
      {message === null ? null : (
        <p role="status" aria-live="polite">
          {message}
        </p>
      )}
      <p className="authority-note">
        这里处理的是系统权限，不替 ARMI
        决定是否使用能力；界面不会把授权或撤回当作效果完成。
      </p>
      {requests.isPending ? (
        <p role="status">正在读取权威申请</p>
      ) : requests.isError ? (
        <p role="status">当前无法核验 capability 申请。</p>
      ) : items.length === 0 ? (
        <p className="timeline-empty">当前没有 capability 申请</p>
      ) : (
        <ul className="capability-list">
          {items.map((item) => (
            <CapabilityItem
              key={item.capability_request_id}
              item={item}
              busy={pendingCommand !== null}
              onDecide={(body) =>
                void submit({ requestId: item.capability_request_id, body })
              }
            />
          ))}
        </ul>
      )}
      {pendingCommand === null ? null : (
        <button
          type="button"
          className="secondary"
          onClick={() => void submit(pendingCommand)}
        >
          核验同一决定
        </button>
      )}
      {requests.hasNextPage ? (
        <button
          type="button"
          disabled={requests.isFetchingNextPage}
          onClick={() => void requests.fetchNextPage()}
        >
          {requests.isFetchingNextPage ? "正在读取" : "加载更早申请"}
        </button>
      ) : null}
    </section>
  );
}
