import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import {
  ApiFailure,
  getCreatorMemories,
  getCreatorMemoryTimeline,
  type LifeRecordKind,
  queryCreatorLifeRecords,
} from "../../api/client";

type MemoryPanelProps = {
  token: string;
  environmentId: string;
  creatorPartyId: string;
  onUnauthorized: () => void;
};

const RECORD_LABELS: Record<string, string> = {
  activity: "Activity",
  conversation: "对话经历",
  material: "生活资料",
  memory: "主观记忆",
  self_change: "自我变化",
};

const ACCESSIBILITY_LABELS: Record<string, string> = {
  available: "可自然回忆",
  faded: "较模糊",
  forgotten: "当前无法自然回忆",
};

const REVISION_LABELS: Record<string, string> = {
  formed: "形成",
  recalled: "回忆",
  faded: "淡忘",
  forgotten: "遗忘",
  reinterpreted: "重新理解",
};

const RELATION_LABELS: Record<string, string> = {
  supports: "支持另一项记忆",
  contradicts: "与另一项记忆矛盾",
  reinterprets: "重新解释另一项记忆",
};

export function MemoryPanel({
  token,
  environmentId,
  creatorPartyId,
  onUnauthorized,
}: MemoryPanelProps) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState("");
  const [queryText, setQueryText] = useState<string | undefined>(undefined);
  const [kind, setKind] = useState<LifeRecordKind | undefined>(undefined);
  const [draftKind, setDraftKind] = useState<LifeRecordKind | "">("");
  const [lifeCursor, setLifeCursor] = useState<string | undefined>(undefined);
  const [memoryCursor, setMemoryCursor] = useState<string | undefined>(
    undefined,
  );
  const [selectedMemoryId, setSelectedMemoryId] = useState<string | null>(null);
  const [timelineCursor, setTimelineCursor] = useState<string | undefined>(
    undefined,
  );

  const lifeKey = [
    "life-records",
    environmentId,
    creatorPartyId,
    kind ?? "all",
    queryText ?? "",
    lifeCursor ?? "first",
  ] as const;
  const lifeRecords = useQuery({
    queryKey: lifeKey,
    queryFn: ({ signal }) =>
      queryCreatorLifeRecords(token, 20, kind, queryText, lifeCursor, signal),
  });

  const memoryKey = [
    "memories",
    environmentId,
    creatorPartyId,
    memoryCursor ?? "first",
  ] as const;
  const memories = useQuery({
    queryKey: memoryKey,
    queryFn: ({ signal }) =>
      getCreatorMemories(token, 20, undefined, memoryCursor, signal),
  });

  const timelineKey = [
    "memory-timeline",
    environmentId,
    creatorPartyId,
    selectedMemoryId,
    timelineCursor ?? "first",
  ] as const;
  const timeline = useQuery({
    queryKey: timelineKey,
    queryFn: ({ signal }) =>
      getCreatorMemoryTimeline(
        token,
        selectedMemoryId!,
        20,
        timelineCursor,
        signal,
      ),
    enabled: selectedMemoryId !== null,
  });

  useEffect(() => {
    if (
      (lifeRecords.error instanceof ApiFailure &&
        lifeRecords.error.status === 401) ||
      (memories.error instanceof ApiFailure && memories.error.status === 401) ||
      (timeline.error instanceof ApiFailure && timeline.error.status === 401)
    ) {
      onUnauthorized();
    }
  }, [lifeRecords.error, memories.error, onUnauthorized, timeline.error]);

  return (
    <section
      className="authority-panel memory-panel"
      aria-labelledby="memory-heading"
    >
      <div className="panel-heading-row">
        <div>
          <p className="eyebrow">生活与记忆</p>
          <h2 id="memory-heading">精确查询</h2>
        </div>
        <button
          type="button"
          className="secondary"
          onClick={() => {
            void queryClient.resetQueries({
              predicate: (query) =>
                ["life-records", "memories", "memory-timeline"].includes(
                  String(query.queryKey[0]),
                ),
            });
          }}
        >
          刷新
        </button>
      </div>

      <form
        className="memory-search"
        onSubmit={(event) => {
          event.preventDefault();
          const next = draft.trim();
          setQueryText(next === "" ? undefined : next);
          setKind(draftKind === "" ? undefined : draftKind);
          setLifeCursor(undefined);
        }}
      >
        <label>
          查询生活记录
          <input
            value={draft}
            maxLength={1024}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="输入名称、主题或内容"
          />
        </label>
        <label>
          范围
          <select
            value={draftKind}
            onChange={(event) =>
              setDraftKind(event.target.value as LifeRecordKind | "")
            }
          >
            <option value="">全部已接入记录</option>
            <option value="activity">Activity</option>
            <option value="conversation">对话经历</option>
            <option value="material">生活资料</option>
            <option value="memory">主观记忆</option>
            <option value="relationship">关系理解</option>
            <option value="self_change">自我变化</option>
          </select>
        </label>
        <button type="submit">查询</button>
      </form>

      <p className="boundary-note">
        这里返回的是本次从权威生活记录取得的证据，不等于 ARMI 一直记得。
      </p>
      {lifeRecords.isPending ? <p role="status">正在查询生活记录</p> : null}
      {lifeRecords.isError ? <p role="status">当前无法查询生活记录。</p> : null}
      {lifeRecords.data?.items?.length === 0 ? (
        <p className="timeline-empty" role="status">
          没有匹配的生活记录
        </p>
      ) : null}
      {Array.isArray(lifeRecords.data?.items) &&
      lifeRecords.data.items.length > 0 ? (
        <ol className="life-record-list">
          {lifeRecords.data.items.map((item) => (
            <li key={`${item.record_kind}:${item.record_ref}`}>
              <div className="memory-title-row">
                <strong>{RECORD_LABELS[item.record_kind]}</strong>
                <span>本次查询取得</span>
              </div>
              <p>{item.summary}</p>
              {item.record_kind === "memory" ? (
                <small>
                  {item.naturally_recallable
                    ? "当前也可自然回忆"
                    : "当前无法自然回忆"}
                </small>
              ) : null}
              <time dateTime={item.occurred_at}>{item.occurred_at}</time>
            </li>
          ))}
        </ol>
      ) : null}
      {lifeRecords.data?.next_cursor !== null &&
      lifeRecords.data?.next_cursor !== undefined ? (
        <button
          type="button"
          className="secondary"
          onClick={() =>
            setLifeCursor(lifeRecords.data?.next_cursor ?? undefined)
          }
        >
          更早的查询结果
        </button>
      ) : null}

      <div className="memory-section-heading">
        <h3>主观记忆</h3>
        <span>只读 current head</span>
      </div>
      {memories.isPending ? <p role="status">正在读取记忆</p> : null}
      {memories.isError ? <p role="status">当前无法读取记忆。</p> : null}
      {memories.data?.items?.length === 0 ? (
        <p className="timeline-empty" role="status">
          当前还没有形成主观记忆
        </p>
      ) : null}
      {Array.isArray(memories.data?.items) && memories.data.items.length > 0 ? (
        <ol className="memory-list">
          {memories.data.items.map((memory) => (
            <li key={memory.memory_id}>
              <div className="memory-title-row">
                <strong>{memory.summary}</strong>
                <span>{ACCESSIBILITY_LABELS[memory.accessibility]}</span>
              </div>
              <p>
                来源：{memory.source_kind} · {memory.source_fact_class}
              </p>
              {memory.uncertainty === null ? null : (
                <p>不确定性：{memory.uncertainty}</p>
              )}
              <button
                type="button"
                className="secondary"
                aria-pressed={selectedMemoryId === memory.memory_id}
                onClick={() => {
                  setTimelineCursor(undefined);
                  setSelectedMemoryId((current) =>
                    current === memory.memory_id ? null : memory.memory_id,
                  );
                }}
              >
                {selectedMemoryId === memory.memory_id
                  ? "收起记忆变化"
                  : "查看记忆变化"}
              </button>
              {selectedMemoryId === memory.memory_id ? (
                <div className="memory-timeline" aria-live="polite">
                  {timeline.isPending ? (
                    <p role="status">正在读取记忆变化</p>
                  ) : null}
                  {timeline.isError ? (
                    <p role="status">当前无法读取记忆变化。</p>
                  ) : null}
                  {Array.isArray(timeline.data?.items) ? (
                    <ol>
                      {timeline.data.items.map((revision) => (
                        <li key={revision.revision_id}>
                          <strong>
                            {REVISION_LABELS[revision.revision_kind]}
                          </strong>
                          <span>{revision.summary}</span>
                          <small>
                            {ACCESSIBILITY_LABELS[revision.accessibility]}
                          </small>
                          {revision.relation_kind === null ? null : (
                            <small>
                              {RELATION_LABELS[revision.relation_kind]}
                            </small>
                          )}
                          <time dateTime={revision.occurred_at}>
                            {revision.occurred_at}
                          </time>
                        </li>
                      ))}
                    </ol>
                  ) : null}
                  {timeline.data?.next_cursor !== null &&
                  timeline.data?.next_cursor !== undefined ? (
                    <button
                      type="button"
                      className="secondary"
                      onClick={() =>
                        setTimelineCursor(
                          timeline.data?.next_cursor ?? undefined,
                        )
                      }
                    >
                      更早的记忆变化
                    </button>
                  ) : null}
                </div>
              ) : null}
            </li>
          ))}
        </ol>
      ) : null}
      {memories.data?.next_cursor !== null &&
      memories.data?.next_cursor !== undefined ? (
        <button
          type="button"
          className="secondary"
          onClick={() =>
            setMemoryCursor(memories.data?.next_cursor ?? undefined)
          }
        >
          更早的记忆
        </button>
      ) : null}
    </section>
  );
}
