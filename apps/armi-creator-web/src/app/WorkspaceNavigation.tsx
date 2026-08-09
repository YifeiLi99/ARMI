import type { ReactNode } from "react";

export type WorkspacePage =
  | "conversation"
  | "activities"
  | "memory"
  | "materials"
  | "relationships"
  | "people"
  | "prompt"
  | "capabilities"
  | "maintenance"
  | "export"
  | "data-rights"
  | "subject"
  | "operation";

type NavigationItem = {
  page: WorkspacePage;
  label: string;
  icon: IconName;
};

type NavigationGroup = {
  label: string;
  items: NavigationItem[];
};

type IconName =
  | "chat"
  | "spark"
  | "memory"
  | "file"
  | "heart"
  | "people"
  | "prompt"
  | "shield"
  | "pulse"
  | "download"
  | "trash"
  | "subject"
  | "operation"
  | "sidebar";

const navigationGroups: NavigationGroup[] = [
  {
    label: "交流",
    items: [
      { page: "conversation", label: "对话", icon: "chat" },
      { page: "people", label: "其他人", icon: "people" },
    ],
  },
  {
    label: "生活",
    items: [
      { page: "activities", label: "活动", icon: "spark" },
      { page: "memory", label: "记忆", icon: "memory" },
      { page: "materials", label: "生活资料", icon: "file" },
      { page: "relationships", label: "关系", icon: "heart" },
    ],
  },
  {
    label: "心智与权限",
    items: [
      { page: "prompt", label: "认知指导", icon: "prompt" },
      { page: "capabilities", label: "能力授权", icon: "shield" },
    ],
  },
  {
    label: "系统",
    items: [
      { page: "maintenance", label: "运行与维护", icon: "pulse" },
      { page: "export", label: "数据导出", icon: "download" },
      { page: "data-rights", label: "数据权利", icon: "trash" },
      { page: "subject", label: "主体状态", icon: "subject" },
    ],
  },
];

const pageMeta: Record<WorkspacePage, { title: string; description: string }> =
  {
    conversation: {
      title: "对话",
      description: "在独立场合中交流，并核验每次输入形成的耐久记录。",
    },
    activities: {
      title: "活动",
      description: "查看 ARMI 当前关注的活动以及生活过程。",
    },
    memory: {
      title: "记忆",
      description: "查询主观记忆及其变化，而不以运行日志补全遗忘。",
    },
    materials: {
      title: "生活资料",
      description: "阅读被正式保存的生活材料与版本信息。",
    },
    relationships: {
      title: "关系",
      description: "查看关系事实、变化与 Creator 边界。",
    },
    people: {
      title: "其他人",
      description: "查看不同参与者各自隔离的场合与交流记录。",
    },
    prompt: {
      title: "认知指导",
      description: "查看和更新 Creator 提供的认知指导 Prompt。",
    },
    capabilities: {
      title: "能力授权",
      description: "逐项审阅能力申请、约束范围并管理当前授权。",
    },
    maintenance: {
      title: "运行与维护",
      description: "观察 Runtime 与维护阶段，必要时执行明确的恢复动作。",
    },
    export: {
      title: "数据导出",
      description: "生成可核验的本地完整数据导出。",
    },
    "data-rights": {
      title: "数据权利",
      description: "查看并执行具有明确影响范围的数据权利命令。",
    },
    subject: {
      title: "主体状态",
      description: "核验当前权威主体版本及各组件版本。",
    },
    operation: {
      title: "操作详情",
      description: "核验一次操作的责任、进度与现实效果。",
    },
  };

function Icon({ name }: { name: IconName }) {
  const paths: Record<IconName, ReactNode> = {
    chat: (
      <>
        <path d="M5 6.75h14v9.5H9l-4 3v-12.5Z" />
        <path d="M8.5 10.5h7M8.5 13h4.5" />
      </>
    ),
    spark: (
      <>
        <path d="m12 3 1.35 4.15L17.5 8.5l-4.15 1.35L12 14l-1.35-4.15L6.5 8.5l4.15-1.35L12 3Z" />
        <path d="m18.5 14 .7 2.3 2.3.7-2.3.7-.7 2.3-.7-2.3-2.3-.7 2.3-.7.7-2.3Z" />
      </>
    ),
    memory: (
      <>
        <path d="M8.5 5.5a3 3 0 0 0-3 3v7a3 3 0 0 0 3 3" />
        <path d="M15.5 5.5a3 3 0 0 1 3 3v7a3 3 0 0 1-3 3M9 8.5h6M9 12h6M9 15.5h4" />
      </>
    ),
    file: (
      <>
        <path d="M7 3.5h7l4 4v13H7v-17Z" />
        <path d="M14 3.5v4h4M10 12h5M10 15.5h5" />
      </>
    ),
    heart: (
      <path d="M20 8.8c0 5.2-8 10-8 10s-8-4.8-8-10a4.3 4.3 0 0 1 7.7-2.65L12 6.6l.3-.45A4.3 4.3 0 0 1 20 8.8Z" />
    ),
    people: (
      <>
        <circle cx="9" cy="8" r="3" />
        <path d="M3.5 19a5.5 5.5 0 0 1 11 0M15.5 6.2a3 3 0 0 1 0 5.6M17 14.2a5.3 5.3 0 0 1 3.5 4.8" />
      </>
    ),
    prompt: (
      <>
        <path d="M5 4.5h14v15H5z" />
        <path d="m8 9 2 2-2 2M12.5 14H16" />
      </>
    ),
    shield: (
      <>
        <path d="M12 3.5 19 6v5.2c0 4.6-3 7.5-7 9.3-4-1.8-7-4.7-7-9.3V6l7-2.5Z" />
        <path d="m9.2 12 1.8 1.8 4-4" />
      </>
    ),
    pulse: (
      <>
        <path d="M3.5 12h4l2-5 4 10 2-5h5" />
        <circle cx="12" cy="12" r="9" />
      </>
    ),
    download: (
      <>
        <path d="M12 3.5v11M8 11l4 4 4-4" />
        <path d="M5 19.5h14" />
      </>
    ),
    trash: (
      <>
        <path d="M5 7h14M9 7V4.5h6V7M7 7l1 13h8l1-13M10 10.5v6M14 10.5v6" />
      </>
    ),
    subject: (
      <>
        <circle cx="12" cy="8" r="3.5" />
        <path d="M5.5 20a6.5 6.5 0 0 1 13 0" />
      </>
    ),
    operation: (
      <>
        <path d="M4.5 7.5h10M4.5 12h15M4.5 16.5h8" />
        <circle cx="18" cy="7.5" r="1.5" />
        <circle cx="15.5" cy="16.5" r="1.5" />
      </>
    ),
    sidebar: (
      <>
        <rect x="3.5" y="4" width="17" height="16" rx="2" />
        <path d="M9 4v16" />
      </>
    ),
  };
  return (
    <svg className="ui-icon" viewBox="0 0 24 24" aria-hidden="true">
      {paths[name]}
    </svg>
  );
}

type WorkspaceNavigationProps = {
  activePage: WorkspacePage;
  collapsed: boolean;
  mobileOpen: boolean;
  onNavigate: (page: WorkspacePage) => void;
  onToggleCollapsed: () => void;
  onCloseMobile: () => void;
};

export function WorkspaceNavigation({
  activePage,
  collapsed,
  mobileOpen,
  onNavigate,
  onToggleCollapsed,
  onCloseMobile,
}: WorkspaceNavigationProps) {
  return (
    <>
      {mobileOpen ? (
        <button
          className="nav-scrim"
          type="button"
          aria-label="关闭导航"
          onClick={onCloseMobile}
        />
      ) : null}
      <aside
        className={`workspace-sidebar${collapsed ? " is-collapsed" : ""}${mobileOpen ? " is-mobile-open" : ""}`}
      >
        <div className="sidebar-brand">
          <div className="brand-mark" aria-hidden="true">
            A
          </div>
          <div className="brand-copy">
            <strong>ARMI</strong>
            <span>Creator</span>
          </div>
          <button
            className="icon-button collapse-button"
            type="button"
            aria-label={collapsed ? "展开导航" : "收起导航"}
            onClick={onToggleCollapsed}
          >
            <Icon name="sidebar" />
          </button>
        </div>
        <nav className="primary-navigation" aria-label="Creator 功能">
          {navigationGroups.map((group) => (
            <div className="navigation-group" key={group.label}>
              <p className="navigation-label">{group.label}</p>
              {group.items.map((item) => (
                <button
                  className="navigation-item"
                  type="button"
                  key={item.page}
                  aria-current={activePage === item.page ? "page" : undefined}
                  title={collapsed ? item.label : undefined}
                  onClick={() => {
                    onNavigate(item.page);
                    onCloseMobile();
                  }}
                >
                  <Icon name={item.icon} />
                  <span>{item.label}</span>
                </button>
              ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-footer">
          <span className="status-dot" />
          本机 Runtime
        </div>
      </aside>
    </>
  );
}

export function PageHeader({
  page,
  onOpenMobile,
}: {
  page: WorkspacePage;
  onOpenMobile: () => void;
}) {
  const meta = pageMeta[page];
  return (
    <header className="page-header">
      <button
        className="icon-button mobile-menu-button"
        type="button"
        aria-label="打开导航"
        onClick={onOpenMobile}
      >
        <Icon name="sidebar" />
      </button>
      <div>
        <h1>{meta.title}</h1>
        <p>{meta.description}</p>
      </div>
    </header>
  );
}
