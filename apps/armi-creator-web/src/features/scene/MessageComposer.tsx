import { useRef, useState } from "react";
import type { FormEvent, KeyboardEvent, CompositionEvent } from "react";
import type { QueryClient, QueryKey } from "@tanstack/react-query";

import {
  acceptCreatorCodexTask,
  acceptCreatorMessage,
  ApiFailure,
} from "../../api/client";
import { createCreatorInputKey, validateCreatorMessage } from "./messageIntent";

type SubmissionState =
  | { kind: "idle"; message?: string }
  | { kind: "sending"; key: string; mode: SubmissionMode }
  | { kind: "unconfirmed"; key: string; mode: SubmissionMode; message: string }
  | { kind: "accepted"; operationRef: string; mode: SubmissionMode }
  | { kind: "rejected"; message: string };

type SubmissionMode = "input" | "codex";

type MessageComposerProps = {
  token: string;
  sceneKey: string;
  sceneOpen: boolean;
  queryClient: QueryClient;
  timelineQueryKey: QueryKey;
  onUnauthorized: () => void;
  onOperationAccepted: (operationRef: string) => void;
};

function rejectedMessage(error: ApiFailure): string {
  if (error.status === 409 && error.code === "IDEMPOTENCY_MISMATCH") {
    return "该接纳身份与此前内容不一致，请作为新输入重试。";
  }
  if (error.status === 413) {
    return "输入超过 Runtime 接纳上限。";
  }
  return "Runtime 已明确拒绝这次输入，请检查后作为新输入重试。";
}

export function MessageComposer({
  token,
  sceneKey,
  sceneOpen,
  queryClient,
  timelineQueryKey,
  onUnauthorized,
  onOperationAccepted,
}: MessageComposerProps) {
  const [message, setMessage] = useState("");
  const [state, setState] = useState<SubmissionState>({ kind: "idle" });
  const composing = useRef(false);

  async function send(mode: SubmissionMode, key?: string): Promise<void> {
    if (!sceneOpen) {
      setState({
        kind: "rejected",
        message: "这个场合已关闭，重新打开后才能输入。",
      });
      return;
    }
    const validation = validateCreatorMessage(message);
    if (!validation.valid) {
      setState({ kind: "idle", message: validation.message });
      return;
    }
    const intentKey = key ?? createCreatorInputKey();
    setState({ kind: "sending", key: intentKey, mode });
    try {
      const accepted =
        mode === "codex"
          ? await acceptCreatorCodexTask(token, sceneKey, intentKey, message)
          : await acceptCreatorMessage(token, sceneKey, intentKey, message);
      const operationRef = accepted.result_ref;
      setMessage("");
      setState({ kind: "accepted", operationRef, mode });
      onOperationAccepted(operationRef);
      await queryClient.resetQueries({
        queryKey: timelineQueryKey,
        exact: true,
      });
    } catch (error) {
      if (error instanceof ApiFailure && error.status === 401) {
        onUnauthorized();
        return;
      }
      if (
        error instanceof ApiFailure &&
        [400, 403, 404, 409, 413].includes(error.status)
      ) {
        setState({ kind: "rejected", message: rejectedMessage(error) });
        return;
      }
      setState({
        kind: "unconfirmed",
        key: intentKey,
        mode,
        message: "结果尚未确认。原输入与接纳身份仍保留，可安全核验同一次意图。",
      });
    }
  }

  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (state.kind !== "sending") {
      void send(
        state.kind === "unconfirmed" ? state.mode : "input",
        state.kind === "unconfirmed" ? state.key : undefined,
      );
    }
  }

  function keyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !composing.current &&
      state.kind !== "sending"
    ) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  function compositionStart(_event: CompositionEvent<HTMLTextAreaElement>) {
    composing.current = true;
  }

  function compositionEnd(_event: CompositionEvent<HTMLTextAreaElement>) {
    composing.current = false;
  }

  const locked =
    !sceneOpen || state.kind === "sending" || state.kind === "unconfirmed";

  return (
    <section className="message-composer" aria-label="发送消息">
      <form onSubmit={submit}>
        <label className="visually-hidden" htmlFor="creator-message">
          输入内容
        </label>
        <textarea
          id="creator-message"
          name="creator-message"
          rows={2}
          placeholder={sceneOpen ? "给 ARMI 发消息…" : "这个场合已关闭"}
          value={message}
          readOnly={locked}
          aria-describedby="composer-note"
          onChange={(event) => {
            setMessage(event.currentTarget.value);
            if (
              state.kind === "rejected" ||
              state.kind === "accepted" ||
              state.kind === "idle"
            ) {
              setState({ kind: "idle" });
            }
          }}
          onKeyDown={keyDown}
          onCompositionStart={compositionStart}
          onCompositionEnd={compositionEnd}
        />
        <p id="composer-note" className="composer-note">
          {sceneOpen
            ? "Enter 发送 · Shift+Enter 换行"
            : "这个场合已关闭；历史 timeline 仍可读取，重新打开后才能继续输入。"}
        </p>
        {state.kind === "unconfirmed" ? (
          <div className="composer-recovery">
            <p role="status">{state.message}</p>
            <button type="submit">核验同一次输入</button>
            <button
              type="button"
              className="secondary"
              onClick={() => setState({ kind: "idle" })}
            >
              作为新输入
            </button>
          </div>
        ) : (
          <div className="composer-actions">
            <button type="submit" aria-label="提交输入" disabled={locked}>
              {state.kind === "sending" ? "发送中" : "发送"}
            </button>
            <button
              type="button"
              className="secondary"
              disabled={locked}
              onClick={() => void send("codex")}
            >
              委托 Codex
            </button>
          </div>
        )}
        {state.kind === "idle" && state.message ? (
          <p role="status">{state.message}</p>
        ) : null}
        {state.kind === "rejected" ? (
          <p role="status">{state.message}</p>
        ) : null}
        {state.kind === "accepted" ? (
          <p className="composer-status" role="status">
            {state.mode === "codex"
              ? "Codex 委托请求已由 Runtime 耐久接纳；若 ARMI 形成正式委托，你仍须在权限区批准。"
              : "消息已发送"}
          </p>
        ) : null}
      </form>
    </section>
  );
}
