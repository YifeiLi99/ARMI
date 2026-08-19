import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  ApiFailure,
  getLiveVoiceStatus,
  setLiveVoiceRunning,
} from "../../api/client";

type LiveVoiceCardProps = {
  token: string;
  onUnauthorized: () => void;
};

const STATE_LABELS: Record<string, string> = {
  disabled: "未启用",
  idle: "已停止",
  starting: "正在启动",
  listening: "正在听",
  recognizing: "正在识别",
  thinking: "正在组织快答",
  speaking: "正在说话",
  waiting_slow: "正在等待完整回答",
  unavailable: "暂不可用",
};

const REASON_LABELS: Record<string, string> = {
  VOICE_INPUT_DEVICE_UNAVAILABLE: "找不到配置的麦克风。",
  VOICE_OUTPUT_DEVICE_UNAVAILABLE: "找不到配置的扬声器。",
  VOICE_AUDIO_UNAVAILABLE: "Windows 音频接口当前不可用。",
  VOICE_PIPELINE_UNAVAILABLE: "实时语音链路尚未完成运行接线。",
};

export function LiveVoiceCard({ token, onUnauthorized }: LiveVoiceCardProps) {
  const queryClient = useQueryClient();
  const queryKey = ["live-voice-status"] as const;
  const status = useQuery({
    queryKey,
    queryFn: ({ signal }) => getLiveVoiceStatus(token, signal),
    refetchInterval: 2_000,
  });
  const control = useMutation({
    mutationFn: (running: boolean) => setLiveVoiceRunning(token, running),
    onSuccess: (value) => queryClient.setQueryData(queryKey, value),
  });

  useEffect(() => {
    if (
      (status.error instanceof ApiFailure && status.error.status === 401) ||
      (control.error instanceof ApiFailure && control.error.status === 401)
    ) {
      onUnauthorized();
    }
  }, [control.error, onUnauthorized, status.error]);

  const active =
    status.data !== undefined &&
    !["disabled", "idle", "unavailable"].includes(status.data.state);
  const canStart = status.data?.state === "idle";

  return (
    <section className="authority-panel" aria-labelledby="live-voice-heading">
      <div className="panel-heading-row">
        <div>
          <p className="eyebrow">本机生活入口</p>
          <h2 id="live-voice-heading">实时语音</h2>
        </div>
        <div className="panel-actions">
          <button
            type="button"
            className="secondary"
            onClick={() => void status.refetch()}
          >
            刷新
          </button>
          <button
            type="button"
            disabled={control.isPending || (!active && !canStart)}
            onClick={() => control.mutate(!active)}
          >
            {control.isPending ? "正在处理" : active ? "结束语音" : "开始语音"}
          </button>
        </div>
      </div>

      {status.isPending ? <p role="status">正在读取语音状态</p> : null}
      {status.isError ? <p role="status">当前无法读取语音状态。</p> : null}
      {status.data === undefined ? null : (
        <>
          <p className="maintenance-state" role="status">
            {STATE_LABELS[status.data.state] ?? status.data.state}
          </p>
          <dl>
            <div>
              <dt>麦克风</dt>
              <dd>{status.data.input_device ?? "尚未配置"}</dd>
            </div>
            <div>
              <dt>扬声器</dt>
              <dd>{status.data.output_device ?? "尚未配置"}</dd>
            </div>
            <div>
              <dt>火山 ASR</dt>
              <dd>{status.data.asr_ready ? "已就绪" : "未就绪"}</dd>
            </div>
            <div>
              <dt>豆包快模型</dt>
              <dd>{status.data.llm_ready ? "已就绪" : "未就绪"}</dd>
            </div>
            <div>
              <dt>火山 TTS</dt>
              <dd>{status.data.tts_ready ? "已就绪" : "未就绪"}</dd>
            </div>
          </dl>
          {status.data.reason_codes.map((reason) => (
            <p className="field-note" key={reason}>
              {REASON_LABELS[reason] ?? `状态原因：${reason}`}
            </p>
          ))}
        </>
      )}
      {control.isError ? <p role="status">语音状态切换失败。</p> : null}
      <p className="boundary-note">
        麦克风由 Runtime
        宿主采集；浏览器麦克风权限保持关闭。首版为半双工，播报期间暂停收音。
      </p>
    </section>
  );
}
