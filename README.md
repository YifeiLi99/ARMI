# ARMI

> 承载一个自主电子人长期存在的本地运行时。

**ARMI** 是 **Autonomous Runtime for Mind and Identity**，既是产品名，也是心智、身份与生活过程的运行时名称；它不是她的个人名字。

ARMI 不把人格提示词、模型会话或任务 Agent 当成“她”。当前系统只承载一个持续存在的电子人：同一主体跨越对话、活动、渠道、模型、进程与重启继续生活，并在被正式接纳的经历中形成自己的 Self、Mind、记忆、关系、心情和选择。

对外交互优先服务获得 Creator 委托的 Agent，再服务人类直接操作。`armi` / `armi-mcp` 提供交互使用，`armi-admin` / `armi-admin-mcp` 提供管理、检查与调试；Creator Web 保留。代理不是新的社交主体，代理输入沿正式 intake 记录来源，Creator 管理授权不替代 ARMI 的主体意愿。

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
| 底座/适配器 | Kernel、Runtime Foundation、Local Control、Artifact Store、PostgreSQL contract、NapCat、QQ、ESP32 display 共 8 个包 |
| 数据库 | PostgreSQL 18.4、pgvector 0.8.6、pg_trgm 1.6；唯一 Alembic `0000`；baseline `armi.schema-baseline.v13` |
| 物理 schema | 当前 baseline 108 张表、1364 个字段、1 个只读 view、65 个显式索引；表和生产 DML 都受 owner registry 检查 |
| Creator API | 52 个 OpenAPI path；同源 bearer session、签名分页、SSE 投影失效刷新 |
| 管理面 | CLI/MCP 共用 Admin 应用服务；支持绑定的 `active` / `development` / `system_test` / `acceptance`，具体操作受配置授权约束 |
| 工具链 | Python 3.14.6、Node 24.18.0、uv 0.11.33；精确版本以 lock/manifest 为准 |

已实现的正式路径包括 Creator 文本/多场合对话、其他人隔离交流、Experience、Memory、Relationship、Activity、Material、Mood、Sleep、Prompt、Capability、Effect/outbox、精确生命查询、数据导出与数据权利；可选边界包括本地混合语义召回、ARMI 网页研究、Creator→Codex、QQ/NapCat、实时语音、常驻视觉和 ESP32 私有心情窗。

“仓库存在实现”不等于目标环境已经启用、供应商可用、账号已登录、设备已连接或 live 已验收。

本机文件可以先用 `armi upload import --file <路径> --idempotency-key <稳定键>` 导入，再用 `armi message send --scene-key default --attachments '["<upload_id>"]' --idempotency-key <输入键> --wait` 发送，正文可通过 `--message` 同时提供。MCP 对应 `upload_import`、`message_send`、`operation_get/wait`。上传支持分块续传和重复校验，完成上传不会自动触发认知；发送后沿用同一操作引用查询逐附件识别、交流和效果结果。图片、MP3、MP4、PDF、Office 和文本沿用现有 Perception 格式与体积限制，缺少模型凭据时明确返回不可用原因。

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

模型候选可表达回复、拒绝、不行动、不改变、延期、需要信息、精确生命查询、网页研究或对已启用 camera/screen 的一次视觉观察请求，并可携带有依据的 experience/appraisal/受限 owner changes。模型不能填写主体版本、权限结果、VAD、模型身份、usage 或现实执行结果。慢模型、网络、文件、设备和 Codex I/O 一律在数据库写事务外；回库时重新验证 Runtime fence、work lease、generation 和主体/owner 版本。

## 仓库结构

```text
apps/
  armi-runtime/                 Runtime、交互 CLI/MCP、Creator HTTP、适配器与组合根
  armi-admin/                   独立 Admin CLI/MCP
  armi-creator-web/             React Creator 工作台
modules/                        23 个业务事实 owner
packages/                       8 个稳定底座与边界适配器
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

依赖和 Web 资源在安装时准备。正式管理入口使用 wheel 安装并核对绑定中的 package set；可用 `armi-admin identity` 离线取得当前安装摘要。日常启动读取独立 Admin 绑定，按依赖顺序启动明确归属本环境的 PostgreSQL、语义召回与 Runtime，并等待核心 readiness：

```powershell
.\start_armi.ps1 -AdminConfig C:\path\to\admin.yaml -OpenBrowser
```

环境由 Admin 配置固定，不通过调用参数切换身份。启动不会安装依赖、安装数据库、执行出生或重建 Web。`-OpenBrowser` 是显式选项；共享或外部数据库不会随整体停止回收。

新环境的明确建立顺序：

```powershell
$env:ARMI_ADMIN_CONFIG = 'C:\path\to\admin.yaml'
armi-admin capabilities
armi-admin maintenance --idempotency-key install-001 --json '{"action":"database_install"}'
armi-admin maintenance --idempotency-key birth-001 --json '{"action":"birth"}'
armi-admin start
armi-admin status
armi-admin stop
```

这些命令会连接或修改目标本地环境，执行前应核对绝对路径和 credential locator。完整环境、QQ、音视频、恢复、维护与重置手册见 [安装、启动与维护](docs/05-运行与验证/01-安装、启动与维护.md)。

交互绑定单独使用 `ARMI_CLIENT_CONFIG`，不包含 Admin 数据库凭据。服务器读取绑定环境的 `interaction-access.yaml` 校验代理、Creator、环境和权限；客户端不能在消息参数中改变身份。

```powershell
$env:ARMI_CLIENT_CONFIG = 'C:\path\to\interaction-client.yaml'
armi capabilities
armi message send --scene-key default --message '你好' --idempotency-key message-001 --wait
armi operation wait --result-ref <返回的引用> --timeout-seconds 20
```

CLI 默认输出 JSON，MCP 使用相同请求合同与应用逻辑。接纳不是完成；等待超时或断线返回继续查询的引用，不重新发送输入。用 `armi schema` 和 `armi-admin schema` 离线读取当前操作参数。

`armi artifact read --effect-id <effect-id> --artifact-kind patch --output <文件路径>` 会逐块读取并核验完整摘要，默认不覆盖文件。MCP 的 `artifact_read` 使用 `offset` / `length`，返回下一块位置和同一制品的摘要。

重置、主体内容校正和相关数据删除先取得具体预览及 `authorization_request`，再由独立 Creator 授权绑定签发。相关数据删除使用 `armi-admin data-deletion-preview` 和 `data-deletion-apply`，普通交互请求不能绕过批准：

```powershell
armi-admin --config <Creator授权绑定> authorization approve --request-id <request-id> --expected-request-digest <request-digest> --idempotency-key approval-001
```

普通代理绑定没有签发权限或私钥 locator。执行重置或主体内容校正时提交对应 `authorization_id`；同一凭据不能供另一调用重用。用 `armi-admin invocation get --operation-name <操作名> --idempotency-key <原调用键>` 查询耐久回执；配置修改与包升级不会使旧回执失联。

Creator Web 开发要求先有 ready Runtime：

```powershell
.\tools\start_creator_web_dev.ps1 -EnvironmentRoot 'C:\path\to\environment' -OpenBrowser
```

Vite 固定使用 `127.0.0.1:5173` 并代理现有 Runtime，不启动第二个后端。

## 质量门禁

```powershell
# Fast：锁、格式、lint、类型、离线单测、架构、安全、前端
.\tools\quality.ps1

# Release：Fast + Web/Python 构建 + workspace wheel 隔离安装
.\tools\quality.ps1 -Release

# System：Release + 隔离 PostgreSQL + 固定 Chromium + Creator 系统旅程
.\tools\quality.ps1 -System
```

System 不调用真实模型、Web Search、Codex、QQ 或设备。声称目标环境真实 Creator 对话可用时，必须在获得真实调用授权后运行：

```powershell
uv run python tools/verify_live_creator_roundtrip.py `
  --environment-root C:\path\to\environment `
  --client-config C:\path\to\interaction-client.yaml
```

该 gate 会产生真实对话记录和模型调用，并验证 cognition、Subject Commit、reply Effect、outbox 和回复 artifact。详细 gate 边界见 [质量门禁与 Live 验证](docs/05-运行与验证/02-质量门禁与Live验证.md)。

## 文档

- [DESIGN.md](DESIGN.md)：可提交的当前实现设计总览。
- [docs/README.md](docs/README.md)：私有设计资料总索引。
- [产品定义](docs/01-产品定义/)：ARMI 是谁、生活与关系、真实性/隐私/自主性。
- [系统设计](docs/02-系统设计/)：权威运行时、认知、权限/效果、恢复、Mood。
- [数据设计](docs/03-数据设计/)：事实分层、全局关系、字段合同、108 张表/1364 字段、约束、索引与 ACL。
- [实现参考](docs/04-实现参考/)：模块、配置、接口、模型/Codex/渠道、设备。
- [运行与验证](docs/05-运行与验证/)：运行手册、质量门禁和实测性能基线。
- [外部研究参考](docs/00-外部研究参考/)：带来源的外部证据，不是 ARMI 事实源。

精确事实优先级：当前代码 → packaged schema/`0000` → 配置与锁文件 → 测试与目标环境证据 → 叙述性文档 → 外部研究。文档中的版本数字是当前快照；发生冲突时以机器合同为准并修正文档。

## 研究与许可

ARMI 会研究开源项目和论文，但只吸收有来源、与当前边界相容的设计证据；外部源码观察不会自动成为 ARMI 合同，也不得复制不兼容代码。

本项目当前未授予开源许可证。
