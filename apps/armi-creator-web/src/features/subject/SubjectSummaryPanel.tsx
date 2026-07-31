import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";

import { ApiFailure, getSubjectSummary } from "../../api/client";

type SubjectSummaryPanelProps = {
  token: string;
  onUnauthorized: () => void;
};

export function SubjectSummaryPanel({
  token,
  onUnauthorized,
}: SubjectSummaryPanelProps) {
  const summary = useQuery({
    queryKey: ["subject-summary"],
    queryFn: ({ signal }) => getSubjectSummary(token, signal),
  });

  useEffect(() => {
    if (summary.error instanceof ApiFailure && summary.error.status === 401) {
      onUnauthorized();
    }
  }, [onUnauthorized, summary.error]);

  return (
    <section
      className="operation-panel"
      aria-labelledby="subject-summary-heading"
    >
      <div className="timeline-heading-row">
        <h2 id="subject-summary-heading">主体版本</h2>
        <button
          type="button"
          className="secondary"
          onClick={() => void summary.refetch()}
        >
          重新核验
        </button>
      </div>
      {summary.isPending ? (
        <p role="status">正在核验主体版本</p>
      ) : summary.isError ? (
        <p role="status">当前无法核验主体版本。</p>
      ) : (
        <dl>
          <div>
            <dt>权威版本</dt>
            <dd>{summary.data.subject_version}</dd>
          </div>
          <div>
            <dt>内容可见性</dt>
            <dd>私密</dd>
          </div>
          {summary.data.components.map((component) => (
            <div key={component.kind}>
              <dt>{component.kind}</dt>
              <dd>
                v{component.version} · {component.schema_version}
              </dd>
            </div>
          ))}
          {summary.data.latest_commit_ref === undefined ||
          summary.data.latest_commit_ref === null ? null : (
            <div>
              <dt>最新提交</dt>
              <dd>{summary.data.latest_commit_ref}</dd>
            </div>
          )}
        </dl>
      )}
    </section>
  );
}
