# ARMI

> 承载一个自主电子人长期存在的本地运行时。

**ARMI** 是 **Autonomous Runtime for Mind and Identity**，既是产品名，也是心智、身份与生活过程的运行时名称；它不是她的个人名字。

ARMI 不把人格提示词、模型会话或任务 Agent 当成“她”。当前系统只承载一个持续存在的电子人：同一主体跨越对话、活动、渠道、模型、进程与重启继续生活，并在被正式接纳的经历中形成自己的 Self、Mind、记忆、关系、心情和选择。

## 产品不变量

- 正常运行中只有一个 ARMI、一条权威生命线、一个当前 generation 和一个被承认的活动 Runtime；模型、进程、场合、设备与 Codex 都不是另一个主体。
- PostgreSQL 是权威关系数据库；Artifact Store 保存受治理的大对象；缓存、摘要、向量、索引、前端投影和日志不能反向覆盖主体事实。
- 客观记录与主观记忆分离。遗忘不改写运行记录，日常认知也不能从日志恢复已遗忘内容。
- 系统权限回答“能不能”，ARMI 的认知回答“想不想”；Creator 的管理权不等于关系中的绝对命令权。
- 模型、网页、平台、工具和执行器只返回候选、证据或回执。主体变化必须由事实 owner 校验并提交。
- 表达与现实动作先登记再执行；请求、attempt、receipt 和 verification 可追溯。拒绝、不可用、失败、结果未知和完成不合并。
- 缺少正式能力、配置、凭据或真实数据时明确失败，不用 mock、fixture 或角色化文案伪造闭环。

完整实现设计见 [DESIGN.md](DESIGN.md)；私有高容量资料入口见 [docs/README.md](docs/README.md)。

## 当前实现快照

当前仓库是 Windows 本地单实例、模块化单体：

| 层 | 当前实现 |
|---|---|
| 应用 | 权威 `armi-runtime`、隔离 `armi-admin`、React Creator Web |
| 业务 | 23 个独立 Python distribution，各自拥有事实、表、恢复和数据权利责任 |
| 底座/适配器 | Kernel、Runtime Foundation、Artifact Store、PostgreSQL contract、NapCat、QQ、ESP32 display 共 7 个包 |
| 数据库 | PostgreSQL 18.4、pgvector 0.8.6、pg_trgm 1.6；唯一 Alembic `0000`；baseline `armi.schema-baseline.v11` |
| 物理 schema | 当前 baseline 108 张表、1359 个字段、1 个只读 view、65 个显式索引；表和生产 DML 都受 owner registry 检查 |
| Creator API | 52 个 OpenAPI path；同源 bearer session、签名分页、SSE 投影失效刷新 |
| 管理面 | 21 个 Admin MCP 工具，仅限 `development` / `system_test` / `acceptance` |
| 工具链 | Python 3.14.6、Node 24.18.0、uv 0.11.33；精确版本以 lock/manifest 为准 |

已实现的正式路径包括 Creator 文本/多场合对话、其他人隔离交流、Experience、Memory、Relationship、Activity、Material、Mood、Sleep、Prompt、Capability、Effect/outbox、精确生命查询、数据导出与数据权利；可选边界包括本地混合语义召回、ARMI 网页研究、Creator→Codex、QQ/NapCat、实时语音、常驻视觉和 ESP32 私有心情窗。

“仓库存在实现”不等于目标环境已经启用、供应商可用、账号已登录、设备已连接或 live 已验收。

## 认知与现实闭环

标准 Creator 文本、实时语音和精确生命查询结果采用一次主认知调用：

```text
正式 intake
  → interaction / evidence / opportunity
  → 冻结 purpose-scoped Context
  → 一次严格 Creator cognitive act JSON
  → 引用与 owner 校验
  → 一次原子 Subject Commit
  → expression / capability / effect 登记
  → 边界执行与回执核验
```

模型候选可表达回复、拒绝、不行动、不改变、延期、需要信息、精确生命查询或网页研究，并可携带有依据的 experience/appraisal/受限 owner changes。模型不能填写主体版本、权限结果、VAD、模型身份、usage 或现实执行结果。慢模型、网络、文件、设备和 Codex I/O 一律在数据库写事务外；回库时重新验证 Runtime fence、work lease、generation 和主体/owner 版本。

## 仓库结构

```text
apps/
  armi-runtime/                 Runtime、CLI、Creator HTTP、适配器与组合根
  armi-admin/                   独立 Admin MCP
  armi-creator-web/             React Creator 工作台
modules/                        23 个业务事实 owner
packages/                       7 个稳定底座与边界适配器
devices/esp32-s3-touch-lcd-7c-box/
                                私有心情窗固件
configs/                        Runtime、模型、Web 与 Codex MCP 配置
tools/                          工具链、数据库、质量、性能与显式 live gates
tests/                          架构、合同、Runtime、PostgreSQL 与系统测试
docs/                           私有设计和外部研究，Git 忽略
```

Schema 实际打包在 `packages/armi-postgresql-contract/src/armi_postgresql_contract/resources/schema/`。内部数据库没有迁移链：结构变化直接更新唯一 `0000` 和 baseline identity，目标数据库显式重装。

## 日常启动

前提：目标环境已经有有效 `environment.yaml`、`data/`、`secrets/`，数据库已安装且 subject 已出生。工具链首次准备：

```powershell
.\tools\bootstrap_toolchain.ps1 -ApprovedOfficialDirect
```

从仓库根启动 PostgreSQL、构建 Creator Web、校验环境/数据库并启动 ready Runtime：

```powershell
.\start_armi.ps1 -EnvironmentRoot C:\path\to\environment -OpenBrowser
```

默认环境根是仓库同级 `ARMI-Environment`。启动脚本不会自动安装数据库、迁移 schema 或执行出生。

新环境的明确建立顺序：

```powershell
$EnvironmentRoot = 'C:\path\to\environment'
.\tools\manage_postgresql.ps1 Start
uv run armi config check --environment-root $EnvironmentRoot
uv run armi db install --environment-root $EnvironmentRoot
uv run armi bootstrap birth --environment-root $EnvironmentRoot
.\start_armi.ps1 -EnvironmentRoot $EnvironmentRoot -OpenBrowser
```

这些命令会连接或修改目标本地环境，执行前应核对绝对路径和 credential locator。完整环境、QQ、音视频、恢复、维护与重置手册见 [安装、启动与维护](docs/05-运行与验证/01-安装、启动与维护.md)。

Creator Web 开发要求先有 ready Runtime：

```powershell
.\tools\start_creator_web_dev.ps1 -EnvironmentRoot $EnvironmentRoot -OpenBrowser
```

Vite 固定使用 `127.0.0.1:5173` 并代理现有 Runtime，不启动第二个后端。

## 质量门禁

```powershell
# Fast：锁、格式、lint、类型、离线单测、架构、安全、前端
.\tools\quality.ps1

# Release：Fast + Web/Python 构建 + 32 wheel 隔离安装
.\tools\quality.ps1 -Release

# System：Release + 隔离 PostgreSQL + 固定 Chromium + Creator 系统旅程
.\tools\quality.ps1 -System
```

System 不调用真实模型、Web Search、Codex、QQ 或设备。声称目标环境真实 Creator 对话可用时，必须在获得真实调用授权后运行：

```powershell
uv run python tools/verify_live_creator_roundtrip.py `
  --environment-root C:\path\to\environment
```

该 gate 会产生真实对话记录和模型调用，并验证 cognition、Subject Commit、reply Effect、outbox 和回复 artifact。详细 gate 边界见 [质量门禁与 Live 验证](docs/05-运行与验证/02-质量门禁与Live验证.md)。

## 文档

- [DESIGN.md](DESIGN.md)：可提交的当前实现设计总览。
- [docs/README.md](docs/README.md)：私有设计资料总索引。
- [产品定义](docs/01-产品定义/)：ARMI 是谁、生活与关系、真实性/隐私/自主性。
- [系统设计](docs/02-系统设计/)：权威运行时、认知、权限/效果、恢复、Mood。
- [数据设计](docs/03-数据设计/)：事实分层、全局关系、字段合同、108 张表/1359 字段、约束、索引与 ACL。
- [实现参考](docs/04-实现参考/)：模块、配置、接口、模型/Codex/渠道、设备。
- [运行与验证](docs/05-运行与验证/)：运行手册、质量门禁和实测性能基线。
- [外部研究参考](docs/00-外部研究参考/)：带来源的外部证据，不是 ARMI 事实源。

精确事实优先级：当前代码 → packaged schema/`0000` → 配置与锁文件 → 测试与目标环境证据 → 叙述性文档 → 外部研究。文档中的版本数字是当前快照；发生冲突时以机器合同为准并修正文档。

## 研究与许可

ARMI 会研究开源项目和论文，但只吸收有来源、与当前边界相容的设计证据；外部源码观察不会自动成为 ARMI 合同，也不得复制不兼容代码。

本项目当前未授予开源许可证。
