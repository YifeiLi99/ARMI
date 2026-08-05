import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  ApiFailure,
  expressCreatorRelationshipBoundary,
  getCreatorRelationshipCurrent,
  getCreatorRelationshipTimeline,
  type CreatorRelationshipBoundary,
} from "../../api/client";
import { createCreatorInputKey } from "../scene/messageIntent";

type RelationshipPanelProps = {
  token: string;
  environmentId: string;
  creatorPartyId: string;
  onUnauthorized: () => void;
  onOperationAccepted: (operationRef: string) => void;
};

type BoundaryKind = CreatorRelationshipBoundary["kind"];
type BoundaryAction = CreatorRelationshipBoundary["action"];

const PARTY_LABELS: Record<string, string> = {
  subject: "ARMI",
  other: "Creator",
};

const KIND_LABELS: Record<string, string> = {
  contact: "联系",
  address: "称呼",
  privacy: "隐私",
  disclosure: "信息披露",
  exit: "结束联系",
};

const ACTION_LABELS: Record<string, string> = {
  refuse: "拒绝",
  restrict: "限制",
  end_contact: "结束联系",
};

const COMMITMENT_STATUS_LABELS: Record<string, string> = {
  active: "进行中",
  fulfilled: "已履行",
  withdrawn: "已撤回",
  forgotten: "已遗忘",
  violated: "已违反",
};

const EVENT_LABELS: Record<string, string> = {
  established: "建立承诺",
  modified: "修改承诺",
  fulfilled: "履行承诺",
  withdrawn: "撤回承诺",
  forgotten: "遗忘承诺",
  violated: "违反承诺",
  conflict_noted: "记录冲突",
};

export function RelationshipPanel({
  token,
  environmentId,
  creatorPartyId,
  onUnauthorized,
  onOperationAccepted,
}: RelationshipPanelProps) {
  const queryClient = useQueryClient();
  const [showTimeline, setShowTimeline] = useState(false);
  const [kind, setKind] = useState<BoundaryKind>("contact");
  const [action, setAction] = useState<BoundaryAction>("restrict");
  const [summary, setSummary] = useState("");
  const [submittedMessage, setSubmittedMessage] = useState<string | null>(null);

  const currentKey = [
    "relationship-current",
    environmentId,
    creatorPartyId,
  ] as const;
  const current = useQuery({
    queryKey: currentKey,
    queryFn: ({ signal }) => getCreatorRelationshipCurrent(token, signal),
  });
  const relationshipId = current.data?.relationship?.relationship_id ?? null;
  const timelineKey = [
    "relationship-timeline",
    environmentId,
    creatorPartyId,
    relationshipId,
  ] as const;
  const timeline = useQuery({
    queryKey: timelineKey,
    queryFn: ({ signal }) =>
      getCreatorRelationshipTimeline(token, relationshipId!, signal),
    enabled: showTimeline && relationshipId !== null,
  });

  const boundary = useMutation({
    mutationFn: (request: CreatorRelationshipBoundary) =>
      expressCreatorRelationshipBoundary(
        token,
        createCreatorInputKey(),
        request,
      ),
    onSuccess: async (operation) => {
      setSummary("");
      setSubmittedMessage("边界表达已进入正式对话处理。");
      onOperationAccepted(operation.result_ref);
      await queryClient.resetQueries({
        predicate: (query) =>
          ["relationship-current", "relationship-timeline"].includes(
            String(query.queryKey[0]),
          ),
      });
    },
  });

  useEffect(() => {
    if (
      (current.error instanceof ApiFailure && current.error.status === 401) ||
      (timeline.error instanceof ApiFailure && timeline.error.status === 401) ||
      (boundary.error instanceof ApiFailure && boundary.error.status === 401)
    ) {
      onUnauthorized();
    }
  }, [boundary.error, current.error, onUnauthorized, timeline.error]);

  function submitBoundary(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const exactSummary = summary.trim();
    if (exactSummary === "") {
      setSubmittedMessage("请填写边界的具体说明。");
      return;
    }
    setSubmittedMessage(null);
    boundary.mutate({
      contract_version: "1.0",
      kind,
      action,
      summary: exactSummary,
    });
  }

  const revision = current.data?.relationship?.current;

  return (
    <section
      className="authority-panel relationship-panel"
      aria-labelledby="relationship-heading"
    >
      <div className="panel-heading-row">
        <div>
          <p className="eyebrow">关系、边界与承诺</p>
          <h2 id="relationship-heading">当前关系</h2>
        </div>
        <button
          type="button"
          className="secondary"
          onClick={() =>
            void queryClient.resetQueries({ queryKey: currentKey })
          }
        >
          刷新
        </button>
      </div>

      <p className="boundary-note">
        这里只显示获准的结构化关系事实与当前表达，不显示隐藏推理、其他场景原文或管理观察。
      </p>
      {current.isPending ? <p role="status">正在读取当前关系</p> : null}
      {current.isError ? <p role="status">当前无法读取关系。</p> : null}
      {current.data?.relationship === null ? (
        <p className="timeline-empty" role="status">
          当前还没有形成关系理解；仍可在下方表达第一项边界。
        </p>
      ) : null}

      {revision === undefined ? null : (
        <div className="relationship-current">
          <div className="relationship-state-row">
            <strong>{revision.interpretation}</strong>
            <span>
              {revision.status === "active" ? "关系进行中" : "关系已结束"}
            </span>
          </div>
          <ul className="relationship-facts" aria-label="关系事实">
            {revision.facts.map((fact, index) => (
              <li key={`${fact.kind}:${index}`}>{fact.summary}</li>
            ))}
          </ul>

          <h3>当前边界</h3>
          {revision.boundaries.length === 0 ? (
            <p className="timeline-empty">当前没有已形成的边界。</p>
          ) : (
            <ul className="relationship-list">
              {revision.boundaries.map((item) => (
                <li key={`${item.party_role}:${item.kind}`}>
                  <strong>
                    {PARTY_LABELS[item.party_role]} · {KIND_LABELS[item.kind]} ·{" "}
                    {ACTION_LABELS[item.action]}
                  </strong>
                  <span>{item.summary}</span>
                </li>
              ))}
            </ul>
          )}

          <h3>当前承诺</h3>
          {revision.commitments.length === 0 ? (
            <p className="timeline-empty">当前没有承诺。</p>
          ) : (
            <ul className="relationship-list">
              {revision.commitments.map((item) => (
                <li key={item.commitment_id}>
                  <strong>
                    {PARTY_LABELS[item.party_role]} ·{" "}
                    {COMMITMENT_STATUS_LABELS[item.status]}
                  </strong>
                  <span>{item.content}</span>
                  <small>{item.last_event_summary}</small>
                </li>
              ))}
            </ul>
          )}

          {revision.open_issues.length === 0 ? null : (
            <div className="relationship-issues">
              <h3>未解决冲突</h3>
              <ul className="relationship-list">
                {revision.open_issues.map((item) => (
                  <li key={item.issue_id}>
                    <strong>待处理</strong>
                    <span>{item.summary}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <button
            type="button"
            className="secondary"
            aria-pressed={showTimeline}
            onClick={() => setShowTimeline((value) => !value)}
          >
            {showTimeline ? "收起关系变化" : "查看关系变化"}
          </button>
          {showTimeline ? (
            <div className="relationship-timeline" aria-live="polite">
              {timeline.isPending ? (
                <p role="status">正在读取关系变化</p>
              ) : null}
              {timeline.isError ? (
                <p role="status">当前无法读取关系变化。</p>
              ) : null}
              {Array.isArray(timeline.data?.items) ? (
                <ol>
                  {timeline.data.items.map((item) => (
                    <li key={item.relationship_revision_id}>
                      <strong>第 {item.revision_no} 次关系表达</strong>
                      <span>{item.interpretation}</span>
                      {item.commitment_event === null ? null : (
                        <small>
                          {EVENT_LABELS[item.commitment_event.kind]}：
                          {item.commitment_event.summary}
                        </small>
                      )}
                      <time dateTime={item.occurred_at}>
                        {item.occurred_at}
                      </time>
                    </li>
                  ))}
                </ol>
              ) : null}
              {timeline.data?.truncated ? (
                <p className="boundary-note">仅显示最近 100 次关系修订。</p>
              ) : null}
            </div>
          ) : null}
        </div>
      )}

      <form className="relationship-boundary-form" onSubmit={submitBoundary}>
        <h3>表达 Creator 边界</h3>
        <p className="boundary-note">
          此操作把你的边界作为正式输入接纳；它不会直接改写 ARMI 的主观关系理解。
        </p>
        <div className="relationship-boundary-fields">
          <label>
            范围
            <select
              value={kind}
              onChange={(event) => {
                const next = event.target.value as BoundaryKind;
                setKind(next);
                if (next === "exit") {
                  setAction("end_contact");
                } else if (action === "end_contact") {
                  setAction("restrict");
                }
              }}
            >
              <option value="contact">联系</option>
              <option value="address">称呼</option>
              <option value="privacy">隐私</option>
              <option value="disclosure">信息披露</option>
              <option value="exit">结束联系</option>
            </select>
          </label>
          <label>
            要求
            <select
              value={action}
              onChange={(event) => {
                const next = event.target.value as BoundaryAction;
                setAction(next);
                if (next === "end_contact") {
                  setKind("exit");
                } else if (kind === "exit") {
                  setKind("contact");
                }
              }}
            >
              <option value="restrict">限制</option>
              <option value="refuse">拒绝</option>
              <option value="end_contact">结束联系</option>
            </select>
          </label>
        </div>
        <label>
          具体说明
          <textarea
            value={summary}
            maxLength={512}
            rows={3}
            onChange={(event) => setSummary(event.target.value)}
            placeholder="准确说明希望遵守的边界"
          />
        </label>
        <button type="submit" disabled={boundary.isPending}>
          {boundary.isPending ? "正在接纳" : "提交边界表达"}
        </button>
        {boundary.isError ? <p role="status">当前无法接纳边界表达。</p> : null}
        {submittedMessage === null ? null : (
          <p role="status">{submittedMessage}</p>
        )}
      </form>
    </section>
  );
}
