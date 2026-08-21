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

ARMI 目前是运行在单机上的模块化单体。Python workspace 包含稳定内核、Runtime/Admin 共用的 PostgreSQL catalog 合同、普通 Runtime、隔离的管理 MCP，以及独立 QQ 适配器和 NapCat 渠道驱动；Creator 工作台是由 Runtime 同源托管的 React 静态应用。PostgreSQL 是唯一权威关系数据库，文件制品只保存不适合直接进入关系表的大正文或执行产物。

二十三个业务领域均为独立 workspace distribution，其中 `armi-live-voice` 独占本机实时语音会话、轮次与 Provider attempt，`armi-live-vision` 独占常驻 USB 摄像头会话、选帧和观察记录。生产与跨模块测试只通过各模块 `api.py` 的冻结 DTO/Protocol 协作；业务 SQL 由表 owner 独占，Runtime 只在共享 PostgreSQL UoW 中协调顺序、CAS、durable work 与审计。Kernel 和 Runtime Foundation 保持业务中性，不维护业务 owner、表名或 Creator 投影版本枚举。

当前代码已经覆盖 Creator 对话与多场合、Self/Mind/Prompt、主观记忆、关系与生活资料、自主机会与 Activity、睡眠维护、主动联系、内置其他人交流、本地导出与数据权利，以及经授权的 Creator→Codex 委托。QQ/NapCat 统一适配器支持好友私聊和白名单群的文字收发，并保留 QQ 已明确给出的内置表情、商城表情与图片子类。内置表情和有效商城摘要在本地解释；其他图片经过真实格式、尺寸和动画帧检查后，按表情、平台特殊图或普通图片选择一次视觉理解。常驻视觉是另一条链路：Runtime 只绑定配置中的同一 USB 摄像头，在内存保留最新帧，并把初始、稳定场景变化、周期或人工触发的选帧交给感知模块；它不绑定 interaction、party 或社交 scene，也不能直接触发回复或现实动作。选中的私有帧最多保留 24 小时，连续原始画面不落盘。QQ 录音走豆包语音大模型录音文件识别标准版的 `400` 模型，它不是实时语音。独立的本机实时语音模块使用 USB Audio、流式 ASR、紧凑快模型和流式 TTS，默认关闭，只有精确配置设备并显式开始后才接纳 `live_voice` Creator 输入；浏览器不取得麦克风权限。视频仍作为完整文件交给方舟视频模型，PDF、文本及常见 Office 文件沿用各自通路。正式 QQ 回复仍只发送文字。代码存在不等于环境已经配置、设备已经连接或服务权限已经通过真实握手。

Creator 输入及其精确生命查询结果使用两条热分支：Runtime 只冻结并编译一次 Context，再分别生成“响应与动作”和“经历与评估”Prompt，两次模型调用并发执行且互相看不到输出。响应分支只决定表达、查询和明确动作；评估分支只提交 Experience、事件级情绪信号、关系或承诺事件，且只有 Creator 明确要求“记住”时才能追加即时记忆。Runtime 按固定顺序汇合两个结果，由各状态 Owner 校验后只执行一次 Subject Commit；单支失败不伪造另一支的结果。接受 Experience 后只登记维护积压，记忆整理与 Self、Mind、Prompt 专项反思在空闲或睡眠窗口按依赖顺序运行。

项目仍是个人研究与高迭代实验系统，不是生产发布版本。安全、部署、迁移、公开渠道、多模态和新的外部执行器不会从历史路线图自动进入范围，而由创造者逐项决定。

## 仓库结构

```text
packages/armi-kernel/       领域、应用端口与稳定公共契约
packages/armi-artifact-store/ Runtime/Admin 共用的内容寻址制品存储
packages/armi-postgresql-contract/ Runtime/Admin 恢复与观测共用的 catalog 证据
packages/armi-channel-napcat/ 独立 NapCat/OneBot 渠道驱动
packages/armi-adapter-qq/    QQ 与内核统一外部消息端口的独立适配器
apps/armi-runtime/          权威 Runtime、适配器、接口与组合根
apps/armi-admin/            与日常 Runtime 隔离的管理 MCP
apps/armi-creator-web/      Creator 本机工作台
modules/                    独立业务 distribution 及其模块行为与契约测试
tests/                      跨模块、Runtime、架构、集成与旅程测试
tools/                      本地数据库、工具链和质量入口
docs/                       私有叙述性设计与外部研究资料
```

`docs/` 被 Git 忽略，用于本地继续设计；精确的字段、路由、状态值和依赖版本仍以当前代码、DDL、配置与锁文件为准。文档入口见 [`docs/README.md`](docs/README.md)。

数据库只保留唯一 Alembic `0000` 基线，并以 `armi.schema-baseline.v1` 标识当前数据库身份。Runtime 与 Admin 的固定仓储写入按“角色—表—INSERT/UPDATE/DELETE”授权，不使用逐字段写权限；`db status` 与日常启动入口会同时核对 revision、基线身份和完整权限合同，身份漂移以 `DB-SCHEMA-CONTRACT` 拒绝，权限漂移以 `DB-ROLE-GRANT` 拒绝。

## 本地开发入口

环境已经完成数据库安装和出生初始化后，可从仓库根目录一键拉起 PostgreSQL 与 Runtime：

```powershell
.\start_armi.ps1
```

需要启动后直接打开 Creator 工作台时使用：

```powershell
.\start_armi.ps1 -OpenBrowser
```

默认环境根是源码仓库同级的 `ARMI-Environment`。也可以通过 `-EnvironmentRoot` 或 `ARMI_ENVIRONMENT_ROOT` 显式覆盖。脚本会同步锁定依赖，把 Creator Web 构建到被 Git 忽略的 `apps/armi-runtime/build/`，检查环境、启动并等待 PostgreSQL、检查数据库、启动 Runtime，并以业务 readiness 为最终成功条件。环境启用 QQ 时，它会在 Runtime 事件入口就绪后幂等确保 `<environment-root>/tools/napcat` 中的 NapCat 启动；等待扫码或渠道异常会作为独立 `qq_state` 警告，不会伪装可用，也不会阻断 Creator。脚本不会暗中执行数据库安装或出生初始化。

修改 Creator 前端时，先用上述脚本启动 Runtime，再在另一个 PowerShell 终端运行 Vite 开发服务器：

```powershell
.\tools\start_creator_web_dev.ps1 -OpenBrowser
```

开发页面位于 `http://127.0.0.1:5173/ui/`，Vite 只在开发期代理 `/v1`；日常 Runtime 仍在自己的 `/ui/` 同源提供构建页面。生成的 JS/CSS 不进入 Git，发布 wheel 则会在构建时携带同一套静态资源，安装后不需要 Node。

开发数据库固定使用 Docker 中的 PostgreSQL 18.4 + pgvector 0.8.6：

```powershell
.\tools\manage_postgresql.ps1 Start
.\tools\manage_postgresql.ps1 Status
```

准备好环境根的 `environment.yaml`、secret locator 与出生资料后，通过正式 CLI 建立和运行环境。仓库内人工维护的默认配置集中在 `configs/`；JSON 只继续承载 OpenAPI、Schema、锁文件和 wire 等机器合同：

```powershell
uv sync --frozen
uv run armi config check --environment-root C:\path\to\environment
uv run armi db install --environment-root C:\path\to\environment
uv run armi bootstrap birth --environment-root C:\path\to\environment
uv run armi semantic-recall install --approved-official-direct --environment-root C:\path\to\environment
uv run armi semantic-recall calibrate --environment-root C:\path\to\environment
uv run armi semantic-recall status --environment-root C:\path\to\environment
uv run armi start --environment-root C:\path\to\environment
uv run armi status --environment-root C:\path\to\environment
uv run armi channel qq status --environment-root C:\path\to\environment
uv run armi channel qq start --environment-root C:\path\to\environment
uv run armi channel qq open --environment-root C:\path\to\environment
uv run armi channel qq open --auto-login --environment-root C:\path\to\environment
uv run armi voice devices --environment-root C:\path\to\environment
uv run armi voice status --environment-root C:\path\to\environment
uv run armi voice start --environment-root C:\path\to\environment
uv run armi voice stop --environment-root C:\path\to\environment
uv run armi creator send --environment-root C:\path\to\environment --message "你好"
uv run armi other-human party register --environment-root C:\path\to\environment --party-key friend-1 --display-label "朋友"
uv run armi other-human scene set --environment-root C:\path\to\environment --party-key friend-1 --scene-key default --status open
uv run armi other-human send --environment-root C:\path\to\environment --party-key friend-1 --message "你好" --idempotency-key friend-message-1
uv run armi other-human data-rights list --environment-root C:\path\to\environment --party-key friend-1
uv run armi stop --environment-root C:\path\to\environment
```

语义召回默认关闭。显式安装命令只从固定的 Qwen 与 llama.cpp 官方地址下载一次并校验固定摘要；`semantic-recall calibrate` 在 Runtime 停止时使用已有制品验证本机 28 层全 GPU 配置，不联网，也不降级到部分 GPU 或 CPU。校准使用不同长度的真实查询并保存延迟、显存和 RSS 结果；旧配置、硬件变化或门槛失败都会明确要求重新校准。启用后的运行期只访问随机回环端口，不会联网换版本或回退云 embedding。数据库以 halfvec HNSW 和 `siglen=256` 的 GiST trigram 分别生成有界候选；有向量时两路使用独立只读连接并行执行，再经原向量、真实词相似度和 owner 当前态精排后做 RRF，向量和关键词仍只是可重建投影。`armi semantic-recall status` 同时显示投影块数、覆盖状态、检索 profile 和两个索引是否就绪。`armi start` 会先尝试启动、预热并检查本地 embedding 服务；模型缺失、校准失效或 GPU 启动失败时只把语义召回标为 `unavailable`，Runtime 主链路继续运行并使用关键词召回，不会转到 CPU。`armi stop` 在权威 Runtime 退出后回收该服务和显存。它仍不终止交互式 QQ/NapCat，渠道掉线也不会持续自动重启。重新运行 `armi start` 或 `armi channel qq start` 会先检查健康状态，健康实例不会被重复拉起。`armi channel qq open` 从当前 NapCat 安装读取 WebUI 地址，把 WebUI 登录凭据复制到 Windows 剪贴板并打开默认浏览器；命令输出和 URL 都不包含凭据。显式增加 `--auto-login` 会把 token 作为浏览器 URL 查询参数交给 NapCat 自动登录，不再复制剪贴板；命令输出仍保持脱敏，但 token 可能进入浏览器、进程、引用来源或本机访问日志，调用该选项即表示操作者接受这项风险。Creator“运行与维护”页统一显示 PostgreSQL、核心 Runtime、Creator 前端、QQ、实时语音与常驻视觉的分项健康；前三项固定开启，可选组件使用运行期滑动开关。QQ 关闭只暂停 ARMI 的事件接纳，不终止交互式 QQ/NapCat；页面仍只提供无密钥管理地址，不获得宿主进程控制权。

自动化 Creator 对话不需要驱动浏览器。运行中的环境可通过 `armi creator send` 把输入送入与工作台相同的正式 Creator intake；重复调用需要自行传入稳定的 `--idempotency-key`。消息也可通过 `--message-file <path>` 读取，或用 `--message-file -` 从标准输入读取。Codex 管理会话可使用 Admin MCP 的 `inject_creator_input`，两条入口最终进入同一 Runtime intake，不直接写数据库。

caller-declared 的本地其他人入口通过 `armi other-human` 调用运行中 Runtime 的私有本机控制面，不进入 Creator 公共 OpenAPI，也不直写数据库。命令覆盖 party 注册、scene 开关、带稳定幂等键的消息接纳，以及 `data-rights request/list/get`；该入口只声明调用方提供的本地身份，不能证明现实平台身份或真实送达。

日常及安装后的 Creator 工作台只在 Runtime 的本机地址上提供。页面打开后会自动建立进程内连接并直接进入工作台，不需要登录、bootstrap code 或手动注销。Vite 地址仅用于源码前端开发。

数据库结构只由唯一 Alembic `0000` 管理。`db install` 拒绝已有用户对象，并在一个事务中安装有序模块化基线、revision 与 `armi.schema-baseline.v1` 身份。ARMI 是本地单实例项目，不提供内部数据库迁移或历史兼容入口；基线变化时必须停止 Runtime、明确删除旧数据库并重新安装。Runtime 只接受与当前源码完全一致的 revision、基线身份和角色权限合同。

已获明确授权的本地彻底重置在停止 Runtime 后使用 `tools/reset_local_environment_data.ps1 -EnvironmentRoot C:\path\to\environment -Apply` 清空并重建 artifacts、backups、Codex runner、exports、logs 与 run 目录。脚本不删除数据库卷，也不触碰环境配置、凭据、模型、工具、NapCat 或渠道配置；数据库卷仍须独立核对后删除。

离线全量灾备与隔离恢复演练使用 `armi recovery create`、`armi recovery verify` 和 `armi recovery drill --apply`。备份保存 custom-format 数据库 dump、全部 retained+verified artifact、schema head 与 Runtime 权威身份；恢复到隔离数据库后通过正式 owner recovery roster 检查业务一致性。它与 Creator JSONL 数据导出是不同协议。

日常开发从改动相关的最小检查开始。仓库提供三层确定性门禁：

```powershell
# Fast：锁文件、格式、lint、严格类型、非 PostgreSQL 测试、架构、安全和前端检查
.\tools\quality.ps1

# Release：Fast + Creator/Python 构建 + 32 个 wheel 的隔离安装与 CLI smoke
.\tools\quality.ps1 -Release

# System：Release + 隔离 PostgreSQL + 固定 Chromium + 真实 Creator 全链路
.\tools\quality.ps1 -System

# 显式并发预算；1 表示完全串行，适合复现并发相关问题
.\tools\quality.ps1 -System -Jobs 1
```

门禁默认按逻辑处理器数自动选择并发预算，最多同时调度 8 项；Python 测试最多使用 8 个 worker，PostgreSQL 测试最多使用 4 个相互隔离的临时容器。可以用 `-Jobs 1..32` 覆盖预算，其中 `-Jobs 1` 同时关闭 pytest 多进程和门禁并行。构建、wheel 安装、浏览器合同和 Creator 系统旅程仍按真实产物依赖顺序执行，失败的前置门禁只跳过其下游，不阻止无关检查完成。

`System` 只使用随机回环端口、临时数据库、临时环境根、构建 wheel 和固定本机 Chromium，结束后清理 Runtime、浏览器与 PostgreSQL 容器。真实模型、网页搜索、语音、摄像头、QQ 真机和付费 Provider 仍属于独立 live gate；未运行时不能计入 `System` 通过，也不能把 `blocked` 写成测试失败或测试通过。`-Gate WHEEL-INSTALL`、`PG-INTEGRATION`、`BROWSER-CONTRACT`、`CREATOR-SYSTEM` 可用于定向定位，且不能与 `-Release` 或 `-System` 混用。

## 研究与许可

项目会研究开源项目和论文，吸收适合 ARMI 的设计，再按自身边界重新实现。来源与许可证记录保存在私有研究目录中；研究对象的自述和做法不会自动成为 ARMI 的设计事实。

本项目暂未授予开源许可证。
