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
  queryClient,
  timelineQueryKey,
  onUnauthorized,
  onOperationAccepted,
}: MessageComposerProps) {
  const [message, setMessage] = useState("");
  const [state, setState] = useState<SubmissionState>({ kind: "idle" });
  const composing = useRef(false);

  async function send(mode: SubmissionMode, key?: string): Promise<void> {
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
          ? await acceptCreatorCodexTask(
              token,
              sceneKey,
              intentKey,
              message,
            )
          : await acceptCreatorMessage(
              token,
              sceneKey,
              intentKey,
              message,
            );
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
    state.kind === "sending" ||
    state.kind === "unconfirmed" ||
    state.kind === "accepted";

  return (
    <section className="message-composer" aria-labelledby="composer-heading">
      <h2 id="composer-heading">向 ARMI 提供输入</h2>
      <form onSubmit={submit}>
        <label htmlFor="creator-message">输入内容</label>
        <textarea
          id="creator-message"
          name="creator-message"
          rows={5}
          value={message}
          readOnly={locked}
          aria-describedby="composer-note"
          onChange={(event) => {
            setMessage(event.currentTarget.value);
            if (state.kind === "rejected" || state.kind === "idle") {
              setState({ kind: "idle" });
            }
          }}
          onKeyDown={keyDown}
          onCompositionStart={compositionStart}
          onCompositionEnd={compositionEnd}
        />
        <p id="composer-note" className="field-note">
          Enter 发送，Shift+Enter 换行。已接纳正文不会由 timeline 回显。
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
            <button type="submit" disabled={locked}>
              {state.kind === "sending" ? "正在接纳" : "提交输入"}
            </button>
            <button
              type="button"
              className="secondary"
              disabled={locked}
              onClick={() => void send("codex")}
            >
              请求 ARMI 委托 Codex
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
          <div className="composer-recovery">
            <p role="status">
              {state.mode === "codex"
                ? "Codex 委托请求已由 Runtime 耐久接纳；若 ARMI 形成正式委托，你仍须在权限区批准。"
                : "输入已由 Runtime 耐久接纳，可在下方核验责任。"}
            </p>
            <button
              type="button"
              className="secondary"
              onClick={() => setState({ kind: "idle" })}
            >
              开始新输入
            </button>
          </div>
        ) : null}
      </form>
    </section>
  );
}
