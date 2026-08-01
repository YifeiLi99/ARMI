import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";

import { ApiFailure, getCreatorOperation } from "../../api/client";

type OperationPanelProps = {
  token: string;
  operationRef: string | null;
  onUnauthorized: () => void;
};

const waitingLabels = {
  context_preparation: "正在准备 Context",
  model_attempt: "Context 已准备，等待模型步骤",
  model_response: "正在等待模型响应",
  candidate_validation: "正在校验认知候选",
  subject_commit: "候选已校验，等待主体提交",
  future_opportunity: "已暂缓，等待未来机会",
  opportunity_available: "等待新的处理机会",
  new_evidence: "需要新的证据",
  creator_evidence_accepted: "等待 Creator 提供新证据",
  response_admission: "正在核验回应准入",
  effect_registration: "回应已接纳，正在登记效果账本",
  effect_dispatch: "效果已登记，正在等待接收与核验",
} as const;

export function OperationPanel({
  token,
  operationRef,
  onUnauthorized,
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

  return (
    <section className="operation-panel" aria-labelledby="operation-heading">
      <div className="timeline-heading-row">
        <h2 id="operation-heading">接纳责任</h2>
        <button
          type="button"
          className="secondary"
          onClick={() => void operation.refetch()}
        >
          刷新 operation
        </button>
      </div>
      {operation.isPending ? (
        <p role="status">正在核验接纳责任</p>
      ) : operation.isError ? (
        <p role="status">当前无法核验这项接纳责任。</p>
      ) : operation.data.status === "accepted" ? (
        <dl>
          <div>
            <dt>状态</dt>
            <dd>已登记，但尚未派发</dd>
          </div>
          <div>
            <dt>保管方</dt>
            <dd>{operation.data.custodian}</dd>
          </div>
          <div>
            <dt>责任引用</dt>
            <dd>{operation.data.result_ref}</dd>
          </div>
        </dl>
      ) : operation.data.status === "waiting" ? (
        <dl>
          <div>
            <dt>状态</dt>
            <dd>{waitingLabels[operation.data.waiting_for]}</dd>
          </div>
          <div>
            <dt>责任引用</dt>
            <dd>{operation.data.result_ref}</dd>
          </div>
        </dl>
      ) : operation.data.status === "rejected" ? (
        <dl>
          <div>
            <dt>状态</dt>
            <dd>认知候选已拒绝</dd>
          </div>
          <div>
            <dt>安全错误码</dt>
            <dd>{operation.data.error.code}</dd>
          </div>
        </dl>
      ) : operation.data.status === "applied" ? (
        <dl>
          <div>
            <dt>状态</dt>
            <dd>主体提交已应用</dd>
          </div>
          <div>
            <dt>权威版本</dt>
            <dd>{operation.data.state_version}</dd>
          </div>
        </dl>
      ) : operation.data.status === "completed" ? (
        <dl>
          <div>
            <dt>状态</dt>
            <dd>责任已完成并有耐久核验证据</dd>
          </div>
        </dl>
      ) : operation.data.status === "unknown" ? (
        <dl>
          <div>
            <dt>状态</dt>
            <dd>效果结果未知，等待权威接收端核验</dd>
          </div>
          <div>
            <dt>核验责任</dt>
            <dd>{operation.data.verification_action}</dd>
          </div>
        </dl>
      ) : (
        <dl>
          <div>
            <dt>状态</dt>
            <dd>认知准备失败</dd>
          </div>
          <div>
            <dt>安全错误码</dt>
            <dd>{operation.data.error.code}</dd>
          </div>
        </dl>
      )}
    </section>
  );
}
