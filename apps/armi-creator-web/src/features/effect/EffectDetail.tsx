import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  ApiFailure,
  type CodexEffectArtifactKind,
  getEffectArtifact,
  getEffectDetail,
} from "../../api/client";

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
  const [artifact, setArtifact] = useState<{
    kind: CodexEffectArtifactKind;
    content: string;
  } | null>(null);
  const [artifactFailure, setArtifactFailure] = useState(false);
  const effect = useQuery({
    queryKey: ["creator-effect", effectRef],
    enabled: effectRef !== null,
    queryFn: ({ signal }) => getEffectDetail(token, effectRef!, signal),
  });

  useEffect(() => {
    if (effectRef !== null) {
      closeButton.current?.focus();
    }
    setArtifact(null);
    setArtifactFailure(false);
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
              <dt>能力</dt>
              <dd>{effect.data.capability_kind}</dd>
            </div>
            <div>
              <dt>Action Intent</dt>
              <dd>{effect.data.action_intent_ref}</dd>
            </div>
            <div>
              <dt>Intent Revision</dt>
              <dd>{effect.data.action_intent_revision_ref}</dd>
            </div>
            {effect.data.policy_decision_ref ? (
              <div>
                <dt>Policy Decision</dt>
                <dd>{effect.data.policy_decision_ref}</dd>
              </div>
            ) : null}
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
          {effect.data.effect_kind === "codex_delegation" &&
          effect.data.status === "completed" ? (
            <div className="verified-response">
              <h3>已核验 Codex 产物</h3>
              <div className="timeline-heading-row">
                {(["patch", "final_result", "validation_report"] as const).map(
                  (kind) => (
                    <button
                      type="button"
                      className="secondary"
                      key={kind}
                      onClick={() => {
                        setArtifactFailure(false);
                        void getEffectArtifact(
                          token,
                          effect.data.effect_id,
                          kind,
                        )
                          .then((content) => setArtifact({ kind, content }))
                          .catch((error: unknown) => {
                            if (
                              error instanceof ApiFailure &&
                              error.status === 401
                            ) {
                              onUnauthorized();
                            } else {
                              setArtifactFailure(true);
                            }
                          });
                      }}
                    >
                      查看 {kind}
                    </button>
                  ),
                )}
              </div>
              {artifact === null ? null : (
                <div>
                  <h4>{artifact.kind}</h4>
                  <pre>{artifact.content}</pre>
                </div>
              )}
              {artifactFailure ? (
                <p role="status">当前无法核验该产物。</p>
              ) : null}
            </div>
          ) : null}
          {effect.data.status === "unknown" ? (
            <p className="critical-note" role="status">
              结果未知；请按核验责任确认，不提供自动重试。
            </p>
          ) : null}
          {effect.data.status === "registered" ? (
            <p className="authority-note" role="status">
              效果已经登记，但尚未证明进入外部派发；授权撤回或过期后的最终状态以账本重取结果为准。
            </p>
          ) : null}
          {effect.data.status === "dispatching" ? (
            <p className="critical-note" role="status">
              效果已进入派发边界；之后撤回授权不会改写在途事实，仍需等待可靠回执或核验结果。
            </p>
          ) : null}
          {effect.data.status === "cancelled" ? (
            <p className="authority-note" role="status">
              账本确认该效果已在派发前取消；intent、policy、attempt
              与取消历史仍被保留。
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}
