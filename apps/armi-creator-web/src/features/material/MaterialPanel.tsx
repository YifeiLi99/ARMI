import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import {
  ApiFailure,
  getCreatorLifeMaterial,
  queryCreatorLifeRecords,
} from "../../api/client";

type MaterialPanelProps = {
  token: string;
  environmentId: string;
  creatorPartyId: string;
  onUnauthorized: () => void;
};

const KIND_LABELS: Record<string, string> = {
  diary: "日记",
  work: "作品",
  collection: "收藏",
  draft: "草稿",
};

const STATUS_LABELS: Record<string, string> = {
  active: "当前使用",
  archived: "已归档",
};

export function MaterialPanel({
  token,
  environmentId,
  creatorPartyId,
  onUnauthorized,
}: MaterialPanelProps) {
  const queryClient = useQueryClient();
  const [cursor, setCursor] = useState<string | undefined>(undefined);
  const [selectedMaterialId, setSelectedMaterialId] = useState<string | null>(
    null,
  );

  const listKey = [
    "life-records",
    environmentId,
    creatorPartyId,
    "material",
    "",
    cursor ?? "first",
  ] as const;
  const materials = useQuery({
    queryKey: listKey,
    queryFn: ({ signal }) =>
      queryCreatorLifeRecords(token, 20, "material", undefined, cursor, signal),
  });

  const detailKey = [
    "life-material",
    environmentId,
    creatorPartyId,
    selectedMaterialId,
  ] as const;
  const detail = useQuery({
    queryKey: detailKey,
    queryFn: ({ signal }) =>
      getCreatorLifeMaterial(token, selectedMaterialId!, signal),
    enabled: selectedMaterialId !== null,
  });

  useEffect(() => {
    if (
      (materials.error instanceof ApiFailure &&
        materials.error.status === 401) ||
      (detail.error instanceof ApiFailure && detail.error.status === 401)
    ) {
      onUnauthorized();
    }
  }, [detail.error, materials.error, onUnauthorized]);

  function closeDetail(): void {
    queryClient.removeQueries({ queryKey: detailKey, exact: true });
    setSelectedMaterialId(null);
  }

  return (
    <section
      className="authority-panel material-panel"
      aria-labelledby="material-heading"
    >
      <div className="panel-heading-row">
        <div>
          <p className="eyebrow">ARMI 的私人空间</p>
          <h2 id="material-heading">生活资料</h2>
        </div>
        <button
          type="button"
          className="secondary"
          onClick={() => {
            queryClient.removeQueries({ queryKey: ["life-material"] });
            void queryClient.resetQueries({
              predicate: (query) => query.queryKey[0] === "life-records",
            });
          }}
        >
          刷新
        </button>
      </div>

      <p className="boundary-note">
        这里只显示 ARMI 当前允许 Creator
        查看且尚未删除的资料。标记私人、恢复可见、修改或删除，都由 ARMI
        在正式对话中决定；可见不表示获准公开或代发。
      </p>

      {materials.isPending ? <p role="status">正在读取生活资料</p> : null}
      {materials.isError ? <p role="status">当前无法读取生活资料。</p> : null}
      {Array.isArray(materials.data?.items) &&
      materials.data.items.length === 0 ? (
        <p className="timeline-empty" role="status">
          当前没有 Creator 可见的生活资料
        </p>
      ) : null}
      {Array.isArray(materials.data?.items) &&
      materials.data.items.length > 0 ? (
        <ol className="material-list">
          {materials.data.items.map((material) => (
            <li key={material.record_ref}>
              <div className="material-title-row">
                <strong>{material.summary}</strong>
                <span>Creator 可见</span>
              </div>
              <time dateTime={material.occurred_at}>
                {material.occurred_at}
              </time>
              <button
                type="button"
                className="secondary"
                aria-pressed={selectedMaterialId === material.record_ref}
                onClick={() => {
                  if (selectedMaterialId === material.record_ref) {
                    closeDetail();
                  } else {
                    if (selectedMaterialId !== null) {
                      queryClient.removeQueries({
                        queryKey: detailKey,
                        exact: true,
                      });
                    }
                    setSelectedMaterialId(material.record_ref);
                  }
                }}
              >
                {selectedMaterialId === material.record_ref
                  ? "收起正文"
                  : "查看正文"}
              </button>
            </li>
          ))}
        </ol>
      ) : null}
      {materials.data?.next_cursor !== null &&
      materials.data?.next_cursor !== undefined ? (
        <button
          type="button"
          className="secondary"
          onClick={() => setCursor(materials.data?.next_cursor ?? undefined)}
        >
          更早的生活资料
        </button>
      ) : null}

      {selectedMaterialId === null ? null : (
        <div className="material-detail" aria-live="polite">
          {detail.isPending ? <p role="status">正在读取资料正文</p> : null}
          {detail.isError ? (
            <div>
              <p role="status">这项资料已变为私人、被删除或当前不可用。</p>
              <button type="button" className="secondary" onClick={closeDetail}>
                关闭
              </button>
            </div>
          ) : null}
          {detail.isSuccess ? (
            <article>
              <div className="material-title-row">
                <h3>{detail.data.title}</h3>
                <span>
                  {KIND_LABELS[detail.data.material_kind]} ·{" "}
                  {STATUS_LABELS[detail.data.material_status]}
                </span>
              </div>
              <p className="material-version">
                第 {detail.data.revision_no} 版
              </p>
              <div className="material-body">{detail.data.body}</div>
              {Object.keys(detail.data.metadata).length === 0 ? null : (
                <dl className="material-metadata">
                  {Object.entries(detail.data.metadata).map(([key, value]) => (
                    <div key={key}>
                      <dt>{key}</dt>
                      <dd>{value}</dd>
                    </div>
                  ))}
                </dl>
              )}
              <button type="button" className="secondary" onClick={closeDetail}>
                关闭正文
              </button>
            </article>
          ) : null}
        </div>
      )}
    </section>
  );
}
