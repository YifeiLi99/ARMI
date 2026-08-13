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
  response_admission: "正在核验回应准入",
  effect_registration: "回应已接纳，正在登记效果账本",
  effect_dispatch: "效果已登记，正在等待接收与核验",
  capability_decision: "Codex 委托正在等待创造者授权",
  codex_dispatch: "Codex 效果已登记，正在等待受限执行",
  codex_verification: "Codex 执行结束，正在核验结果",
  codex_result_acceptance: "Codex 结果已保管，正在等待主体接纳",
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
            {data.details.policy_decision_ref ? (
              <div>
                <dt>Policy</dt>
                <dd>{data.details.policy_decision_ref}</dd>
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
              效果已进入派发边界；撤回 grant 不会把在途事实改写为未发生。
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
