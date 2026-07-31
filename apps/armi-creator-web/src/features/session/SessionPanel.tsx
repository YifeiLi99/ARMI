import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";

import {
  ApiFailure,
  createBrowserSession,
  deleteCurrentBrowserSession,
  getCurrentBrowserSession,
  getRuntimeStatus,
} from "../../api/client";
import type { BrowserSession, RuntimeStatus } from "../../api/client";
import {
  clearStoredSession,
  loadStoredSession,
  saveStoredSession,
} from "./storage";
import type { StoredBrowserSession } from "./storage";
import { MessageComposer } from "../scene/MessageComposer";
import { OperationPanel } from "../scene/OperationPanel";
import { TimelinePanel } from "../scene/TimelinePanel";
import { SubjectSummaryPanel } from "../subject/SubjectSummaryPanel";

type ViewState =
  | { kind: "bootstrap"; message?: string }
  | { kind: "loading"; message: string }
  | {
      kind: "unavailable";
      stored: StoredBrowserSession;
      message: string;
    }
  | {
      kind: "authenticated";
      stored: StoredBrowserSession;
      session: BrowserSession;
      runtime: RuntimeStatus;
      message?: string;
    };

function safeMessage(error: unknown): string {
  if (error instanceof ApiFailure && error.status === 401) {
    return "会话已失效，请使用新的 bootstrap code。";
  }
  return "当前无法连接本机 Runtime，请稍后重试。";
}

export function SessionPanel() {
  const queryClient = useQueryClient();
  const streamAbort = useRef<(() => void) | null>(null);
  const [code, setCode] = useState("");
  const [selectedOperation, setSelectedOperation] = useState<string | null>(
    null,
  );
  const [view, setView] = useState<ViewState>({
    kind: "loading",
    message: "正在核对浏览器会话",
  });
  const registerStreamAbort = useCallback((abort: (() => void) | null) => {
    streamAbort.current = abort;
  }, []);

  function abortStream(): void {
    streamAbort.current?.();
    streamAbort.current = null;
  }

  async function loadAuthenticated(
    stored: StoredBrowserSession,
    signal?: AbortSignal,
  ) {
    try {
      const session = await getCurrentBrowserSession(stored.token, signal);
      if (session.environment_id !== stored.environmentId) {
        abortStream();
        clearStoredSession();
        queryClient.clear();
        setSelectedOperation(null);
        setView({
          kind: "bootstrap",
          message: "运行环境已变化，请重新建立会话。",
        });
        return;
      }
      const runtime = await getRuntimeStatus(stored.token, signal);
      setView({ kind: "authenticated", stored, session, runtime });
    } catch (error) {
      if (signal?.aborted) {
        return;
      }
      if (error instanceof ApiFailure && error.status === 401) {
        clearStoredSession();
        queryClient.clear();
        setSelectedOperation(null);
        setView({ kind: "bootstrap", message: safeMessage(error) });
        return;
      }
      setView({
        kind: "unavailable",
        stored,
        message: safeMessage(error),
      });
    }
  }

  useEffect(() => {
    const stored = loadStoredSession();
    if (stored === null) {
      setView({ kind: "bootstrap" });
      return;
    }
    const controller = new AbortController();
    void loadAuthenticated(stored, controller.signal);
    return () => controller.abort();
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const submittedCode = code;
    setCode("");
    setView({ kind: "loading", message: "正在建立安全浏览器会话" });
    try {
      const established = await createBrowserSession(submittedCode);
      const stored = {
        token: established.browser_session_token,
        expiresAt: established.expires_at,
        environmentId: established.environment_id,
      };
      saveStoredSession(stored);
      await loadAuthenticated(stored);
    } catch (error) {
      clearStoredSession();
      queryClient.clear();
      setSelectedOperation(null);
      setView({
        kind: "bootstrap",
        message:
          error instanceof ApiFailure && error.status === 429
            ? "尝试过于频繁，请稍后再试。"
            : error instanceof ApiFailure && error.status === 401
              ? "bootstrap code 无效或已过期。"
              : safeMessage(error),
      });
    }
  }

  async function logout() {
    if (view.kind !== "authenticated") {
      return;
    }
    const token = view.stored.token;
    abortStream();
    clearStoredSession();
    queryClient.clear();
    setSelectedOperation(null);
    setView({ kind: "bootstrap", message: "浏览器会话已注销。" });
    try {
      await deleteCurrentBrowserSession(token);
    } catch {
      // Local credential removal is authoritative for this tab.
    }
  }

  function unauthorized() {
    abortStream();
    clearStoredSession();
    queryClient.clear();
    setSelectedOperation(null);
    setView({
      kind: "bootstrap",
      message: "会话已失效，请使用新的 bootstrap code。",
    });
  }

  if (view.kind === "loading") {
    return (
      <div className="session-state" role="status" aria-live="polite">
        <span className="status-marker" aria-hidden="true" />
        {view.message}
      </div>
    );
  }

  if (view.kind === "bootstrap") {
    return (
      <form className="session-form" onSubmit={submit}>
        <label htmlFor="bootstrap-code">Bootstrap code</label>
        <p className="field-note">
          在受信终端运行 Creator session 签发命令，再在此输入一次性 code。
        </p>
        <input
          id="bootstrap-code"
          name="bootstrap-code"
          type="password"
          autoComplete="off"
          spellCheck={false}
          required
          pattern="bootstrap-v1\.[A-Za-z0-9_-]{22}"
          maxLength={35}
          value={code}
          onChange={(event) => setCode(event.currentTarget.value)}
        />
        {view.message ? (
          <p className="session-message" role="status">
            {view.message}
          </p>
        ) : null}
        <button type="submit">建立浏览器会话</button>
      </form>
    );
  }

  if (view.kind === "unavailable") {
    return (
      <section className="session-state" aria-live="polite">
        <p role="status">{view.message}</p>
        <button
          type="button"
          onClick={() => void loadAuthenticated(view.stored)}
        >
          重新连接
        </button>
      </section>
    );
  }

  return (
    <div className="authenticated-view">
      <section className="session-summary" aria-labelledby="session-heading">
        <p className="runtime-status" role="status" aria-live="polite">
          <span className="status-marker is-ready" aria-hidden="true" />
          浏览器会话已建立
        </p>
        <h2 id="session-heading">本机 Runtime 状态</h2>
        <dl>
          <div>
            <dt>生命周期</dt>
            <dd>{view.runtime.runtime_state}</dd>
          </div>
          <div>
            <dt>接纳状态</dt>
            <dd>{view.runtime.readiness}</dd>
          </div>
          <div>
            <dt>会话到期</dt>
            <dd>{view.session.expires_at}</dd>
          </div>
        </dl>
        <div className="session-actions">
          <button
            type="button"
            onClick={() => void loadAuthenticated(view.stored)}
          >
            重新读取状态
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() => void logout()}
          >
            注销
          </button>
        </div>
        <p className="boundary-note">
          当前只显示经认证的本机 Runtime 安全状态。
        </p>
      </section>
      <MessageComposer
        token={view.stored.token}
        sceneKey={view.session.default_scene_key}
        queryClient={queryClient}
        timelineQueryKey={[
          "scene-timeline",
          view.session.environment_id,
          view.session.creator_party_id,
          view.session.default_scene_key,
        ]}
        onUnauthorized={unauthorized}
        onOperationAccepted={setSelectedOperation}
      />
      <TimelinePanel
        token={view.stored.token}
        environmentId={view.session.environment_id}
        creatorPartyId={view.session.creator_party_id}
        sceneKey={view.session.default_scene_key}
        onUnauthorized={unauthorized}
        onOperationSelected={setSelectedOperation}
        registerStreamAbort={registerStreamAbort}
      />
      <OperationPanel
        token={view.stored.token}
        operationRef={selectedOperation}
        onUnauthorized={unauthorized}
      />
      <SubjectSummaryPanel
        token={view.stored.token}
        onUnauthorized={unauthorized}
      />
    </div>
  );
}
