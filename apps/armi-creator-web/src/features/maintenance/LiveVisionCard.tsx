import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  ApiFailure,
  controlLiveVision,
  getLiveVisionObservation,
  getLiveVisionPreview,
  getLiveVisionStatus,
  type LiveVisionSourceKind,
  observeLiveVision,
} from "../../api/client";
import { createCreatorInputKey } from "../scene/messageIntent";
import { ComponentSwitch } from "./ComponentSwitch";

type Props = { token: string; onUnauthorized: () => void };

const labels: Record<string, string> = {
  disabled: "未启用",
  idle: "已暂停",
  starting: "正在启动",
  observing: "正在观察",
  degraded: "连接中断，等待同一来源恢复",
  unavailable: "暂不可用",
  stopping: "正在停止",
};

export function LiveVisionCard({ token, onUnauthorized }: Props) {
  const status = useQuery({
    queryKey: ["live-vision-status"],
    queryFn: ({ signal }) => getLiveVisionStatus(token, signal),
    refetchInterval: 2_000,
  });
  useEffect(() => {
    if (status.error instanceof ApiFailure && status.error.status === 401) {
      onUnauthorized();
    }
  }, [onUnauthorized, status.error]);
  return (
    <section className="authority-panel" aria-labelledby="live-vision-heading">
      <div className="panel-heading-row">
        <div>
          <p className="eyebrow">私有环境感知</p>
          <h2 id="live-vision-heading">常驻视觉</h2>
        </div>
      </div>
      {status.isPending ? <p role="status">正在读取视觉状态</p> : null}
      {status.isError ? <p role="status">当前无法读取视觉状态。</p> : null}
      {status.data?.sources.map((source) => (
        <VisionSourcePanel
          key={source.source_kind}
          token={token}
          source={source.source_kind}
          status={source}
          onUnauthorized={onUnauthorized}
        />
      ))}
      <p className="boundary-note">
        预览只读取 Runtime 内存中的缩小画面，不保存、不上传模型，也不形成
        Evidence。正式屏幕观察会把所选显示器的完整画面发送给视觉模型。
      </p>
    </section>
  );
}

function VisionSourcePanel({
  token,
  source,
  status,
  onUnauthorized,
}: {
  token: string;
  source: LiveVisionSourceKind;
  status: Awaited<ReturnType<typeof getLiveVisionStatus>>["sources"][number];
  onUnauthorized: () => void;
}) {
  const queryClient = useQueryClient();
  const [observationId, setObservationId] = useState<string | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string>();
  const control = useMutation({
    mutationFn: (action: "start" | "stop") =>
      controlLiveVision(token, source, action),
    onSuccess: (value) =>
      queryClient.setQueryData(["live-vision-status"], value),
  });
  const manual = useMutation({
    mutationFn: () => observeLiveVision(token, source, createCreatorInputKey()),
    onSuccess: (value) => setObservationId(value.observation_id),
  });
  const observation = useQuery({
    queryKey: ["live-vision-observation", source, observationId],
    enabled: observationId !== null,
    queryFn: ({ signal }) =>
      getLiveVisionObservation(token, observationId!, signal),
    refetchInterval: (query) =>
      query.state.data !== undefined &&
      ["completed", "failed", "unknown"].includes(query.state.data.status)
        ? false
        : 1_000,
  });
  const preview = useMutation({
    mutationFn: () => getLiveVisionPreview(token, source),
    onSuccess: (blob) =>
      setPreviewUrl((current) => {
        if (current !== undefined) URL.revokeObjectURL(current);
        return blob === null ? undefined : URL.createObjectURL(blob);
      }),
  });
  useEffect(
    () => () => {
      if (previewUrl !== undefined) URL.revokeObjectURL(previewUrl);
    },
    [previewUrl],
  );
  useEffect(() => {
    if (
      [control.error, manual.error, observation.error, preview.error].some(
        (error) => error instanceof ApiFailure && error.status === 401,
      )
    )
      onUnauthorized();
  }, [
    control.error,
    manual.error,
    observation.error,
    onUnauthorized,
    preview.error,
  ]);
  const active = status.state === "observing" || status.state === "degraded";
  const title = source === "camera" ? "摄像头" : "电脑屏幕";
  return (
    <article className="authority-panel" aria-label={title}>
      <div className="panel-heading-row">
        <h3>{title}</h3>
        <div className="panel-actions">
          <button
            type="button"
            className="secondary"
            disabled={!status.capture_ready || preview.isPending}
            onClick={() => preview.mutate()}
          >
            预览
          </button>
          <button
            type="button"
            className="secondary"
            disabled={!active || manual.isPending}
            onClick={() => manual.mutate()}
          >
            立即观察
          </button>
          <ComponentSwitch
            label={title}
            checked={active}
            disabled={!status.enabled}
            pending={control.isPending}
            onChange={(running) => control.mutate(running ? "start" : "stop")}
          />
        </div>
      </div>
      <p className="maintenance-state" role="status">
        {labels[status.state] ?? status.state}
      </p>
      <dl>
        <div>
          <dt>精确来源</dt>
          <dd>{status.identity ?? "尚未配置"}</dd>
        </div>
        <div>
          <dt>采集 / 感知</dt>
          <dd>
            {status.capture_ready ? "已就绪" : "未就绪"} /{" "}
            {status.perception_ready ? "已就绪" : "未就绪"}
          </dd>
        </div>
        <div>
          <dt>最后帧 / 观察</dt>
          <dd>
            {status.last_frame_at ?? "尚无"} /{" "}
            {status.last_observation_at ?? "尚无"}
          </dd>
        </div>
        <div>
          <dt>小时预算</dt>
          <dd>
            {status.observations_last_hour} / {status.hourly_limit}
          </dd>
        </div>
      </dl>
      {status.reason_codes.map((reason) => (
        <p className="field-note" key={reason}>
          状态原因：{reason}
        </p>
      ))}
      {previewUrl === undefined ? null : (
        <img
          src={previewUrl}
          alt={`${title}当前帧预览`}
          style={{ maxWidth: "100%", height: "auto" }}
        />
      )}
      {preview.isSuccess && preview.data === null ? (
        <p role="status">当前还没有可预览的帧。</p>
      ) : null}
      {observation.data === undefined ? null : (
        <p role="status">
          手动观察：{observation.data.status}
          {observation.data.summary === null
            ? ""
            : ` · ${observation.data.summary}`}
          {observation.data.error_code === null
            ? ""
            : ` · ${observation.data.error_code}`}
        </p>
      )}
    </article>
  );
}
