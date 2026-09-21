# ARMI

> 承载一个自主电子人长期存在的本地运行时。

**ARMI** 是 **Autonomous Runtime for Mind and Identity**，既是产品名，也是心智、身份与生活过程的运行时名称；它不是她的个人名字。

ARMI 不把人格提示词、模型会话或任务 Agent 当成“她”。当前系统只承载一个持续存在的电子人：同一主体跨越对话、活动、渠道、模型、进程与重启继续生活，并在被正式接纳的经历中形成自己的 Self、Mind、记忆、关系、心情和选择。

对外交互优先服务获得 Creator 委托的 Agent，再服务人类直接操作。`ARMI cli interaction` / 统一 MCP 的 `interaction_*` 提供交互使用，`ARMI cli admin` / 统一 MCP 的 `admin_*` 提供管理、检查与调试；Creator Web 保留。代理不是新的社交主体，代理输入沿正式 intake 记录来源，Creator 管理授权不替代 ARMI 的主体意愿。

产品以完整、直接、高效的 Agent/LLM 自动化链路为第一优先级，人类界面为第二优先级。已开启的能力在配置范围内持续可用，不额外设置申请、审核、批准流程；普通回复是基础能力。简化应减少无独立职责的步骤、状态和重复记录，同时保留隐私、数据保护与执行正确性。普通 Creator 文本、语音、QQ 私聊及共用回复链的主动表达已采用直接执行、中断即结束；Codex 委托同样直接执行、中断即结束：通过 `codex.enabled` 开启后重启生效，默认关闭；执行器或凭据不可用会明确失败。保留 Creator／代理提交任务入口，由 ARMI 决定委托并自行理解结果，无逐次审批。普通文本和实时语音可直接选择 Codex 委托，不需要 Creator 先提交专门任务。委托固定使用 `gpt-5.6-luna` / `medium`，不能自行升级模型或思考强度。Codex 第一版采用轻量委托：记录目标与执行选项，SDK 执行后保存最终正文并交回认知；不要求任务 ZIP、文件差异或独立验证报告，清理失败与执行结果分开记录。管理端授权保持独立合同。

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
| 数据库 | PostgreSQL 18.4、pgvector 0.8.6、pg_trgm 1.6；唯一 Alembic `0000`；baseline `armi.schema-baseline.v48`，只维护最新数据库 |
| 物理 schema | 当前 baseline 82 张表；字段以 packaged SQL 为准，表和生产 DML 都受 owner registry 检查 |
| Creator API | 55 个 OpenAPI path；同源 bearer session、签名分页、SSE 投影失效刷新 |
| 管理面 | CLI/MCP 共用 Admin 应用服务；支持绑定的 `active` / `development` / `system_test` / `acceptance`，具体操作受配置授权约束 |
| 工具链 | Python 3.14.6、Node 24.18.0、uv 0.11.33；精确版本以 lock/manifest 为准 |

已实现的正式路径包括 Creator 文本/多场合对话、其他人隔离交流、Experience、Memory、Relationship、Activity、Material、Mood、Sleep、Prompt、Capability、Effect/outbox、精确生命查询、数据导出与数据权利；可选边界包括本地混合语义召回、Codex 委托及互联网研究、QQ/NapCat、实时语音、常驻视觉和 ESP32 私有心情窗。

“仓库存在实现”不等于目标环境已经启用、供应商可用、账号已登录、设备已连接或 live 已验收。

本机文件可以先用 `ARMI cli interaction upload import --file <路径> --idempotency-key <稳定键>` 导入，再用 `ARMI cli interaction message send --scene-key default --attachments '["<upload_id>"]' --idempotency-key <输入键> --wait` 发送，正文可通过 `--message` 同时提供。MCP 对应 `upload_import`、`message_send`、`operation_get/wait`。上传支持分块续传和重复校验，完成上传不会自动触发认知；发送后沿用同一操作引用查询逐附件识别、交流和效果结果。图片、MP3、MP4、PDF、Office 和文本沿用现有 Perception 格式与体积限制，缺少模型凭据时明确返回不可用原因。

## 认知与现实闭环

标准 Creator 文本、实时语音和精确生命查询结果共用主认知与原子提交链：

```text
正式 intake
  → interaction / evidence / opportunity
  → 冻结 purpose-scoped Context
  → cognition.execute：模型生成 → 候选校验 → 制品准备
  → 原子提交校验/应用结果 + 主体变化 + 意图 + Effect/outbox + 工作结算
  → 边界执行与回执核验
```

Qwen/DeepSeek 文本返回仅在 JSON 或候选结构不合格时，使用完全相同的冻结请求最多生成 5 次（含首次），首次合格即停。各次原始返回和费用分别记录，后端业务校验及提交只执行一次；网络 unknown、协议错误和业务拒绝不重试。独立实时语音保持单次调用。 对话处理的任何技术失败均静默结束，不发送错误提示；日志、原始返回和真实失败状态保留。

所有共用认知（包括其他人对话、自主活动、Codex 和睡眠整理）中断即结束本轮，格式重试也不在重启后继续。模型响应成功先单独保存，后续校验或提交失败不改写模型调用结果；`finalizing` 表示正在校验、准备制品并提交。长期活动与维护进度保留，由原调度重新准备新 Context，不读取旧响应或候选续算。

模型候选可表达回复、拒绝、不行动、不改变、延期、需要信息、精确生命查询、Codex 委托或对已启用 camera/screen 的一次视觉观察请求，并可携带有依据的 experience/appraisal/受限 owner changes。模型不能填写主体版本、权限结果、VAD、模型身份、usage 或现实执行结果。慢模型、网络、文件、设备和 Codex I/O 一律在数据库写事务外；回库时重新验证 Runtime fence、work lease、generation 和主体/owner 版本。

## 持续自主生活

自主生活采用两段认知：空闲且人类回复结束后安静满 60 秒，先运行只返回 `{"engage":bool}` 的轻量判断，连续不行动按 1→2→5 分钟退避。只有值得进一步思考时才运行完整自主认知，推进活动、使用工具或选择 1–3 条主动消息；完整认知也可沉默。取消每日额度及模型设置全局下次时间，具体活动仍保留自身等待条件。新输入优先并取消未提交的自主认知，技术失败只记日志，不发聊天错误消息。

`autonomy` 配置只保留 `enabled` 与 `outlet`。CLI/MCP 自主状态、分页历史和 Creator 活动页共用阶段、下次检查、退避档位、最近判断、关联执行及两段 Provider 实测调用量、tokens 和耗时。精确合同和验证边界见 [DESIGN](DESIGN.md#轻量自主判断与完整认知)。

## 仓库结构

```text
apps/
  armi-app/                     统一桌面、CLI 与 MCP 模式入口
  armi-runtime/                 Runtime、交互 CLI/MCP、Creator HTTP、适配器与组合根
  armi-admin/                   独立 Admin CLI/MCP
  armi-creator-web/             React Creator 工作台
modules/                        业务模块
packages/                       8 个稳定底座与边界适配器
devices/esp32-s3-touch-lcd-7c-box/
                                私有心情窗固件
configs/                        Runtime、模型与 Codex MCP 配置
tools/                          工具链、数据库、质量、性能与显式 live gates
tests/                          架构、合同、Runtime、PostgreSQL 与系统测试
docs/                           私有设计和外部研究，Git 忽略
```

Schema 实际打包在 `packages/armi-postgresql-contract/src/armi_postgresql_contract/resources/schema/`。结构变化更新唯一 `0000` 和 baseline identity；只维护最新数据库，不提供旧库升级。已有库合同不匹配时明确拒绝；清空重建须另获针对目标数据的明确授权。

## 日常启动

统一头像使用 `assets/avatar-grid/avatar-32.png` 的固定 32×32 网格，色块坐标与 SVG 同目录保存，采用银白侧马尾、青绿发饰和紫宝石色眼睛。运行 `tools/generate_app_icons.ps1` 保留原稿留白，通过最近邻缩放生成多尺寸 ICO、MSIX 图标和网页头像；整数倍放大精确保留色块，较小尺寸仍会丢失细节。桌面与托盘从随包资源读取，EXE 嵌入同一 ICO，不依赖开发机器路径。

**Windows 安装版使用 MSIX，程序由 Windows 管理，永久数据保存在 `%LOCALAPPDATA%\ARMI`。** 其中 `environments/active/` 保存数据库、配置、凭据、模型和生活数据，`control/` 保存设置、环境登记、管理回执和更新状态，`cache/`、`tmp/` 保存缓存与临时文件。程序目录保持只读；数据目录通过 Known Folder API 定位，使用 MSIX 目录虚拟化排除声明，普通卸载后仍保留。

桌面入口使用上述默认环境，安装版 CLI/MCP 的显式环境也必须位于数据目录的 `environments/` 下。测试包使用独立的 `YifeiLi99.ARMI.Acceptance` 包身份、`ARMI.Acceptance.exe` 别名和 `%LOCALAPPDATA%\ARMI.Acceptance` 数据目录。本次不迁移、修改或删除旧 Inno 安装与数据；源码构建目录和 `.armi/reusable/` 仍是开发资源区域。

Windows 11 x64 安装版包含原生 PostgreSQL、扩展、私有 Python 和已构建网页；用户不需要 Docker、全局 Python/Node、PowerShell 7 或编译器。通过开始菜单或执行别名打开 ARMI。环境准备与出生分开，未显式出生不会进入正常生活；普通启动只检查和启动已有环境。可选能力默认关闭，登录自启使用默认关闭的 Windows StartupTask，并尊重用户在系统中的禁用状态。

`ARMI.exe` 是唯一对外主入口。未配置时进入设置；正常启动成功后打开 Creator Web，重复启动复用同环境实例。托盘与用户级环境宿主独立：CLI/MCP 可以静默启动后台，双击入口接回已有后台并打开托盘。关闭设置窗口只隐藏窗口；“退出托盘”保留后台当前状态；“停止”停止所属环境并保留托盘；“停止并退出”经 Admin 正常停机成功后才关闭托盘。托盘悬停、右键菜单和设置窗口每 5 秒刷新真实 Runtime 状态；图标存在不代表 Runtime 就绪，图标不存在也不代表后台停止。AI 使用同一程序的 `cli interaction/admin/setup` 或统一 `mcp` 模式，MCP 通过同一连接提供 interaction_、admin_、setup_ 工具。`ARMI.exe settings` 直接打开设置。卸载使用 Windows 的应用管理，不交付独立卸载 EXE。长期进程由系统激活的私有环境宿主监督，CLI/MCP 和托盘退出不会误停环境；宿主或包被终止时，所属进程随 Job 结束。

下文 `ARMI` 代表执行别名 `ARMI.exe`。机器接入使用稳定的绝对路径 `%LOCALAPPDATA%\Microsoft\WindowsApps\ARMI.exe` 和参数数组，不绑定含版本号的 WindowsApps 包目录。PowerShell 可用 `& "$env:LOCALAPPDATA\Microsoft\WindowsApps\ARMI.exe" cli admin identity | Out-String` 等管道命令。源码开发使用受管 Python 的 `python -m armi_app …`。

桌面后台启动后检查 GitHub `YifeiLi99/ARMI` Releases，常驻时每 24 小时检查；设置中可关闭自动更新或手动检查。普通 CLI/MCP 调用不额外联网检查。下载后核验可信签名、相同包身份、架构、递增版本和签名覆盖的数据库合同，再由 Windows 登记延后更新；下次系统激活生效。“重启并更新”先完成所属环境停机，停机失败不强制继续。部署状态以 Windows 实际版本为准，不凭下载完成宣称成功。

自动更新只准备数据库合同一致的版本，不迁移或重装数据库。用户直接安装不兼容 MSIX 后，Windows 可能完成程序部署，但 ARMI 会拒绝进入生活并保留数据；业务检查失败不会自动降级。默认卸载保留数据与凭据，重新安装兼容包后核验并接续原环境，不重复出生。正式签名和 GitHub 发布尚需配置，本地签名测试通过不等于公众安装或在线发布已经通过。

**卸载与清理：** 在 ARMI 设置的“卸载”页点击“卸载 ARMI…”。确认窗口中的“同时永久删除全部数据”每次默认不勾选；勾选后会清理当前安装版的数据目录，包括数据库、主体身份、生活记录、配置、凭据和缓存。所有环境先经 Admin 正常停止，停机失败不清理、不卸载。数据清理不可恢复，清理与 Windows 包卸载不是原子操作，失败时可能已清理部分或全部数据。直接从 Windows 设置卸载仍始终保留数据。

机器使用同一 `cli setup` / MCP `setup_*` 用例：`{"action":"uninstall"}` 默认保留；只有 `{"action":"uninstall","delete_data":true}` 才清理。`uninstall_requested` 表示已交给原生入口处理，最终包状态以 Windows 为准；卸载会关闭此安装版的桌面与 CLI/MCP 进程。此操作不触及其他包身份或旧 Inno 数据，不影响普通安装更新的保留行为。

从源码构建需要 PowerShell 7、锁定的 MSVC 与 Windows SDK `10.0.26100.0`。发布身份、版本和更新源集中在 `configs/windows-release.yaml`，Publisher 必须匹配签名证书；证书私钥不进入仓库。最终用户不执行这些命令：

```powershell
.\tools\prepare_windows_build_tools.ps1 -ApprovedOfficialDirect
.\tools\bootstrap_toolchain.ps1 -ApprovedOfficialDirect
.\tools\build_windows_payload.ps1 -OutputDirectory .tmp\windows-payload
.\tools\build_windows_installer.ps1 -PayloadDirectory .tmp\windows-payload -OutputDirectory .tmp\installers -CertificateThumbprint <签名证书指纹>
```

本机验收可为构建命令增加 `-Development`，自动使用独立验收包身份；`tools/test_msix_platform.ps1 -CertificateThumbprint <测试证书指纹>` 执行最小平台验收。自签名测试证书须先在测试电脑建立信任：将公开 `.cer` 导入 `LocalMachine\TrustedPeople` 需要管理员权限，这是一次性的本机信任配置，不是微软审核或每次打包授权。正式构建不接受自签名证书，未配置正式 Publisher 或可用签名私钥时明确失败。

当前开发阶段暂不使用 GitHub Releases。要求“更新本机”时，默认从当前源码构建并安装或原位升级本机 MSIX 验收版，不以先卸载再重装代替升级，不重建已有数据库：

```powershell
.\tools\install_local_msix.ps1
```

该命令重新构建网页、wheels 和完整 payload，自动选择高于已安装版本与本地构建记录的四段版本，再签名并调用 Windows 安装。它仅使用 `YifeiLi99.ARMI.Acceptance` 身份和独立验收数据，软件显示名统一为 `ARMI`；已有环境先检查数据库合同，再通过 Admin 正常停机，停机失败则不请求更新。部署后核对 Windows 实际版本，关闭验收版的 GitHub 自动更新，保持环境停止，随后从开始菜单打开“ARMI”即可测试。构建默认使用已准备的离线依赖缓存；缺少依赖时失败，不自动联网补齐。

默认选择证书库中唯一有效且匹配验收 Publisher 的私钥证书；多个候选时显式传 `-CertificateThumbprint <指纹>`。签名和信任需预先配置，脚本不导入证书。只打包、不安装时增加 `-BuildOnly`；产物位于 `dist/msix-local/<版本>/`，可把 `.msix` 复制到另一台已信任同一测试证书的电脑后双击安装或更新。数据库合同相同才允许原位更新；合同不同时在部署前拒绝，不自动清库或重复出生。若决定丢弃旧数据，须另行明确授权清空并重建目标数据库。源码变更不会自动更新安装版。

版本格式为 `年.月.日.当日序号`，例如 `2026.9.15.1`，日期取构建电脑的本地日期。同日序号高于发布配置、已安装版本及本地构建记录，换日从 1 开始。日期早于已知最高版本或同日序号达到 65535 时明确失败；旧 `0.1.0.x` 可直接升级到日期版本。本地生成的 release tag 同步为 `v<完整版本>`，不上传 GitHub。发布配置中的 `.0` 是未发布基准，正式发布需填写实际日期及序号并同步 tag。

`dist/msix-local/` 只保留最新成功签名的一版产物；新包生成成功后自动删除旧版本，`-BuildOnly` 同样执行。构建失败删除未完成产物并保留上一成功版本；安装失败仍保留本次已签名的包。退出时清理完整 payload 和 staging，构建日志固定在 `.tmp/local-msix-build/`，下次构建替换，不按次累积。

上述构建默认使用已经准备好的精确 wheel 缓存；缺失时显式失败。原生 PG 制品由 `tools/build_native_postgresql.ps1` 构建，开发与系统测试共用它。正式管理入口核对 wheel package set；可用 `ARMI cli admin identity` 离线取得当前安装摘要。已经完成环境配置和出生后，托盘或显式 Admin 绑定按依赖顺序启动 PostgreSQL、语义召回与 Runtime，并等待核心 readiness：

```powershell
.\start_armi.ps1 -AdminConfig C:\path\to\admin.yaml -OpenBrowser
```

环境由 Admin 配置固定，不通过调用参数切换身份。启动不会安装依赖、安装数据库、执行出生或重建 Web。`-OpenBrowser` 是显式选项；共享或外部数据库不会随整体停止回收。

机器可以通过安装应用服务准备新环境。以下 JSON 的 `operation_id` 必须是调用者保存并在重试中复用的 UUIDv7；安装入口从自身位置寻找全部运行依赖：

```powershell
'{"action":"prepare","operation_id":"<UUIDv7>"}' | & "$env:LOCALAPPDATA\Microsoft\WindowsApps\ARMI.exe" cli setup
```

统一 MCP 的 `setup_*` 与 CLI、窗口共用应用用例；调用 MCP 时省略外层 `action`，例如 `setup_update` 的参数为 `{"update":{"action":"status"}}`。管理操作直接使用 `admin_*` 工具，不提供 `setup_admin` 转发。更新内部 action 可为 `status/check/prepare/apply/automatic`，自动更新设置另传 `enabled`。配置不返回秘密正文；显式受限绑定按各自授权范围执行。已有环境的正式维护入口：

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

开发代理操作 ARMI 默认使用正式 CLI/MCP，包括查询、配置、启停、诊断和结果核验；构建及安装更新使用项目脚本和 Windows 包管理接口。只有用户针对当前操作明确要求 Computer Use（电脑操控）时才使用桌面或浏览器界面操控；“打开”“看看”“检查”及修改界面本身不构成该要求。打开窗口可调用正式入口，机器接口缺失时说明缺口，不自行切换界面操作。视觉验收遵守同一边界，未做的视觉检查如实说明。

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

账号凭据在环境准备完成后，通过“设置 → 账号凭据”填写并保存。千问文本模型使用 `model.qwen_api_key`，DeepSeek 文本模型使用 `model.deepseek_api_key`；方舟 Key 仅用于独立豆包语音认知、视觉识别。豆包语音识别/合成使用新版语音控制台 Key；Codex 导入登录文件；QQ 通信凭据自动生成。已有 locator 的 Key 更换在后续请求生效，当前任务不切换；旧环境首次添加千问或 DeepSeek locator 后需要重启 Runtime。安装版凭据文件位于所属环境的 `secrets/provider-<凭据名称>`，依靠文件权限保护，不回显已保存内容。普通升级和默认卸载保留这些文件。保存只证明本地文件已更新，不代表服务商认证、模型或真实对话已通过。

主文本模型在“功能与模型”页选择 `qwen` 或 `deepseek`，填写型号并点击“保存文本模型”，随后重启 Runtime。主链路不再接受方舟，也不在失败时自动回退。当前支持千问 `qwen3.8-flash`（默认）、`qwen3.8-max`、`qwen3.7-flash`、`qwen3.7-plus`、`qwen3.7-max`，以及 DeepSeek `deepseek-flash`、`deepseek-v4-pro`；两家统一使用官方 Responses 接口并关闭思考。Qwen 通过提示词提供完整 Schema 和格式要求，DeepSeek 另启用 JSON Object 模式；后端始终使用同一套严格候选校验。新增型号必须先确认其 Responses 与非思考能力，不能仅换名字猜测兼容。

机器沿用 Admin `configuration` 的 `model-bindings` target，读取当前版本后以同一个 apply 补丁更新 `active_binding` 和唯一 `bindings` 项（保留所有 purpose、预算和独立 voice binding）。千问 adapter 为 `armi.model-adapter.qwen-responses-v1`，北京地址 `https://dashscope.aliyuncs.com/compatible-mode/v1`；也允许官方北京 Workspace 域名。DeepSeek adapter 为 `armi.model-adapter.deepseek-responses-v1`，地址 `https://api.deepseek.com`。各自使用 `armi.model.qwen-api-key.v1` / `armi.model.deepseek-api-key.v1` 的 credential identity、上述 locator 和 `model.request.qwen` / `model.request.deepseek` purpose。设置页保存模型也调用同一用例。协议和官方来源见 [模型设计](DESIGN.md)；缺少价格继续按现有规则显示待计价，不继承方舟单价。

语音凭据名称保持 `speech.volc_credentials`，CLI/MCP setup 的 `credential.put.value` 直接接收 API Key 文本，不再接收 App ID/Access Token JSON。流式 ASR、双向 TTS 和录音识别共用该语音 Key，通过 `X-Api-Key` 鉴权；资源 ID 和音色仍由配置指定。请在[豆包语音新版控制台](https://console.volcengine.com/speech/new/setting/apikeys?projectName=default)创建 Key 并开通所需服务，不自动复用方舟模型 Key。已有旧格式文件须重新录入语音 Key，不会自动转换或删除。依据：[流式识别](https://docs.volcengine.com/docs/6561/1354869)、[双向合成](https://docs.volcengine.com/docs/6561/1329505)、[录音识别](https://docs.volcengine.com/docs/6561/1354868)官方鉴权说明（2026-09-11 核对）。

QQ 默认关闭，也不随 MSIX 预装 NapCat。在“设置 → QQ 接入”只填写你的 Creator QQ 号，ARMI 的号码在扫码登录后自动读取，点击“一键安装并启用 QQ”，自动下载固定版本的官方 Windows Node 组件、校验摘要、配置本机端口和两份独立通信密钥、启动环境并打开登录页。扫码及 QQ 安全验证仍由账号本人完成；默认只允许回复 Creator 私聊，群聊保持关闭。组件在所属环境的 `tools/napcat/`，正常停机回收受管 Node 进程，更新和默认卸载保留配置及数据。

机器使用同一 `ARMI.exe cli setup` / MCP `setup_*` 用例：请求 `{"action":"napcat","napcat":{"action":"prepare","creator_user_id":98765,"enabled":true}}`，Creator 号码需替换为实际值；需要打开浏览器时增加 `open_login:true`。不传号码、不开启时仅安装组件；`{"action":"napcat","napcat":{"action":"status"}}` 读取安装准备进度，实时渠道状态使用 Admin `maintenance.napcat_status`。NapCat 下载来自其上游 Releases，与 ARMI 自身是否使用 GitHub 更新无关；使用须遵守上游 [许可证](https://github.com/NapNeko/NapCatQQ/blob/v4.18.9/LICENSE)。

QQ 准备返回 `awaiting_login` 后，设置窗口自动检测登录并完成配置，无需再按确认按钮。CLI/MCP 调用方每隔至少 10 秒提交 `{"action":"napcat","napcat":{"action":"complete"}}`，服务从本机认证接口取得在线账号后完成绑定并返回 `account_id`；未登录继续返回等待状态。`status` 保持只读，不触发绑定。重复完成不会重复配置；自动配置中断后不会盲目重放管理操作。

QQ 已登录但 NapCat API 端口被 Windows 禁止绑定时，可调用 `{"action":"napcat","napcat":{"action":"repair"}}`：验证在线账号和绑定一致、旧端口确实返回 Windows 10013 后，正常停止环境、分配可绑定端口、同步 ARMI 与 OneBot 配置并启动核验。保留账号、登录资料、通信密钥及事件端口，不重新安装或扫码；端口占用、未登录和其他故障不套用此修复。

QQ 页面分别显示组件安装、账号登录和连接状态；进度条仅用于下载与安装。`refresh` 用例读取当前登录和渠道健康，`open_login` 打开已有登录页并启动必要环境，不重新安装或重做绑定。首次配置后的重启可能需要 QQ 再次扫码验证，此时显示 `login_required`；再次登录后仅核验连接，不循环重启。已保存的安装进度不代表当前在线，`ready` 也不等于真实消息收发已验证。

模型和语音凭据提供“保存并验证”及“验证已保存的 Key”：setup `credential.action` 分别使用 `put_and_verify`（带 `value`）与 `verify`（不带值）。验证产生少量服务商用量，只发送固定测试内容。两家文本 Key 可独立验证：已选供应商检查所选型号，另一家使用默认测试型号（千问 `qwen3.8-flash`、DeepSeek `deepseek-flash`），不修改聊天配置，也不拿该 Key 尝试另一家。两家均用 Responses，并复用正式文本适配器的生成设置与后端严格 Schema 校验。方舟 Key 单独验证语音认知模型；语音服务 Key 验证 TTS 生成与 ASR 识别。全部检查成功才返回 `verification.status=passed`，`status=configured` 只代表已保存。本地请求校验失败与服务商鉴权、响应错误分别说明。状态读取不联网。此验证不覆盖主体认知、录音文件识别或设备采集，不发送生活数据。

## 统一 MCP 与数据库管理

安装版只配置 `ARMI.exe mcp`；示例见 [Codex MCP 配置](configs/codex/armi-mcp.toml)。源码使用 `python -m armi_app mcp --environment-root <绝对环境目录> --installation-root <完整 payload 目录>`。环境未准备时仍可发现工具、查询设置和准备环境；结束 MCP 不停止环境。

本地拥有者经私有目录 ACL、环境身份及本机绑定验证后获得完整 ARMI 管理范围，无需 Windows 提权或逐次应用内审批。受限连接使用 `--config <绝对路径>`，绑定文件为严格 YAML，格式如下；至少指定一个配置，路径必须绝对，不接受管理员声明：

```yaml
schema_version: armi.mcp-binding.v1
admin_config: C:/path/to/restricted-admin.yaml
interaction_config: C:/path/to/client.yaml
```

- `admin_database_catalog` 列出表、视图、字段、主键、关系和读写限制。
- `admin_cognition_read` 按 `episode_id` 列出该轮认知的 Context、模型请求、原始响应和诊断制品；再传入目录中的 `artifact_id`、`offset`、`length` 分段读取正文。CLI 为 `cli admin cognition-read`。先用 `admin_trace_flow` 从消息/操作定位 episode；分页按 Unicode 字符计，沿 `next_offset` 读取。新请求包含实际系统指令、输入和输出 Schema，旧请求只展示历史留存内容，不重新调用模型。
- `admin_database_query` 接受 `table`、`fields`、`filters`、`order`、`limit`、`offset`。数值、数组、二进制和时间以 PostgreSQL 文本无损返回；JSON 使用 `{"postgresql_json":"<精确 JSON 文本>"}` 保留数字精度，也接受普通 JSON 输入。
- `admin_database_batch` 接受 `idempotency_key`、`reason` 和 `changes`。每项选择 `insert/update/delete`；更新和删除必须给出完整 `key` 及查询返回的 `expected_version`。所有项同事务提交，失败全部回滚。执行前正常停止业务进程，保留 PostgreSQL 并持有环境控制锁；完成后保持停止。
- 身份、权限、审计、管理回执及其他受保护记录不能通过表管理修改。事务内的 `admin_data_changes` 回执不伪装成认知；中断后通过 `admin_invocation_reconcile` 核对，不盲目重放。

只提供当前数据库的空库安装与校验，不提供数据库升级 CLI/MCP。程序更新不自动删除数据；旧库不兼容时停止并报告。

日常内容使用 `admin_content_write`：指定 `change.owner`（`memory/relationship/material/subject_state/mood/prompt/activity`）、`action`、`object_id`、`expected_version`、内容及 `expected_generation_id`。从 `admin_database_catalog` 的 `online_management` 和 `admin_database_query` 读取对象及当前版本；对象版本与表维护返回的行版本标记不是同一字段。新增实体版本为 0；主体组件和心情只允许修改，`object_id` 使用主体 ID；人格锚点不可修改。活动可调整为 ready 或 paused，不能伪造已完成的现实效果。

在线写入由各 owner 校验并追加管理员版本，删除遵循逻辑删除/遗忘语义，返回历史保留和实际清理范围。资料和提示正文使用正式 Artifact 发布协议；写入和耐久回执同事务提交。遇到认知、效果、数据治理或共享锁占用时返回忙碌/冲突，不停机、不取消回复、不覆盖旧候选；调用方应重新读取版本后作出新操作。修复内部表仍使用明确的停机维护接口。

## 测试与质量检查

日常“全量测试”使用一个源码入口，包含全仓 Python、隔离原生 PostgreSQL 和前端 Vitest（jsdom），不包含 Playwright、真实浏览器、构建安装或真实外部调用：

```powershell
./tools/test.ps1 -All
./tools/test.ps1 -Group cognition,expression -Database
./tools/test.ps1 -Group web
./tools/test.ps1 -List
./tools/test.ps1 -All -Jobs 14 -DatabaseJobs 4
```

`-Group` 默认运行相关代码测试，加 `-Database` 才包含该组数据库场景；`-All` 自动包括数据库。目录决定基本归组，文件名中的完整模块名补充相关组，跨模块场景在测试上声明 `pytest.mark.test_group("cognition", "expression")`。组可以重叠，执行自动去重；新增用例无须登记进全量名单。分组不自动推断所有调用方，公共合同变化应同时选择受影响消费者或运行全量。

Python 与数据库使用 pytest-xdist 持续领取用例，前端使用受限 Vitest worker。默认总预算最多 14 个测试 worker，典型分配为代码 8、数据库 4、前端 2；小预算按可用槽位分批启动。每个数据库 worker 使用独立的临时 PostgreSQL，整轮复用、结束后停止清理，不触及安装版环境。`.tmp/test-runs/<运行标识>/` 保留收集清单、日志、JUnit/Vitest 结果及慢用例信息。数据库未启动、收集错误或测试失败均返回非零。

真实浏览器、安装和外部服务用例分别使用 `creator_system`/`browser`、`installation`、`live` 标记，源码入口明确排除；不要用 `skip` 把必需的数据库测试伪装为通过。下列质量入口保留用于格式、类型、发布与系统验收，和日常全量测试分开：

收集结果的 `out_of_scope` 列出排除用例和原因，目前仅有 Creator 浏览器旅程。Admin CLI 的数据库安装、查询与作用域测试直接运行当前源码，包含在数据库全量中。启停、恢复、上传、权限和容量分别由对应行为测试覆盖；CLI/MCP 共用用例与传输映射分别验证。认知中断矩阵按 purpose 与 stage 参数化，各场景独立调度，保留相同的数据库断言。

源码修改后先按影响运行自动化测试，不必先安装 MSIX；数据库与系统测试创建隔离环境。安装更新、卸载、包身份、执行别名、自启和托盘等安装版行为再用真实签名包验收。当前不另外维护常驻开发主体，源码测试环境与本机安装的验收版分开；验收版已有身份、生活数据和凭据必须保留，不能当作可随手重置的临时数据。只有要求更新本机或验证安装版效果时，才进入本地打包安装流程。

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
- [数据设计](docs/03-数据设计/)：事实分层、全局关系、字段合同、约束、索引与 ACL。
- [实现参考](docs/04-实现参考/)：模块、配置、接口、模型/Codex/渠道、设备。
- [运行与验证](docs/05-运行与验证/)：运行手册、质量门禁和实测性能基线。
- [外部研究参考](docs/00-外部研究参考/)：带来源的外部证据，不是 ARMI 事实源。

精确事实优先级：当前代码 → packaged schema/`0000` → 配置与锁文件 → 测试与目标环境证据 → 叙述性文档 → 外部研究。文档中的版本数字是当前快照；发生冲突时以机器合同为准并修正文档。

## 研究与许可

ARMI 会研究开源项目和论文，但只吸收有来源、与当前边界相容的设计证据；外部源码观察不会自动成为 ARMI 合同，也不得复制不兼容代码。

本项目当前未授予开源许可证。
