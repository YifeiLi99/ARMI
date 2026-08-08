import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import {
  ApiFailure,
  createCreatorExport,
  type CreatorExport,
} from "../../api/client";

type ExportPanelProps = {
  token: string;
  onUnauthorized: () => void;
};

function idempotencyKey(): string {
  return `creator-export-${crypto.randomUUID()}`;
}

export function ExportPanel({ token, onUnauthorized }: ExportPanelProps) {
  const [directoryName, setDirectoryName] = useState("");
  const [result, setResult] = useState<CreatorExport | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const requestIdentity = useRef<{
    directoryName: string;
    key: string;
  } | null>(null);
  const exportMutation = useMutation({
    mutationFn: (name: string) => {
      if (requestIdentity.current?.directoryName !== name) {
        requestIdentity.current = {
          directoryName: name,
          key: idempotencyKey(),
        };
      }
      return createCreatorExport(token, name, requestIdentity.current.key);
    },
    onSuccess: (value) => {
      setResult(value);
      setMessage(
        value.status === "completed"
          ? "本地完整数据导出已完成。"
          : value.status === "partial"
            ? "导出已生成，但有登记制品缺失或损坏；它不是完整备份。"
            : "导出未完成。",
      );
    },
    onError: (error) => {
      if (error instanceof ApiFailure && error.status === 401) {
        onUnauthorized();
        return;
      }
      setMessage(
        error instanceof ApiFailure && error.status === 409
          ? "目录名已使用，或幂等请求发生冲突。"
          : "当前无法生成本地数据导出。",
      );
    },
  });

  return (
    <section className="authority-panel" aria-labelledby="export-heading">
      <div className="panel-heading-row">
        <div>
          <p className="eyebrow">Creator 数据权利</p>
          <h2 id="export-heading">本地完整数据导出</h2>
        </div>
      </div>
      <form
        className="prompt-form"
        onSubmit={(event) => {
          event.preventDefault();
          setMessage(null);
          setResult(null);
          exportMutation.mutate(directoryName);
        }}
      >
        <p className="field-note">
          结果只写入 Runtime 的 data/exports
          目录。它包含同一时点的数据库快照和所有已登记制品；不执行上传、加密或恢复。
        </p>
        <label htmlFor="creator-export-directory">导出目录名</label>
        <input
          id="creator-export-directory"
          value={directoryName}
          required
          maxLength={64}
          pattern="[A-Za-z0-9][A-Za-z0-9._-]{0,63}"
          spellCheck={false}
          disabled={exportMutation.isPending}
          onChange={(event) => setDirectoryName(event.currentTarget.value)}
        />
        <button type="submit" disabled={exportMutation.isPending}>
          {exportMutation.isPending ? "正在导出" : "生成本地导出"}
        </button>
      </form>
      {message === null ? null : <p role="status">{message}</p>}
      {result === null ? null : (
        <dl>
          <div>
            <dt>状态</dt>
            <dd>{result.status}</dd>
          </div>
          <div>
            <dt>数据库</dt>
            <dd>
              {result.table_count} 张表，{result.row_count} 行
            </dd>
          </div>
          <div>
            <dt>已复制制品</dt>
            <dd>{result.artifact_count}</dd>
          </div>
          <div>
            <dt>缺失或损坏</dt>
            <dd>{result.missing_artifacts.length}</dd>
          </div>
          <div>
            <dt>目标路径</dt>
            <dd>{result.destination_path}</dd>
          </div>
          <div>
            <dt>Manifest 摘要</dt>
            <dd>{result.manifest_digest ?? "未生成"}</dd>
          </div>
        </dl>
      )}
    </section>
  );
}
