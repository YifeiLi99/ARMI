import { useEffect } from "react";
import type { RefObject } from "react";
import { useQuery } from "@tanstack/react-query";

import { ApiFailure, getCreatorOperation } from "../../api/client";

type OperationPanelProps = {
  token: string;
  operationRef: string | null;
  onEffectSelected: (effectRef: string) => void;
  onUnauthorized: () => void;
  effectTriggerRef: RefObject<HTMLButtonElement | null>;
};

const waitingLabels = {
  context_preparation: "正在准备 Context",
  model_attempt: "Context 已准备，等待模型步骤",
  model_response: "正在等待模型响应",
  candidate_validation: "正在校验认知候选",
  subject_commit: "候选已校验，等待主体提交",
  future_opportunity: "已暂缓，等待未来机会",
  new_evidence: "需要新的证据",
  effect_dispatch: "效果已登记，正在等待接收与核验",
  codex_dispatch: "Codex 效果已登记，正在等待受限执行",
  codex_verification: "Codex 执行结束，正在核验结果",
  codex_result_acceptance: "Codex 结果已保存，ARMI 正在处理后续认知和回复",
} as const;

const operationKindLabels = {
  cognition: "认知",
  subject_change: "主体变化",
  creator_response: "Creator 回应",
  other_human_response: "其他人回应",
  codex_delegation: "Codex 委托",
  formal_dialogue: "正式对话决定",
} as const;

export function OperationPanel({
  token,
  operationRef,
  onEffectSelected,
  onUnauthorized,
  effectTriggerRef,
}: OperationPanelProps) {
  const operation = useQuery({
    queryKey: ["creator-operation", operationRef],
    enabled: operationRef !== null,
    queryFn: ({ signal }) => getCreatorOperation(token, operationRef!, signal),
    refetchInterval: (query) =>
      query.state.data?.status === "waiting" ? 2000 : false,
  });

  useEffect(() => {
    if (
      operation.error instanceof ApiFailure &&
      operation.error.status === 401
    ) {
      onUnauthorized();
    }
  }, [onUnauthorized, operation.error]);

  if (operationRef === null) {
    return null;
  }
  const data = operation.data;
  return (
    <section className="authority-panel" aria-labelledby="operation-heading">
      <div className="timeline-heading-row">
        <h2 id="operation-heading">Operation</h2>
        <button
          type="button"
          className="secondary"
          onClick={() => void operation.refetch()}
        >
          刷新
        </button>
      </div>
      {operation.isPending ? (
        <p role="status">正在核验 operation</p>
      ) : operation.isError || data === undefined ? (
        <p role="status">当前无法核验这项 operation。</p>
      ) : (
        <>
          <dl>
            <div>
              <dt>合同状态</dt>
              <dd>{data.status}</dd>
            </div>
            <div>
              <dt>阶段</dt>
              <dd>{data.details.stage}</dd>
            </div>
            <div>
              <dt>结果</dt>
              <dd>{data.details.outcome}</dd>
            </div>
            <div>
              <dt>行动类型</dt>
              <dd>{operationKindLabels[data.details.operation_kind]}</dd>
            </div>
            {data.status === "waiting" ? (
              <div>
                <dt>等待</dt>
                <dd>{waitingLabels[data.waiting_for]}</dd>
              </div>
            ) : null}
            {data.status === "applied" ? (
              <div>
                <dt>权威版本</dt>
                <dd>{data.state_version}</dd>
              </div>
            ) : null}
            {data.status === "rejected" ||
            data.status === "unavailable" ||
            data.status === "failed" ? (
              <div>
                <dt>安全错误码</dt>
                <dd>{data.error.code}</dd>
              </div>
            ) : null}
            {data.status === "unknown" ? (
              <div className="critical-state">
                <dt>核验责任</dt>
                <dd>{data.verification_action}</dd>
              </div>
            ) : null}
            <div>
              <dt>Operation</dt>
              <dd>{data.details.operation_ref}</dd>
            </div>
            {data.details.intent_ref ? (
              <div>
                <dt>Intent</dt>
                <dd>{data.details.intent_ref}</dd>
              </div>
            ) : null}
            {data.details.effect_attempt_ref ? (
              <div>
                <dt>当前 Effect Attempt</dt>
                <dd>
                  {data.details.effect_attempt_no} ·{" "}
                  {data.details.effect_dispatch_state} ·{" "}
                  {data.details.effect_attempt_ref}
                </dd>
              </div>
            ) : null}
            {data.details.effect_observation_ref ? (
              <div>
                <dt>现实观察</dt>
                <dd>
                  {data.details.effect_observation_conclusion} ·{" "}
                  {data.details.effect_observation_reliability} ·{" "}
                  {data.details.effect_observation_ref}
                </dd>
              </div>
            ) : null}
            {data.details.owner_reason ? (
              <div>
                <dt>Owner 原因</dt>
                <dd>{data.details.owner_reason}</dd>
              </div>
            ) : null}
            {data.details.codex_execution ? (
              <>
                <div>
                  <dt>Codex 执行状态</dt>
                  <dd>
                    {data.details.codex_execution.execution_status ?? "待核验"}
                  </dd>
                </div>
                <div>
                  <dt>后续处理</dt>
                  <dd>
                    {data.details.codex_execution.result_processing_phase ??
                      "尚未开始"}
                  </dd>
                </div>
                {data.details.codex_execution.result_processing_reason ? (
                  <div>
                    <dt>后续处理原因</dt>
                    <dd>
                      {data.details.codex_execution.result_processing_reason}
                    </dd>
                  </div>
                ) : null}
                <div>
                  <dt>Codex Task Source</dt>
                  <dd>{data.details.codex_execution.task_source_ref}</dd>
                </div>
                <div>
                  <dt>Validator</dt>
                  <dd>{data.details.codex_execution.validator_id}</dd>
                </div>
                {data.details.codex_execution.model_id ? (
                  <div>
                    <dt>Codex Model</dt>
                    <dd>{data.details.codex_execution.model_id}</dd>
                  </div>
                ) : null}
                {data.details.codex_execution.final_tree_digest ? (
                  <div>
                    <dt>Final Tree</dt>
                    <dd>{data.details.codex_execution.final_tree_digest}</dd>
                  </div>
                ) : null}
              </>
            ) : null}
          </dl>
          {data.status === "failed" &&
          data.error.code === "DEPENDENCY_RUNTIME_INTERRUPTED" ? (
            <p className="authority-note" role="status">
              本轮对话因 Runtime
              中断已结束。已提交的变化保留，未完成的回复不会补发；可以开始新的对话。
            </p>
          ) : null}
          {data.details.effect_ref === undefined ||
          data.details.effect_ref === null ? null : (
            <button
              ref={effectTriggerRef}
              type="button"
              onClick={() => onEffectSelected(data.details.effect_ref!)}
            >
              查看效果详情
            </button>
          )}
          {data.details.stage === "dispatching" ? (
            <p className="critical-note" role="status">
              {data.details.operation_kind === "codex_delegation"
                ? "委托正在执行；中断后不会重跑，实际结果按核验记录保留。"
                : "回复正在发送，最终结果以实际回执为准。"}
            </p>
          ) : null}
          {data.details.stage === "cancelled" ? (
            <p className="authority-note" role="status">
              Runtime 已确认效果在派发前取消；历史责任链仍保留。
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}
