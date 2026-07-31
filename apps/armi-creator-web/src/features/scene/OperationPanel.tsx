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
      ) : (
        <dl>
          <div>
            <dt>状态</dt>
            <dd>{operation.data.status}</dd>
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
      )}
    </section>
  );
}
