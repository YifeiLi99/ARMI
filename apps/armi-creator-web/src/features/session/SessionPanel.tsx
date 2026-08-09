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
import { ActivityPanel } from "../activity/ActivityPanel";
import { MaintenancePanel } from "../maintenance/MaintenancePanel";
import { MaterialPanel } from "../material/MaterialPanel";
import { MemoryPanel } from "../memory/MemoryPanel";
import { RelationshipPanel } from "../relationship/RelationshipPanel";
import { CapabilityInbox } from "../capability/CapabilityInbox";
import { EffectDetail } from "../effect/EffectDetail";
import { ExportPanel } from "../export/ExportPanel";
import { DataRightsPanel } from "../dataRights/DataRightsPanel";
import { OperationPanel } from "../operation/OperationPanel";
import { OtherHumanRecordPanel } from "../otherHuman/OtherHumanRecordPanel";
import { PromptPanel } from "../prompt/PromptPanel";
import { TimelinePanel } from "../scene/TimelinePanel";
import { SceneSelector } from "../scene/SceneSelector";
import { SubjectSummaryPanel } from "../subject/SubjectSummaryPanel";
import { PageHeader, WorkspaceNavigation } from "../../app/WorkspaceNavigation";
import type { WorkspacePage } from "../../app/WorkspaceNavigation";

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
  const effectTrigger = useRef<HTMLButtonElement>(null);
  const [code, setCode] = useState("");
  const [selectedOperation, setSelectedOperation] = useState<string | null>(
    null,
  );
  const [selectedEffect, setSelectedEffect] = useState<string | null>(null);
  const [activePage, setActivePage] = useState<WorkspacePage>("conversation");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileNavigationOpen, setMobileNavigationOpen] = useState(false);
  const [selectedScene, setSelectedScene] = useState<{
    key: string;
    status: "open" | "closed";
  } | null>(null);
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
        setSelectedEffect(null);
        setSelectedScene(null);
        setView({
          kind: "bootstrap",
          message: "运行环境已变化，请重新建立会话。",
        });
        return;
      }
      const runtime = await getRuntimeStatus(stored.token, signal);
      setSelectedScene(
        (current) =>
          current ?? { key: session.default_scene_key, status: "open" },
      );
      setView({ kind: "authenticated", stored, session, runtime });
    } catch (error) {
      if (signal?.aborted) {
        return;
      }
      if (error instanceof ApiFailure && error.status === 401) {
        clearStoredSession();
        queryClient.clear();
        setSelectedOperation(null);
        setSelectedEffect(null);
        setSelectedScene(null);
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
      setSelectedEffect(null);
      setSelectedScene(null);
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
    setSelectedEffect(null);
    setSelectedScene(null);
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
    setSelectedEffect(null);
    setSelectedScene(null);
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

  const activeScene = selectedScene ?? {
    key: view.session.default_scene_key,
    status: "open" as const,
  };

  function navigate(page: WorkspacePage) {
    setActivePage(page);
    if (page !== "operation") {
      setSelectedEffect(null);
    }
  }

  return (
    <div className="authenticated-view">
      <WorkspaceNavigation
        activePage={activePage}
        collapsed={sidebarCollapsed}
        mobileOpen={mobileNavigationOpen}
        onNavigate={navigate}
        onToggleCollapsed={() => setSidebarCollapsed((value) => !value)}
        onCloseMobile={() => setMobileNavigationOpen(false)}
      />
      <section className="workspace-main">
        <div className="workspace-toolbar">
          <div className="environment-context">
            <span className="status-dot" aria-hidden="true" />
            <span>{view.session.environment_id}</span>
            <span className="context-separator">/</span>
            <span>{view.runtime.runtime_state}</span>
          </div>
          <button
            type="button"
            className="account-button"
            onClick={() => void logout()}
          >
            <span className="account-avatar" aria-hidden="true">
              C
            </span>
            <span>注销</span>
          </button>
        </div>
        <PageHeader
          page={activePage}
          onOpenMobile={() => setMobileNavigationOpen(true)}
        />
        <div className="page-content">
          <div hidden={activePage !== "conversation"}>
            <div className="conversation-page">
              <SceneSelector
                token={view.stored.token}
                environmentId={view.session.environment_id}
                creatorPartyId={view.session.creator_party_id}
                selectedSceneKey={activeScene.key}
                onSelected={(key, status) => {
                  abortStream();
                  setSelectedOperation(null);
                  setSelectedEffect(null);
                  setSelectedScene({ key, status });
                }}
                onUnauthorized={unauthorized}
              />
              <MessageComposer
                key={activeScene.key}
                token={view.stored.token}
                sceneKey={activeScene.key}
                sceneOpen={activeScene.status === "open"}
                queryClient={queryClient}
                timelineQueryKey={[
                  "scene-timeline",
                  view.session.environment_id,
                  view.session.creator_party_id,
                  activeScene.key,
                ]}
                onUnauthorized={unauthorized}
                onOperationAccepted={(operationRef) => {
                  setSelectedEffect(null);
                  setSelectedOperation(operationRef);
                  setActivePage("operation");
                }}
              />
              <TimelinePanel
                token={view.stored.token}
                environmentId={view.session.environment_id}
                creatorPartyId={view.session.creator_party_id}
                sceneKey={activeScene.key}
                onUnauthorized={unauthorized}
                onOperationSelected={(operationRef) => {
                  setSelectedEffect(null);
                  setSelectedOperation(operationRef);
                  setActivePage("operation");
                }}
                onEffectSelected={(effectRef) => {
                  setSelectedEffect(effectRef);
                  setActivePage("operation");
                }}
                registerStreamAbort={registerStreamAbort}
              />
            </div>
          </div>
          <div hidden={activePage !== "prompt"}>
            <PromptPanel
              token={view.stored.token}
              environmentId={view.session.environment_id}
              creatorPartyId={view.session.creator_party_id}
              onUnauthorized={unauthorized}
            />
          </div>
          <div hidden={activePage !== "export"}>
            <ExportPanel
              token={view.stored.token}
              onUnauthorized={unauthorized}
            />
          </div>
          <div hidden={activePage !== "data-rights"}>
            <DataRightsPanel
              token={view.stored.token}
              environmentId={view.session.environment_id}
              creatorPartyId={view.session.creator_party_id}
              onUnauthorized={unauthorized}
            />
          </div>
          <div hidden={activePage !== "maintenance"}>
            <div className="page-stack">
              <section
                className="session-summary content-panel"
                aria-labelledby="session-heading"
              >
                <div className="panel-heading-row">
                  <div>
                    <p className="eyebrow">连接</p>
                    <h2 id="session-heading">本机 Runtime 状态</h2>
                  </div>
                  <span className="state-badge">
                    <span className="status-dot" />
                    浏览器会话已建立
                  </span>
                </div>
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
                <button
                  type="button"
                  className="secondary"
                  onClick={() => void loadAuthenticated(view.stored)}
                >
                  重新读取状态
                </button>
              </section>
              <MaintenancePanel
                token={view.stored.token}
                environmentId={view.session.environment_id}
                creatorPartyId={view.session.creator_party_id}
                onUnauthorized={unauthorized}
              />
            </div>
          </div>
          <div hidden={activePage !== "activities"}>
            <ActivityPanel
              token={view.stored.token}
              environmentId={view.session.environment_id}
              creatorPartyId={view.session.creator_party_id}
              onUnauthorized={unauthorized}
            />
          </div>
          <div hidden={activePage !== "memory"}>
            <MemoryPanel
              token={view.stored.token}
              environmentId={view.session.environment_id}
              creatorPartyId={view.session.creator_party_id}
              onUnauthorized={unauthorized}
            />
          </div>
          <div hidden={activePage !== "materials"}>
            <MaterialPanel
              token={view.stored.token}
              environmentId={view.session.environment_id}
              creatorPartyId={view.session.creator_party_id}
              onUnauthorized={unauthorized}
            />
          </div>
          <div hidden={activePage !== "relationships"}>
            <RelationshipPanel
              token={view.stored.token}
              environmentId={view.session.environment_id}
              creatorPartyId={view.session.creator_party_id}
              onUnauthorized={unauthorized}
              onOperationAccepted={(operationRef) => {
                setSelectedEffect(null);
                setSelectedOperation(operationRef);
                setActivePage("operation");
              }}
            />
          </div>
          <div hidden={activePage !== "people"}>
            <OtherHumanRecordPanel
              token={view.stored.token}
              environmentId={view.session.environment_id}
              creatorPartyId={view.session.creator_party_id}
              onUnauthorized={unauthorized}
            />
          </div>
          <div hidden={activePage !== "capabilities"}>
            <CapabilityInbox
              token={view.stored.token}
              environmentId={view.session.environment_id}
              creatorPartyId={view.session.creator_party_id}
              onUnauthorized={unauthorized}
            />
          </div>
          <div hidden={activePage !== "operation"}>
            <div className="page-stack">
              {selectedOperation === null ? (
                <section className="content-panel empty-page">
                  <h2>尚未选择操作</h2>
                  <p>
                    从对话记录或关系操作中打开一项操作后，可在这里核验完整责任链。
                  </p>
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => navigate("conversation")}
                  >
                    返回对话
                  </button>
                </section>
              ) : (
                <>
                  <OperationPanel
                    token={view.stored.token}
                    operationRef={selectedOperation}
                    onEffectSelected={setSelectedEffect}
                    onUnauthorized={unauthorized}
                    effectTriggerRef={effectTrigger}
                  />
                  <EffectDetail
                    token={view.stored.token}
                    effectRef={selectedEffect}
                    onClose={() => {
                      setSelectedEffect(null);
                      effectTrigger.current?.focus();
                    }}
                    onUnauthorized={unauthorized}
                  />
                </>
              )}
            </div>
          </div>
          <div hidden={activePage !== "subject"}>
            <SubjectSummaryPanel
              token={view.stored.token}
              environmentId={view.session.environment_id}
              creatorPartyId={view.session.creator_party_id}
              onUnauthorized={unauthorized}
            />
          </div>
        </div>
      </section>
    </div>
  );
}
