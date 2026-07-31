import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";

import { ApiFailure, getCreatorOperation } from "../../api/client";

type OperationPanelProps = {
  token: string;
  operationRef: string | null;
  onUnauthorized: () => void;
};

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
            <dd>已耐久接纳</dd>
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
            <dd>
              {operation.data.waiting_for === "context_preparation"
                ? "正在准备 Context"
                : "Context 已准备，等待模型步骤"}
            </dd>
          </div>
          <div>
            <dt>责任引用</dt>
            <dd>{operation.data.result_ref}</dd>
          </div>
        </dl>
      ) : (
        <dl>
          <div>
            <dt>状态</dt>
            <dd>Context 准备失败</dd>
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
