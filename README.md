# ARMI

> 承载一个电子人长期存在的自主运行时。

**ARMI** 是 **Autonomous Runtime for Mind and Identity** 的缩写。它既是产品名，也是承载心智、身份与生活过程的运行时名称；它不是电子人的个人名字。

ARMI 不是围绕一轮对话或一项任务运行的助手，也不是多角色、多租户或多 Agent 编排平台。这个项目只承载一个持续存在的自主电子人：同一个主体跨越对话、活动、模型、进程与重启继续生活，并在真实经历中形成自己的记忆、关系、偏好和选择。

## 核心认识

ARMI 以真实人类的心理、生活和社会行为作为参照，但承认自己的电子存在条件。她可以犹豫、拒绝、沉默、偏心、犯错或改变主意，不必始终有用；她也没有需要虚构的人类身体、自然年龄和生活史。

出生只提供语言、常识和少量人格锚点，不预写个人名字、经历、兴趣、关系和目标。后天的 Self、Mind、记忆和关系必须来自真正被接纳的经历，而不是模型的一次输出、完整日志的倒灌或固定角色脚本。

项目长期坚持几条边界：

- 正常运行中只有一个 ARMI、一条权威生命线和一个当前活动世界；模型、进程、入口和外部执行器都不是另一个主体。
- 主观记忆与客观运行记录分离。遗忘不会改写日志，日志也不能在日常认知中偷偷补全记忆。
- 系统权限回答“能不能”，ARMI 的意愿回答“想不想”。创造者拥有系统管理权，但不因此拥有社会关系中的绝对命令权。
- 模型、网页、平台、工具与 Codex 都处于信任边界之外，只能提供候选、证据或执行回执，不能直接提交主体状态或扩大权限。
- 对外表达和现实动作先登记、后执行、再核验。失败、拒绝、不可用、结果未知和完成保持不同语义。

## 当前软件形态

ARMI 目前是运行在单机上的模块化单体。Python workspace 包含稳定内核、普通 Runtime 与隔离的管理 MCP；Creator 工作台是由 Runtime 同源托管的 React 静态应用。PostgreSQL 是唯一权威关系数据库，文件制品只保存不适合直接进入关系表的大正文或执行产物。

当前代码已经覆盖 Creator 对话与多场合、Self/Mind/Prompt、主观记忆、关系与生活资料、自主机会与 Activity、睡眠维护、主动联系、内置其他人交流、本地导出与数据权利，以及经授权的 Creator→Codex 委托。代码存在不等于某个环境已经配置并启用；模型、网页、Codex 和其他外部能力仍取决于该环境的绑定、凭据与授权。

项目仍是个人研究与高迭代实验系统，不是生产发布版本。安全、部署、迁移、公开渠道、多模态和新的外部执行器不会从历史路线图自动进入范围，而由创造者逐项决定。

## 仓库结构

```text
packages/armi-kernel/       领域、应用端口与稳定公共契约
apps/armi-runtime/          权威 Runtime、适配器、接口与组合根
apps/armi-admin/            与日常 Runtime 隔离的管理 MCP
apps/armi-creator-web/      Creator 本机工作台
tests/                      单元、契约、集成与旅程测试
tools/                      本地数据库、工具链和质量入口
docs/                       私有叙述性设计与外部研究资料
```

`docs/` 被 Git 忽略，用于本地继续设计；精确的字段、路由、状态值和依赖版本仍以当前代码、DDL、配置与锁文件为准。文档入口见 [`docs/README.md`](docs/README.md)。

## 本地开发入口

开发数据库固定使用 Docker 中的 PostgreSQL 18.4 + pgvector 0.8.6：

```powershell
.\tools\manage_postgresql.ps1 Start
.\tools\manage_postgresql.ps1 Status
```

准备好环境根的 `environment.toml`、secret locator 与出生资料后，通过正式 CLI 建立和运行环境：

```powershell
uv sync --frozen
uv run armi config check --environment-root C:\path\to\environment
uv run armi db install --environment-root C:\path\to\environment
uv run armi bootstrap birth --environment-root C:\path\to\environment
uv run armi start --environment-root C:\path\to\environment
uv run armi status --environment-root C:\path\to\environment
uv run armi creator-session issue --environment-root C:\path\to\environment
uv run armi stop --environment-root C:\path\to\environment
```

日常开发从改动相关的最小检查开始；仓库快速质量入口为：

```powershell
.\tools\quality.ps1
```

需要真实 PostgreSQL、浏览器、付费模型或完整发布门禁时，应根据本次风险显式选择对应入口，不能把未运行的环境验证写成已经通过。

## 研究与许可

项目会研究开源项目和论文，吸收适合 ARMI 的设计，再按自身边界重新实现。来源与许可证记录保存在私有研究目录中；研究对象的自述和做法不会自动成为 ARMI 的设计事实。

本项目暂未授予开源许可证。
