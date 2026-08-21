import type { RuntimeStatus } from "../../api/client";
import { ComponentSwitch } from "./ComponentSwitch";

type RequiredComponentsCardProps = {
  runtime: RuntimeStatus;
  onRefresh: () => void;
};

const COMPONENT_META = {
  database: { title: "PostgreSQL", description: "权威数据库与当前 schema" },
  runtime: { title: "核心 Runtime", description: "主体生命线、任务与接口" },
  creator_web: {
    title: "Creator 前端",
    description: "同源静态资源与浏览器会话",
  },
} as const;

const STATE_LABELS = {
  ready: "健康",
  degraded: "降级",
  unavailable: "不可用",
} as const;

export function RequiredComponentsCard({
  runtime,
  onRefresh,
}: RequiredComponentsCardProps) {
  return (
    <section
      className="authority-panel component-console"
      aria-labelledby="required-components-heading"
    >
      <div className="panel-heading-row">
        <div>
          <p className="eyebrow">基础运行层</p>
          <h2 id="required-components-heading">必需组件</h2>
        </div>
        <button type="button" className="secondary" onClick={onRefresh}>
          重新检测
        </button>
      </div>
      <div className="component-list">
        {runtime.components.map((component) => {
          const meta = COMPONENT_META[component.component];
          return (
            <article className="component-row" key={component.component}>
              <div className="component-copy">
                <div className="component-title-line">
                  <h3>{meta.title}</h3>
                  <span
                    className="component-health"
                    data-state={component.state}
                  >
                    {STATE_LABELS[component.state]}
                  </span>
                </div>
                <p>{meta.description}</p>
                {component.reason_codes.map((reason) => (
                  <small key={reason}>状态原因：{reason}</small>
                ))}
              </div>
              <ComponentSwitch label={meta.title} checked disabled />
            </article>
          );
        })}
      </div>
      <p className="boundary-note">
        必需组件由本机启动器统一管理，因此固定开启。数据库或 Runtime
        停止后此页面也会不可达，恢复仍使用本机启动入口。
      </p>
    </section>
  );
}
