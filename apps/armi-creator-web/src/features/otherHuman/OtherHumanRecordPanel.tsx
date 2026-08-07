import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import {
  ApiFailure,
  getOtherHumanRecordParties,
  getOtherHumanRecordScenes,
  getOtherHumanRecordTimeline,
} from "../../api/client";

type Props = {
  token: string;
  environmentId: string;
  creatorPartyId: string;
  onUnauthorized: () => void;
};

export function OtherHumanRecordPanel({
  token,
  environmentId,
  creatorPartyId,
  onUnauthorized,
}: Props) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [partyCursor, setPartyCursor] = useState<string | undefined>();
  const [sceneCursor, setSceneCursor] = useState<string | undefined>();
  const [timelineCursor, setTimelineCursor] = useState<string | undefined>();
  const [selectedPartyId, setSelectedPartyId] = useState<string | null>(null);
  const [selectedSceneId, setSelectedSceneId] = useState<string | null>(null);

  const parties = useQuery({
    queryKey: [
      "other-human-record-parties",
      environmentId,
      creatorPartyId,
      partyCursor ?? "first",
    ],
    queryFn: ({ signal }) =>
      getOtherHumanRecordParties(token, 20, partyCursor, signal),
    enabled: open,
  });
  const scenes = useQuery({
    queryKey: [
      "other-human-record-scenes",
      environmentId,
      creatorPartyId,
      selectedPartyId,
      sceneCursor ?? "first",
    ],
    queryFn: ({ signal }) =>
      getOtherHumanRecordScenes(
        token,
        selectedPartyId!,
        20,
        sceneCursor,
        signal,
      ),
    enabled: selectedPartyId !== null,
  });
  const timeline = useQuery({
    queryKey: [
      "other-human-record-timeline",
      environmentId,
      creatorPartyId,
      selectedPartyId,
      selectedSceneId,
      timelineCursor ?? "first",
    ],
    queryFn: ({ signal }) =>
      getOtherHumanRecordTimeline(
        token,
        selectedPartyId!,
        selectedSceneId!,
        50,
        timelineCursor,
        signal,
      ),
    enabled: selectedPartyId !== null && selectedSceneId !== null,
  });

  useEffect(() => {
    if (
      [parties.error, scenes.error, timeline.error].some(
        (error) => error instanceof ApiFailure && error.status === 401,
      )
    ) {
      onUnauthorized();
    }
  }, [onUnauthorized, parties.error, scenes.error, timeline.error]);

  return (
    <section
      className="authority-panel other-human-record-panel"
      aria-labelledby="other-human-record-heading"
    >
      <div className="panel-heading-row">
        <div>
          <p className="eyebrow">其他人</p>
          <h2 id="other-human-record-heading">交流记录</h2>
        </div>
        <button
          type="button"
          className="secondary"
          onClick={() =>
            void queryClient.resetQueries({
              predicate: (query) =>
                String(query.queryKey[0]).startsWith("other-human-record-"),
            })
          }
        >
          刷新
        </button>
      </div>
      <p className="boundary-note">
        这里只读展示已接纳的交流事实；原文不会自动进入当前 Creator
        对话，也不能在这里代替 ARMI 回复或修改关系。
      </p>

      <button
        type="button"
        className="secondary"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        {open ? "收起交流记录" : "查看交流记录"}
      </button>

      {open ? (
        <>
          {parties.isPending ? <p role="status">正在读取交流对象</p> : null}
          {open && parties.isError ? (
            <p role="status">当前无法读取其他人记录。</p>
          ) : null}
          {open && parties.data?.items.length === 0 ? (
            <p className="timeline-empty" role="status">
              当前还没有其他人交流记录
            </p>
          ) : null}
          {parties.data?.items.map((party) => (
            <button
              type="button"
              className="record-choice"
              aria-pressed={selectedPartyId === party.party_id}
              key={party.party_id}
              onClick={() => {
                setSelectedPartyId(party.party_id);
                setSelectedSceneId(null);
                setSceneCursor(undefined);
                setTimelineCursor(undefined);
              }}
            >
              <strong>{party.display_label}</strong>
              <span>
                {party.scene_count} 个场合 · {party.record_count} 条记录
              </span>
            </button>
          ))}
          {parties.data?.next_cursor ? (
            <button
              type="button"
              className="secondary"
              onClick={() =>
                setPartyCursor(parties.data?.next_cursor ?? undefined)
              }
            >
              更多交流对象
            </button>
          ) : null}

          {scenes.data ? (
            <h3>{scenes.data.party.display_label} 的场合</h3>
          ) : null}
          {scenes.data?.items.map((scene) => (
            <button
              type="button"
              className="record-choice"
              aria-pressed={selectedSceneId === scene.scene_id}
              key={scene.scene_id}
              onClick={() => {
                setSelectedSceneId(scene.scene_id);
                setTimelineCursor(undefined);
              }}
            >
              <strong>{scene.scene_key}</strong>
              <span>
                {scene.status === "open" ? "进行中" : "已关闭"} ·{" "}
                {scene.record_count} 条
              </span>
            </button>
          ))}
          {scenes.data?.next_cursor ? (
            <button
              type="button"
              className="secondary"
              onClick={() =>
                setSceneCursor(scenes.data?.next_cursor ?? undefined)
              }
            >
              更多场合
            </button>
          ) : null}

          {timeline.data ? (
            <ol className="other-human-record-list">
              {timeline.data.items.map((item) => (
                <li key={item.timeline_item_id} data-direction={item.direction}>
                  <div className="memory-title-row">
                    <strong>
                      {item.direction === "received" ? "对方" : "ARMI"}
                    </strong>
                    <span>{item.status}</span>
                  </div>
                  <p>{item.text}</p>
                  <time dateTime={item.occurred_at}>{item.occurred_at}</time>
                </li>
              ))}
            </ol>
          ) : null}
          {timeline.data?.next_cursor ? (
            <button
              type="button"
              className="secondary"
              onClick={() =>
                setTimelineCursor(timeline.data?.next_cursor ?? undefined)
              }
            >
              更早的记录
            </button>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
