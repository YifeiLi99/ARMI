import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";

import { ApiFailure, getEffectDetail } from "../../api/client";

type EffectDetailProps = {
  token: string;
  effectRef: string | null;
  onClose: () => void;
  onUnauthorized: () => void;
};

export function EffectDetail({
  token,
  effectRef,
  onClose,
  onUnauthorized,
}: EffectDetailProps) {
  const closeButton = useRef<HTMLButtonElement>(null);
  const effect = useQuery({
    queryKey: ["creator-effect", effectRef],
    enabled: effectRef !== null,
    queryFn: ({ signal }) => getEffectDetail(token, effectRef!, signal),
  });

  useEffect(() => {
    if (effectRef !== null) {
      closeButton.current?.focus();
    }
  }, [effectRef]);
  useEffect(() => {
    if (effect.error instanceof ApiFailure && effect.error.status === 401) {
      onUnauthorized();
    }
  }, [effect.error, onUnauthorized]);

  if (effectRef === null) {
    return null;
  }
  return (
    <section
      className="authority-panel effect-detail"
      aria-labelledby="effect-heading"
    >
      <div className="timeline-heading-row">
        <h2 id="effect-heading">效果详情</h2>
        <button
          ref={closeButton}
          type="button"
          className="secondary"
          onClick={onClose}
        >
          关闭详情
        </button>
      </div>
      {effect.isPending ? (
        <p role="status">正在核验效果账本</p>
      ) : effect.isError ? (
        <p role="status">当前无法核验该效果。</p>
      ) : (
        <>
          <dl>
            <div>
              <dt>状态</dt>
              <dd>{effect.data.status}</dd>
            </div>
            <div>
              <dt>Attempt</dt>
              <dd>{effect.data.attempt_count}</dd>
            </div>
            <div>
              <dt>核验状态</dt>
              <dd>{effect.data.verification_status}</dd>
            </div>
            {effect.data.last_observation_kind === undefined ||
            effect.data.last_observation_kind === null ? null : (
              <div>
                <dt>最后可靠观察</dt>
                <dd>
                  {effect.data.last_observation_kind} ·{" "}
                  {effect.data.last_observation_reliability}
                </dd>
              </div>
            )}
            {effect.data.verification_action === undefined ||
            effect.data.verification_action === null ? null : (
              <div className="critical-state">
                <dt>核验责任</dt>
                <dd>{effect.data.verification_action}</dd>
              </div>
            )}
            {effect.data.settled_at === undefined ||
            effect.data.settled_at === null ? null : (
              <div>
                <dt>结算时间</dt>
                <dd>{effect.data.settled_at}</dd>
              </div>
            )}
            <div>
              <dt>安全引用</dt>
              <dd>{effect.data.effect_id}</dd>
            </div>
          </dl>
          {effect.data.status === "completed" &&
          effect.data.response_text !== undefined &&
          effect.data.response_text !== null ? (
            <div className="verified-response">
              <h3>已核验回应</h3>
              <pre>{effect.data.response_text}</pre>
            </div>
          ) : null}
          {effect.data.status === "unknown" ? (
            <p className="critical-note" role="status">
              结果未知；请按核验责任确认，不提供自动重试。
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}
