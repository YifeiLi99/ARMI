# ARMI

> 承载一个自主电子人长期存在的本地运行时。

**ARMI** 是 **Autonomous Runtime for Mind and Identity**，既是产品名，也是心智、身份与生活过程的运行时名称；它不是她的个人名字。

ARMI 不把人格提示词、模型会话或任务 Agent 当成“她”。当前系统只承载一个持续存在的电子人：同一主体跨越对话、活动、渠道、模型、进程与重启继续生活，并在被正式接纳的经历中形成自己的 Self、Mind、记忆、关系、心情和选择。

对外交互优先服务获得 Creator 委托的 Agent，再服务人类直接操作。`ARMI cli interaction` / `ARMI mcp interaction` 提供交互使用，`ARMI cli admin` / `ARMI mcp admin` 提供管理、检查与调试；Creator Web 保留。代理不是新的社交主体，代理输入沿正式 intake 记录来源，Creator 管理授权不替代 ARMI 的主体意愿。

产品以完整、直接、高效的 Agent/LLM 自动化链路为第一优先级，人类界面为第二优先级。已开启的能力在配置范围内持续可用，不额外设置申请、审核、批准流程；普通回复是基础能力。简化应减少无独立职责的步骤、状态和重复记录，同时保留隐私、数据保护与执行正确性。普通 Creator 文本、语音、QQ 私聊及共用回复链的主动表达已采用直接执行、中断即结束；Codex 委托同样直接执行、中断即结束：通过 `codex.enabled` 开启后重启生效，默认关闭；执行器或凭据不可用会明确失败。保留 Creator／代理提交任务入口，由 ARMI 决定委托并自行理解结果，无逐次审批。管理端授权保持独立合同。

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
| 应用 | 统一入口 `armi-app`、权威 `armi-runtime`、隔离 `armi-admin`、React Creator Web |
| 业务 | 23 个独立 Python distribution；Capability 仅保留静态目录，其余按 owner 承担事实、恢复和数据权利责任 |
| 底座/适配器 | Kernel、Runtime Foundation、Local Control、Artifact Store、PostgreSQL contract、NapCat、QQ、ESP32 display 共 8 个包 |
| 数据库 | PostgreSQL 18.4、pgvector 0.8.6、pg_trgm 1.6；唯一 Alembic `0000`；baseline `armi.schema-baseline.v16` |
| 物理 schema | 当前 baseline 101 张表、1269 个字段、1 个只读 view、62 个显式索引；表和生产 DML 都受 owner registry 检查 |
| Creator API | 52 个 OpenAPI path；同源 bearer session、签名分页、SSE 投影失效刷新 |
| 管理面 | CLI/MCP 共用 Admin 应用服务；支持绑定的 `active` / `development` / `system_test` / `acceptance`，具体操作受配置授权约束 |
| 工具链 | Python 3.14.6、Node 24.18.0、uv 0.11.33；精确版本以 lock/manifest 为准 |

已实现的正式路径包括 Creator 文本/多场合对话、其他人隔离交流、Experience、Memory、Relationship、Activity、Material、Mood、Sleep、Prompt、Capability、Effect/outbox、精确生命查询、数据导出与数据权利；可选边界包括本地混合语义召回、ARMI 网页研究、Creator→Codex、QQ/NapCat、实时语音、常驻视觉和 ESP32 私有心情窗。

“仓库存在实现”不等于目标环境已经启用、供应商可用、账号已登录、设备已连接或 live 已验收。

本机文件可以先用 `ARMI cli interaction upload import --file <路径> --idempotency-key <稳定键>` 导入，再用 `ARMI cli interaction message send --scene-key default --attachments '["<upload_id>"]' --idempotency-key <输入键> --wait` 发送，正文可通过 `--message` 同时提供。MCP 对应 `upload_import`、`message_send`、`operation_get/wait`。上传支持分块续传和重复校验，完成上传不会自动触发认知；发送后沿用同一操作引用查询逐附件识别、交流和效果结果。图片、MP3、MP4、PDF、Office 和文本沿用现有 Perception 格式与体积限制，缺少模型凭据时明确返回不可用原因。

## 认知与现实闭环

标准 Creator 文本、实时语音和精确生命查询结果采用一次主认知调用：

```text
正式 intake
  → interaction / evidence / opportunity
  → 冻结 purpose-scoped Context
  → cognition.execute：一次模型调用 → 候选校验 → 制品准备
  → 原子提交校验/应用结果 + 主体变化 + 意图 + Effect/outbox + 工作结算
  → 边界执行与回执核验
```

所有共用认知（包括其他人对话、自主活动、Codex 和睡眠整理）中断即结束本轮。模型响应成功先单独保存，后续校验或提交失败不改写模型调用结果；`finalizing` 表示正在校验、准备制品并提交。长期活动与维护进度保留，由原调度重新准备新 Context，不读取旧响应或候选续算。

模型候选可表达回复、拒绝、不行动、不改变、延期、需要信息、精确生命查询、网页研究或对已启用 camera/screen 的一次视觉观察请求，并可携带有依据的 experience/appraisal/受限 owner changes。模型不能填写主体版本、权限结果、VAD、模型身份、usage 或现实执行结果。慢模型、网络、文件、设备和 Codex I/O 一律在数据库写事务外；回库时重新验证 Runtime fence、work lease、generation 和主体/owner 版本。

## 仓库结构

```text
apps/
  armi-app/                     统一桌面、CLI 与 MCP 模式入口
  armi-runtime/                 Runtime、交互 CLI/MCP、Creator HTTP、适配器与组合根
  armi-admin/                   独立 Admin CLI/MCP
  armi-creator-web/             React Creator 工作台
modules/                        23 个业务模块
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

**Windows 安装版使用 MSIX，程序由 Windows 管理，永久数据保存在 `%LOCALAPPDATA%\ARMI`。** 其中 `environments/active/` 保存数据库、配置、凭据、模型和生活数据，`control/` 保存设置、环境登记、管理回执和更新状态，`cache/`、`tmp/` 保存缓存与临时文件。程序目录保持只读；数据目录通过 Known Folder API 定位，使用 MSIX 目录虚拟化排除声明，普通卸载后仍保留。

桌面入口使用上述默认环境，安装版 CLI/MCP 的显式环境也必须位于数据目录的 `environments/` 下。测试包使用独立的 `YifeiLi99.ARMI.Acceptance` 包身份、`ARMI.Acceptance.exe` 别名和 `%LOCALAPPDATA%\ARMI.Acceptance` 数据目录。本次不迁移、修改或删除旧 Inno 安装与数据；源码构建目录和 `.armi/reusable/` 仍是开发资源区域。

Windows 11 x64 安装版包含原生 PostgreSQL、扩展、私有 Python 和已构建网页；用户不需要 Docker、全局 Python/Node、PowerShell 7 或编译器。通过开始菜单或执行别名打开 ARMI。环境准备与出生分开，未显式出生不会进入正常生活；普通启动只检查和启动已有环境。可选能力默认关闭，登录自启使用默认关闭的 Windows StartupTask，并尊重用户在系统中的禁用状态。

`ARMI.exe` 是唯一对外主入口。未配置时进入设置；正常启动成功后打开 Creator Web，托盘提供设置与退出。重复启动复用同环境实例。AI 使用同一程序的 `cli interaction/admin/setup` 或 `mcp interaction/admin/setup` 模式，MCP 每次只加载一种独立权限的服务。`ARMI.exe settings` 直接打开设置。卸载使用 Windows 的应用管理，不交付独立卸载 EXE。长期进程由系统激活的私有环境宿主监督，CLI/MCP 退出不会误停环境；宿主或包被终止时，所属进程随 Job 结束。

下文 `ARMI` 代表执行别名 `ARMI.exe`。机器接入使用稳定的绝对路径 `%LOCALAPPDATA%\Microsoft\WindowsApps\ARMI.exe` 和参数数组，不绑定含版本号的 WindowsApps 包目录。PowerShell 可用 `& "$env:LOCALAPPDATA\Microsoft\WindowsApps\ARMI.exe" cli admin identity | Out-String` 等管道命令。源码开发使用受管 Python 的 `python -m armi_app …`。

桌面后台启动后检查 GitHub `YifeiLi99/ARMI` Releases，常驻时每 24 小时检查；设置中可关闭自动更新或手动检查。普通 CLI/MCP 调用不额外联网检查。下载后核验可信签名、相同包身份、架构、递增版本和签名覆盖的数据库合同，再由 Windows 登记延后更新；下次系统激活生效。“重启并更新”先完成所属环境停机，停机失败不强制继续。部署状态以 Windows 实际版本为准，不凭下载完成宣称成功。

自动更新只准备数据库合同一致的版本，不迁移或重装数据库。用户直接安装不兼容 MSIX 后，Windows 可能完成程序部署，但 ARMI 会拒绝进入生活并保留数据；业务检查失败不会自动降级。卸载保留数据与凭据，重新安装兼容包后核验并接续原环境，不重复出生。正式签名和 GitHub 发布尚需配置，本地签名测试通过不等于公众安装或在线发布已经通过。

从源码构建需要 PowerShell 7、锁定的 MSVC 与 Windows SDK `10.0.26100.0`。发布身份、版本和更新源集中在 `configs/windows-release.yaml`，Publisher 必须匹配签名证书；证书私钥不进入仓库。最终用户不执行这些命令：

```powershell
.\tools\prepare_windows_build_tools.ps1 -ApprovedOfficialDirect
.\tools\bootstrap_toolchain.ps1 -ApprovedOfficialDirect
.\tools\build_windows_payload.ps1 -OutputDirectory .tmp\windows-payload
.\tools\build_windows_installer.ps1 -PayloadDirectory .tmp\windows-payload -OutputDirectory .tmp\installers -CertificateThumbprint <签名证书指纹>
```

本机验收可为构建命令增加 `-Development`，自动使用独立验收包身份；`tools/test_msix_platform.ps1 -CertificateThumbprint <测试证书指纹>` 执行最小平台验收。自签名测试证书须先在测试电脑建立信任：将公开 `.cer` 导入 `LocalMachine\TrustedPeople` 需要管理员权限，这是一次性的本机信任配置，不是微软审核或每次打包授权。正式构建不接受自签名证书，未配置正式 Publisher 或可用签名私钥时明确失败。

日常开发可直接从当前源码构建并安装本机 MSIX 验收版，全程无需 GitHub Releases：

```powershell
.\tools\install_local_msix.ps1
```

该命令重新构建网页、wheels 和完整 payload，自动选择高于已安装版本与本地构建记录的四段版本，再签名并调用 Windows 安装。它仅使用 `YifeiLi99.ARMI.Acceptance` 身份和独立验收数据；已有环境先检查数据库合同，再通过 Admin 正常停机，停机失败则不请求更新。部署后核对 Windows 实际版本，关闭验收版的 GitHub 自动更新，保持环境停止，随后从开始菜单打开“ARMI 验收”即可测试。构建默认使用已准备的离线依赖缓存；缺少依赖时失败，不自动联网补齐。

默认选择证书库中唯一有效且匹配验收 Publisher 的私钥证书；多个候选时显式传 `-CertificateThumbprint <指纹>`。签名和信任需预先配置，脚本不导入证书。只打包、不安装时增加 `-BuildOnly`；产物位于 `dist/msix-local/<版本>/`，可把 `.msix` 复制到另一台已信任同一测试证书的电脑后双击安装或更新。数据库合同改变时本机更新明确拒绝复用旧数据，生成的包仍保留；不会重装数据库或自动出生。

上述构建默认使用已经准备好的精确 wheel 缓存；缺失时显式失败。原生 PG 制品由 `tools/build_native_postgresql.ps1` 构建，开发与系统测试共用它。正式管理入口核对 wheel package set；可用 `ARMI cli admin identity` 离线取得当前安装摘要。已经完成环境配置和出生后，托盘或显式 Admin 绑定按依赖顺序启动 PostgreSQL、语义召回与 Runtime，并等待核心 readiness：

```powershell
.\start_armi.ps1 -AdminConfig C:\path\to\admin.yaml -OpenBrowser
```

环境由 Admin 配置固定，不通过调用参数切换身份。启动不会安装依赖、安装数据库、执行出生或重建 Web。`-OpenBrowser` 是显式选项；共享或外部数据库不会随整体停止回收。

机器可以通过安装应用服务准备新环境。以下 JSON 的 `operation_id` 必须是调用者保存并在重试中复用的 UUIDv7；安装入口从自身位置寻找全部运行依赖：

```powershell
'{"action":"prepare","operation_id":"<UUIDv7>"}' | & "$env:LOCALAPPDATA\Microsoft\WindowsApps\ARMI.exe" cli setup
```

`ARMI mcp setup` 使用相同请求合同；`status`、`check`、`credential`、`birth`、`login_startup`、`admin` 和 `update` 与窗口共用用例。更新请求形如 `{"action":"update","update":{"action":"status"}}`，内部 action 可为 `status/check/prepare/apply/automatic`，自动更新设置另传 `enabled` 布尔值。配置不返回秘密正文；日常 Admin、Creator 签发和交互绑定相互独立。已有环境的正式维护入口：

```powershell
$env:ARMI_ADMIN_CONFIG = 'C:\path\to\admin.yaml'
ARMI cli admin capabilities
ARMI cli admin maintenance --idempotency-key install-001 --json '{"action":"database_install"}'
ARMI cli admin maintenance --idempotency-key birth-001 --json '{"action":"birth"}'
ARMI cli admin start
ARMI cli admin status
ARMI cli admin stop
```

这些命令会连接或修改目标本地环境，执行前应核对绝对路径和 credential locator。完整环境、QQ、音视频、恢复、维护与重置手册见 [安装、启动与维护](docs/05-运行与验证/01-安装、启动与维护.md)。

交互绑定单独使用 `ARMI_CLIENT_CONFIG`，不包含 Admin 数据库凭据。服务器读取绑定环境的 `interaction-access.yaml` 校验代理、Creator、环境和权限；客户端不能在消息参数中改变身份。

```powershell
$env:ARMI_CLIENT_CONFIG = 'C:\path\to\interaction-client.yaml'
ARMI cli interaction capabilities
ARMI cli interaction message send --scene-key default --message '你好' --idempotency-key message-001 --wait
ARMI cli interaction operation wait --result-ref <返回的引用> --timeout-seconds 20
```

CLI 默认输出 JSON，MCP 使用相同请求合同与应用逻辑。接纳不是完成；等待超时或断线返回继续查询的引用，不重新发送输入。用 `ARMI cli interaction schema` 和 `ARMI cli admin schema` 离线读取当前操作参数。

`ARMI cli interaction artifact read --effect-id <effect-id> --artifact-kind patch --output <文件路径>` 会逐块读取并核验完整摘要，默认不覆盖文件。MCP 的 `artifact_read` 使用 `offset` / `length`，返回下一块位置和同一制品的摘要。

重置、主体内容校正和相关数据删除先取得具体预览及 `authorization_request`，再由独立 Creator 授权绑定签发。相关数据删除使用 `ARMI cli admin data-deletion-preview` 和 `data-deletion-apply`，普通交互请求不能绕过批准：

```powershell
ARMI cli admin --config <Creator授权绑定> authorization approve --request-id <request-id> --expected-request-digest <request-digest> --idempotency-key approval-001
```

普通代理绑定没有签发权限或私钥 locator。执行重置或主体内容校正时提交对应 `authorization_id`；同一凭据不能供另一调用重用。用 `ARMI cli admin invocation get --operation-name <操作名> --idempotency-key <原调用键>` 查询耐久回执；配置修改与包升级不会使旧回执失联。

调用中断后，使用同参数的 `ARMI cli admin invocation reconcile`（MCP：`invocation_reconcile`）核验原结果。核验依据已记录的完成阶段、配置替换文件身份或 owner 幂等记录，不重新执行原操作；证据不足仍返回 `unknown`。配置 `status` 区分已采用、部分消费者采用、需要重启、组件未运行、环境变量覆盖和无法核验；仅保存文件不证明已生效或必须重启。

Creator Web 开发要求先有 ready Runtime：

```powershell
.\tools\start_creator_web_dev.ps1 -EnvironmentRoot 'C:\path\to\environment' -OpenBrowser
```

Vite 固定使用 `127.0.0.1:5173` 并代理现有 Runtime，不启动第二个后端。

本地可复用模型、安装缓存及私有凭据可保存在被 Git 忽略的 `.armi/reusable/`，它不是可运行环境，不继承主体、数据库或管理身份。凭据目录仅允许当前用户访问；复用凭据需要在新环境显式配置，语义模型需要重新安装和校准。Live 验证脚本必须传入 `--environment-root`，不再默认读取仓库旁的旧环境。

保留资源按用途分目录：`models/semantic-recall/` 保存模型，`tools/semantic-recall/cache/` 保存安装包，`secrets/` 下按 `ark`、`codex`、`volc` 分别保存账号凭据，`config/` 保存配置参考；这些路径均相对于 `.armi/reusable/`。目录内的 `README.md` 说明用途与复用方式。

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
- [数据设计](docs/03-数据设计/)：事实分层、全局关系、字段合同、101 张表/1269 字段、约束、索引与 ACL。
- [实现参考](docs/04-实现参考/)：模块、配置、接口、模型/Codex/渠道、设备。
- [运行与验证](docs/05-运行与验证/)：运行手册、质量门禁和实测性能基线。
- [外部研究参考](docs/00-外部研究参考/)：带来源的外部证据，不是 ARMI 事实源。

精确事实优先级：当前代码 → packaged schema/`0000` → 配置与锁文件 → 测试与目标环境证据 → 叙述性文档 → 外部研究。文档中的版本数字是当前快照；发生冲突时以机器合同为准并修正文档。

## 研究与许可

ARMI 会研究开源项目和论文，但只吸收有来源、与当前边界相容的设计证据；外部源码观察不会自动成为 ARMI 合同，也不得复制不兼容代码。

本项目当前未授予开源许可证。
