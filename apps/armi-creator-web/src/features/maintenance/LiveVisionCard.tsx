import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  ApiFailure,
  controlLiveVision,
  getLiveVisionPreview,
  getLiveVisionStatus,
} from "../../api/client";
import { ComponentSwitch } from "./ComponentSwitch";

type Props = { token: string; onUnauthorized: () => void };

const labels: Record<string, string> = {
  disabled: "未启用",
  idle: "已暂停",
  starting: "正在启动",
  observing: "正在观察",
  degraded: "连接中断，等待同一设备恢复",
  unavailable: "暂不可用",
  stopping: "正在停止",
};

export function LiveVisionCard({ token, onUnauthorized }: Props) {
  const queryClient = useQueryClient();
  const key = ["live-vision-status"] as const;
  const status = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => getLiveVisionStatus(token, signal),
    refetchInterval: 2_000,
  });
  const control = useMutation({
    mutationFn: (action: "start" | "stop" | "observe") =>
      controlLiveVision(token, action),
    onSuccess: (value) => queryClient.setQueryData(key, value),
  });
  const [previewUrl, setPreviewUrl] = useState<string>();
  const preview = useMutation({
    mutationFn: () => getLiveVisionPreview(token),
    onSuccess: (blob) => {
      setPreviewUrl((current) => {
        if (current !== undefined) URL.revokeObjectURL(current);
        return blob === null ? undefined : URL.createObjectURL(blob);
      });
    },
  });
  useEffect(
    () => () => {
      if (previewUrl !== undefined) URL.revokeObjectURL(previewUrl);
    },
    [previewUrl],
  );
  useEffect(() => {
    const errors = [status.error, control.error, preview.error];
    if (
      errors.some(
        (error) => error instanceof ApiFailure && error.status === 401,
      )
    ) {
      onUnauthorized();
    }
  }, [control.error, onUnauthorized, preview.error, status.error]);

  const active =
    status.data?.state === "observing" || status.data?.state === "degraded";
  return (
    <section className="authority-panel" aria-labelledby="live-vision-heading">
      <div className="panel-heading-row">
        <div>
          <p className="eyebrow">私有环境感知</p>
          <h2 id="live-vision-heading">常驻视觉</h2>
        </div>
        <div className="panel-actions">
          <button
            type="button"
            className="secondary"
            disabled={!status.data?.capture_ready || preview.isPending}
            onClick={() => preview.mutate()}
          >
            单帧取景检查
          </button>
          <button
            type="button"
            className="secondary"
            disabled={!active || control.isPending}
            onClick={() => control.mutate("observe")}
          >
            立即观察
          </button>
          <ComponentSwitch
            label="常驻视觉"
            checked={active}
            disabled={!status.data?.enabled}
            pending={control.isPending}
            onChange={(running) => control.mutate(running ? "start" : "stop")}
          />
        </div>
      </div>
      {status.isPending ? <p role="status">正在读取视觉状态</p> : null}
      {status.isError ? <p role="status">当前无法读取视觉状态。</p> : null}
      {status.data === undefined ? null : (
        <>
          <p className="maintenance-state" role="status">
            {labels[status.data.state] ?? status.data.state}
          </p>
          <dl>
            <div>
              <dt>精确设备</dt>
              <dd>{status.data.device ?? "尚未配置"}</dd>
            </div>
            <div>
              <dt>采集</dt>
              <dd>{status.data.capture_ready ? "已就绪" : "未就绪"}</dd>
            </div>
            <div>
              <dt>感知</dt>
              <dd>{status.data.perception_ready ? "已就绪" : "未就绪"}</dd>
            </div>
            <div>
              <dt>最后帧</dt>
              <dd>{status.data.last_frame_at ?? "尚无"}</dd>
            </div>
            <div>
              <dt>最后观察</dt>
              <dd>{status.data.last_observation_at ?? "尚无"}</dd>
            </div>
            <div>
              <dt>小时预算</dt>
              <dd>
                {status.data.observations_last_hour} /{" "}
                {status.data.hourly_limit}
              </dd>
            </div>
          </dl>
          {status.data.reason_codes.map((reason) => (
            <p className="field-note" key={reason}>
              状态原因：{reason}
            </p>
          ))}
        </>
      )}
      {previewUrl === undefined ? null : (
        <img
          src={previewUrl}
          alt="当前摄像头单帧预览"
          style={{ maxWidth: "100%", height: "auto" }}
        />
      )}
      {preview.isSuccess && preview.data === null ? (
        <p role="status">当前还没有可预览的帧。</p>
      ) : null}
      <p className="boundary-note">
        浏览器不会申请摄像头权限。预览只读取 Runtime
        内存中的当前缩小画面，不保存、不上传模型，也不形成 Evidence。
      </p>
    </section>
  );
}
