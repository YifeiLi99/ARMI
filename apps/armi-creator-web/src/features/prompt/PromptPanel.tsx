import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  ApiFailure,
  deactivateCreatorPrompt,
  getCreatorPrompt,
  reviseCreatorPrompt,
} from "../../api/client";

type PromptPanelProps = {
  token: string;
  environmentId: string;
  creatorPartyId: string;
  onUnauthorized: () => void;
};

export function PromptPanel({
  token,
  environmentId,
  creatorPartyId,
  onUnauthorized,
}: PromptPanelProps) {
  const queryClient = useQueryClient();
  const queryKey = ["creator-prompt", environmentId, creatorPartyId] as const;
  const prompt = useQuery({
    queryKey,
    queryFn: ({ signal }) => getCreatorPrompt(token, signal),
  });
  const [content, setContent] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (prompt.data !== undefined) {
      setContent(prompt.data.content ?? "");
    }
  }, [prompt.data]);

  useEffect(() => {
    if (prompt.error instanceof ApiFailure && prompt.error.status === 401) {
      onUnauthorized();
    }
  }, [onUnauthorized, prompt.error]);

  const revision = useMutation({
    mutationFn: () =>
      reviseCreatorPrompt(
        token,
        prompt.data?.current_revision_id ?? null,
        content,
      ),
    onSuccess: (value) => {
      queryClient.setQueryData(queryKey, value);
      setMessage("Creator Prompt 新修订已生效，只影响后续认知。");
    },
    onError: (error) => {
      if (error instanceof ApiFailure && error.status === 401) {
        onUnauthorized();
        return;
      }
      setMessage(
        error instanceof ApiFailure && error.status === 409
          ? "Prompt 已被其他修订推进，请重新读取后再提交。"
          : "当前无法提交 Creator Prompt。",
      );
    },
  });

  const deactivation = useMutation({
    mutationFn: () => {
      const revisionId = prompt.data?.current_revision_id;
      if (revisionId === null || revisionId === undefined) {
        throw new Error("Prompt revision is unavailable");
      }
      return deactivateCreatorPrompt(token, revisionId);
    },
    onSuccess: (value) => {
      queryClient.setQueryData(queryKey, value);
      setMessage("Creator Prompt 已停用；历史认知仍保留原 revision 引用。");
    },
    onError: (error) => {
      if (error instanceof ApiFailure && error.status === 401) {
        onUnauthorized();
        return;
      }
      setMessage(
        error instanceof ApiFailure && error.status === 409
          ? "Prompt 已被其他修订推进，请重新读取后再停用。"
          : "当前无法停用 Creator Prompt。",
      );
    },
  });

  const busy = revision.isPending || deactivation.isPending;
  const unchanged = content === (prompt.data?.content ?? "");

  return (
    <section
      className="authority-panel prompt-panel"
      aria-labelledby="prompt-heading"
    >
      <div className="panel-heading-row">
        <div>
          <p className="eyebrow">Creator 权威</p>
          <h2 id="prompt-heading">认知指导 Prompt</h2>
        </div>
        <button
          type="button"
          className="secondary"
          disabled={busy}
          onClick={() => {
            setMessage(null);
            void prompt.refetch();
          }}
        >
          重新读取
        </button>
      </div>
      {prompt.isPending ? (
        <p role="status">正在读取 Creator Prompt</p>
      ) : prompt.isError ? (
        <p role="status">当前无法读取 Creator Prompt。</p>
      ) : (
        <form
          className="prompt-form"
          onSubmit={(event) => {
            event.preventDefault();
            setMessage(null);
            revision.mutate();
          }}
        >
          <p className="field-note">
            这里只维护 Creator 指导；不能修改固定人格锚点、Self 或 ARMI 自维护
            Prompt。
          </p>
          <label htmlFor="creator-prompt-content">Creator Prompt 内容</label>
          <textarea
            id="creator-prompt-content"
            value={content}
            maxLength={65_536}
            required
            disabled={busy}
            onChange={(event) => setContent(event.currentTarget.value)}
          />
          <dl>
            <div>
              <dt>状态</dt>
              <dd>
                {prompt.data.current_revision_id === null
                  ? "尚未创建"
                  : prompt.data.status === "active"
                    ? "生效中"
                    : "已停用"}
              </dd>
            </div>
            <div>
              <dt>当前版本</dt>
              <dd>{prompt.data.revision_no ?? "尚未创建"}</dd>
            </div>
          </dl>
          <div className="composer-actions">
            <button
              type="submit"
              disabled={busy || !content.trim() || unchanged}
            >
              {prompt.data.current_revision_id === null
                ? "创建并生效"
                : prompt.data.status === "inactive"
                  ? "提交新修订并恢复"
                  : "提交新修订"}
            </button>
            <button
              type="button"
              className="secondary"
              disabled={
                busy ||
                prompt.data.current_revision_id === null ||
                prompt.data.status === "inactive"
              }
              onClick={() => {
                setMessage(null);
                deactivation.mutate();
              }}
            >
              停用
            </button>
          </div>
          {message === null ? null : <p role="status">{message}</p>}
        </form>
      )}
    </section>
  );
}
