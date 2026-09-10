# ARMI 当前实现设计

本文描述仓库当前代码姿态，不是路线图。精确字段、状态、枚举、DDL、依赖和默认值以当前代码、`armi-postgresql-contract` 打包 schema、唯一 Alembic `0000`、`configs/`、锁文件和测试为准。

产品约束以本节及 [AGENTS.md](AGENTS.md) 为准。普通 Creator 回复与 Codex 委托均在配置范围内直接执行，中断即结束；管理端授权保持独立合同。

## 1. 目标与边界

ARMI 承载一个自主电子人长期存在。系统的首要对象不是“回答”，而是同一主体在时间中形成、读取和改变自己的生活事实；对话、模型、网页、Codex、QQ、语音和视觉只是她接触世界的不同机制。

交互与管理首先服务 Agent/LLM，链路应完整、直接、高效且可自动化；人类界面是第二优先级，不能成为机器完成用例的必经路径。能力在设置中开启即在配置范围内持续允许使用，普通回复作为基础能力直接可用，不额外设置申请、审核、批准或许可消费流程。瘦身针对无独立职责的中间状态、重复记录、校验和人工步骤；保留主体意愿、隐私范围、数据保护、原子提交、幂等与现实结果核验。既定破坏性管理操作边界不外推成日常能力审批。

当前固定边界：

- 单实例、单 subject、单当前 generation、单权威 Runtime；
- 模块化单体，不是多 Agent、微服务、多租户或多角色平台；
- PostgreSQL 是权威关系事实源，Artifact Store 管理大对象，派生投影可重建；
- 每类主体/生活/关系/权限/效果事实只有一个 owner 和正式写入路径；
- 客观记录、外部证据、第一人称经历、主观记忆分别建模；
- 意愿、授权和现实结果分别由 Cognition/Expression、Capability、Effect/adapter 回答；
- 模型与外部机制不可信，只能返回冻结合同内的候选、证据或回执；
- 对外副作用先登记，后尝试，再核验；unknown 是正式状态，不能用重试抹平。

## 2. 部署与进程拓扑

**部署约束：已安装 ARMI 的全部受管文件必须位于同一个安装根目录。** 根内按 `versions/`（程序）、`environments/active/`（数据库、配置、凭据、模型与运行数据）、`control/`（安装设置、环境索引和独立管理记录）、`cache/`、`tmp/` 分工。管理记录放在可重置环境之外，但不能放到安装根之外。安装根不可写时明确失败，不另建 AppData 数据目录或仓库父目录下的控制目录。Windows 系统入口登记不作为私有数据存储位置。更新与卸载须按受管程序清单执行，保留环境与必要管理记录，不整根递归删除。桌面默认打开根内环境，Setup 统一拒绝根外环境路径；安装索引与 Admin 控制路径共享此布局，入口为自身及子进程设置根内缓存、临时目录。

```text
                         Windows local machine

 Creator browser ──HTTP/SSE──┐
 ARMI cli/mcp interaction ──认证本机──┤
 QQ/NapCat ──OneBot──────────┤
 WASAPI / DirectShow / USB ──┤
                             ▼
                    ┌─────────────────┐
                    │  armi-runtime   │
                    │ authority + app │
                    │ 23 owner ports  │
                    │ durable workers │
                    └───┬─────┬───────┘
                        │     │
          short UoW/SQL │     │ governed artifacts
                        ▼     ▼
              PostgreSQL 18.4  Artifact Store
                 + vector/trgm   under environment/data

      model / Web / Codex / NapCat / device I/O occurs outside write UoW

 ARMI cli admin / ARMI mcp admin ──独立配置/角色/进程──► owner Admin ports
 Codex runner ──一次性 workspace；无 DB/Admin/宿主 secret
```

Runtime 是唯一正常活动写入者。Admin 使用独立进程、配置、credential、pool 和 owner 管理端口；Creator UI 不接触 Admin。ARMI→Codex runner 显式关闭 MCP，不能发现 Codex→ARMI Admin 链。

`armi-app` 是依赖 Runtime 与 Admin 的顶层分派包，按 GUI、CLI、MCP 模式仅加载指定入口；它不合并权限或业务用例，底层应用不反向依赖它。安装版唯一产品 EXE 为 `ARMI.exe`，机器模式保留标准流与退出码，GUI 模式不创建控制台。取消原生启动器时只结束本次机器传输，不结束独立 Runtime。安装维护由私有 Python 模块执行；主入口、版本指针及程序字段由更新日志统一恢复，旧辅助 EXE 只在确认归属且切换成功后清理。

Windows 安装版按当前用户部署，不注册系统服务。私有 Python、锁定 wheels、已构建网页和原生 PostgreSQL 随包交付；`ARMI cli setup` / `ARMI mcp setup` 与 Tk/ttk 窗口共用安装应用服务。首次配置只在明确的新目录生成独立凭据和绑定，完成数据库初始化后仍保持未出生，出生调用正式 owner 路径。托盘通过已有生命周期用例启停 Runtime、附属工作和所属数据库；关闭网页不停止进程。

程序与环境在安装根内使用不同子目录。安装器将包放入 `versions/<package_id>`，原生 EXE 根据 `.current-version` 找到私有运行环境。程序清单记录文件摘要、包身份和数据库合同；更新先核对现有环境及数据库，再替换程序路径和包身份，原子切换版本指针。中断恢复记录只保存程序字段，不复制凭据或数据；不兼容数据库合同拒绝切换。卸载先核验并停止受管进程，保留根内环境数据和 `control/` 中必要的安装与环境身份记录。此路径不提供备份、旧 Docker 数据导入或跨 schema 迁移。

原生 PG 管理器使用 `initdb`、`pg_ctl` 和数据库检查，进程身份绑定可执行文件、命令行、创建时间、数据目录、持久端口及集群 system identifier。仅监听回环地址，使用 UTF-8、UTC、builtin `C.UTF-8`、校验和与 SCRAM；端口冲突失败，不连接占用该端口的其他数据库。系统测试通过同一管理器创建独立临时集群。

对外优先服务 Creator 委托的 Agent。交互绑定固定环境、Creator、delegate、凭据 locator 和读写范围；来源由认证入口写入 `party_input_interactions.delegate_id`，并进入当前输入与近期对话的 Context。代理不成为第二关系身份，不能用消息正文声明授权。

场合管理、Creator guidance、能力决定、数据权利申请与正式导出的请求也将认证 delegate 传到 owner 命令，由 owner 写事务记录 `creator_delegate` 审计来源；Creator 本人入口保持本人来源。业务参数不接受调用者自填的 delegate。

`armi-local-control` 共用配置加载、本机过程身份、进程锁及生命周期合同，不是业务 owner。交互客户端不持有 Admin 数据库凭据；Admin 按操作需要建连，因此数据库停止时仍可发现工具、检查本机进程和启动环境。

## 3. 分层与依赖

业务依赖方向是 `Interface → Application → Domain`，外部实现通过稳定 port 注入：

- **Domain**：值对象、不变量、候选/命令语义；不得依赖数据库、FastAPI、Provider/平台 SDK 或客户端格式。
- **Application**：用例、owner 协调、事务边界和稳定端口；不拥有外部连接细节。
- **Interface**：CLI、Creator HTTP/OpenAPI/SSE、Admin MCP、渠道 intake。
- **Adapter**：PostgreSQL、Artifact Store、模型、Web、Codex、NapCat、WASAPI、DirectShow、serial。
- **Composition Root**：读取配置与 secrets、核验环境/数据库、选择唯一活动适配器并组装 owner/worker。

业务模块公共面只在 `api.py`，组合入口只在 `bootstrap.py`，`_*.py` 私有。架构 gate 拒绝深导入、反向依赖、动态导出、公共 `Any`、合同同族并行数字版本以及生产 SQL 越权写表。

## 4. 事实所有权

23 个 owner 不是独立主体，而是同一主体的责任分区：

| 事实域 | Owner |
|---|---|
| 接触与感知 | interaction、perception、live-voice、live-vision、evidence |
| 进入认知 | opportunity（distribution: attention）、context、experience、cognition |
| 主观生活 | memory、relationship、activity、material、subject-state、mood、prompt、sleep |
| 意愿与现实 | expression、capability、effect |
| 外部工作 | web-observation、codex |
| 治理 | data-rights |

Owner 同时拥有本类领域合同、表、DML、head/revisions、幂等与并发语义、恢复检查、数据权利参与和 Admin 校正端口。`tools/schema_ownership.py` 把当前 101 张表逐一映射到 owner，并扫描 production SQL；跨 owner 改变必须通过公共端口与 Subject Commit，不能 join/update 别人的表绕过不变量。

## 5. 主体与连续性

连续性由 environment identity、subject/generation、各 owner revision/head、因果引用、Artifact custody 和 Runtime authority 共同建立。模型会话、PID、网页 session、设备或渠道账号都可替换，不能成为“她是谁”的根。

出生只在已安装的空白生活环境中执行一次。当前 birth contract 建立：电子人 identity、唯一 primary Creator、空名字/兴趣/目标/偏好/价值、固定人格锚点、零点 Mood home base 和清醒 life mode。Birth manifest 不能嵌入经历、关系、自我描述等后天生活内容。

Subject State 拥有统一主体版本及 Self/Mind/life mode；Mood、Relationship、Memory 等仍有各自 revision。一次认知中的多 owner 变化在同一 Subject Commit 中验证并原子提交，避免出现“记住了但关系没变”之类的半提交。

## 6. 输入、Context 与认知

### 6.1 正式 intake

Creator HTTP/CLI、other-human 控制面、QQ、live voice、视觉/Web/Codex 结果都先形成稳定 interaction/evidence/opportunity 身份。重复 idempotency key 返回同一逻辑接纳，不产生第二段经历。外部媒体先成为受治理 artifact，再由 Perception 识别；识别文字不自动等于 sender 原话或主体记忆。

### 6.2 Context

Context 以 purpose profile 冻结，而不是拼接所有历史。四层为 stable prefix、scope context、conversation history、turn tail；可选 section 闭集为 runtime truth、purpose、Self、Mind、Mood、life mode、scene、relationship、memory、activity、material、evidence、capability、prompt。

Profile 同时声明 required、optional、retrieval、forbidden：Creator 文本可召回 memory/material；Creator voice 当前只召回 memory；other-human 禁止 Creator prompt 和私人生活召回；视觉、Codex、睡眠各有更窄范围。最近对话只取同一 scene 最多八个已接纳真实事件。外部文件在快照事务外读取，最终 Context bytes、digest、来源与版本作为 artifact 固定。

### 6.3 Creator 单次认知

标准 Creator 文本、语音和精确生命查询结果各只进行一次主认知调用。当前 `armi.creator-cognitive-act-candidate.v3` 允许：reply、decline、no_action、no_change、defer、need_information、exact_life_query、web_research；并可带一项 experience、语义 appraisal、受限 owner changes。

模型只提出业务决定，不能生成 subject/scene ID、revision/version、权限结果、Emotion/VAD 数字、usage/model identity 或现实结果。关系/承诺变化必须有 experience；记忆只在当前 Creator 明确要求 remember 时形成。Voice compact wire 会确定性还原为同一语义，不是旁路合同。

### 6.4 Subject Commit

```text
frozen Context + expected subject/owner versions
  → model attempt outside transaction
  → strict parse + reference validation
  → each owner validates its command
  → transaction checks runtime fence / work lease / generation / versions
  → all accepted owner revisions + cognition application + subject version
  → commit
```

执行器将实际模型响应、usage 与模型成功以短事务保存，此时认知仍处于 `finalizing`。本次响应直接传入校验器，类型化变更集直接传入提交服务；受治理存档保留，正常执行不重读存档接续工作。制品在事务外准备，最终事务原子登记校验、应用事实、主体变化、意图、Effect/outbox 并结算工作；全程共享同一租约、续租和取消信号。后续失败不改写已成功的模型调用。

任一 owner 失败不留下半个主体变化。并发版本已推进时旧候选 stale，不能最后写入者覆盖。模型明确失败可按同一 work 预算安全重试；Provider 已受理但结果 unknown 时不再调用。

精确生命查询和网页研究是后续耐久 work：结果成为同一 root opportunity 下的新证据和新 episode，不在原 episode 偷加第二次模型调用。

## 7. 数据模型与读取

### 7.1 权威关系事实

PostgreSQL 保存 subject、life、work、effect 与治理事实。多数可变事实使用 append-only revision/event + current head；写入携带 expected revision/subject version。数据库 statement time 提供权威时序，UUIDv7 提供稳定身份。

当前 101 张表、1269 个字段、owner、关系、约束、索引与 ACL 的实现派生目录见[数据设计](docs/03-数据设计/)。该目录是 baseline 的只读说明，不替代 packaged SQL、owner registry 或测试。

### 7.2 Artifact

物理 bytes 按内容寻址；逻辑 artifact 保存业务用途、privacy、MIME、size、digest、publication 与 lifecycle。一个物理对象可被多个逻辑事实引用。发布预约、核验、退役和物理删除分开；逻辑删除只有在引用清空并满足 grace 后才形成物理删除 work。

### 7.3 客观记录与主观记忆

- Interaction：谁在何时通过哪个 scene/contact 发生了什么；
- Evidence/Perception/Web：外部观察与识别证据；
- Experience：被主体接纳的一人称经历；
- Memory：当前可访问、可淡化、可重释或遗忘的主观记忆；
- Diagnostics/Audit：系统行为证据，不能进入普通认知补全遗忘。

### 7.4 派生投影

Embedding、关键词索引、列表投影、游标和前端缓存可删除重建。语义召回仅覆盖 current accessible memory 与未删除 material：固定 Qwen 1024 维 embedding，HNSW/halfvec 取稠密候选，GiST trigram 取关键词候选，原向量/真实词相似度精排，owner 集合 SQL 复核资格，再用 RRF 融合。投影 binding/profile/head/coverage 不符时不得进入 Context。

## 8. Mood

模型只给有 Context 依据的语义 appraisal；Mood owner 确定性推导情绪成分、VAD target、half-life、当前 top emotions 和 action tendencies。权威状态当前为 `armi.mood.v3`，候选为 `armi.mood-candidate.v4`。

事件以 new/reinforce/reappraise/resolve 形成 episode 轨迹。当前快照按数据库 `as_of` 从 home base 和仍有效事件推导，不按秒写库；同一事实和时间得到同一结果。Mood 只作为 Context 状态/建议，不能直接改变 Self、Memory、Relationship、Capability 或 Effect。Home base 只在 sleep maintenance 的确定性 `reflect_mood` 阶段小步调整。

ESP32 心情窗只接收 Mood 映射后的不透明 face、color、energy 和 version；情绪名、nuance、事件和 VAD 原值不离开主机。

## 9. Durable Work 与恢复

数据库是工作 custody；进程 wakeup 只优化延迟。当前 `WorkType` 是 11 项闭集、12 组责任绑定，覆盖 Context、认知执行、Web、外部内容、生命查询、embedding、artifact 删除、视觉采集和视觉识别。认知只有 `cognition.context.prepare` 与 `cognition.execute` 两类任务；候选校验和 Subject Commit 由后者直接调用，不再领取独立 work。每个 `(owner kind, work type)` 映射唯一 reconciliation owner。

Work 以 ready/leased/completed/failed/cancelled 管理执行资格；业务 owner 决定 attempt/result 和是否可恢复。慢 I/O 前短事务登记，事务外调用，结算事务重新检查 lease/fence/generation/current state。重启后由固定 recovery roster 检查 owner head、过期 work、artifact、effect unknown 和投影 coverage；框架不猜业务修复。

Creator export 使用 `armi.creator-export.v5`，由 Data Rights 管理导出路径及涉及的 party scope；外部副本无法删除时必须保持 partial/operator action，而非伪报完成。

## 10. 意愿、授权与 Effect

普通 Creator 文本、实时语音、QQ 私聊及共用回复链的主动表达，由代码、harness 与渠道配置直接执行，不建立申请、批准、grant、policy、有效期或使用次数。

```text
Cognition decision
  → Subject Commit: 主体变化 + Expression intent/decision + Effect/outbox（同一事务）
  → adapter attempt outside transaction
  → receipt / observation / verification
```

Effect 保持 registered、dispatching、completed 等当前机器状态，并保留失败、拒绝、不可用、取消和 unknown 的不同语义。平台模糊超时、部分语音播放等可能已经产生副作用，不能安全重试。所有重试共享一个语义操作预算和稳定 effect identity。

回复正文在事务外保存，提交只登记引用；发送时核验实际读取的正文及当前接收目标、渠道配置、隐私和数据权利。普通回复 outbox 的发送截止时间为空；网络超时、worker 租约与并发 fence 只负责执行控制。普通回复不生成回复准入 work。Codex 也在 Subject Commit 同事务登记 Effect/outbox，`effect.register` 工作类型及后台登记流程已删除。

所有 purpose 的未完成认知中断即结束，包括其他人对话、自主活动与睡眠整理；未调用 attempt 取消，调用结果不明保留 unknown，已保存响应和已提交主体变化保留，不读取旧响应或变更集续算。长期活动、维护阶段和进度由原 owner 保留，原调度按当前状态重新创建机会与 Context，沿用重新考虑上限，耗尽明确失败。独立效果的其他恢复语义不扩展。

普通对话中断即结束。停机和启动入口调用现有 owner 的收尾逻辑，终结这一轮未完成的机会、认知和派生 work；已提交的主体变化与完成的发送保留，尚未发送的回复取消，已开始发送但结果不确定的回复保留 unknown/部分完成，不重发，也不要求人为恢复这一轮。新输入和新的主动表达可以继续，旧动作不得重放。Codex 委托沿用相同的中断原则，管理端授权和真实完整性故障的检查保持各自语义；现有数据库不会自动迁移、重装或清空。

Creator operation 投影聚合 cognition、Codex 与 effect 阶段，但不把 operation 完成等同于外部送达核验。SSE 只提示投影失效，UI 必须重新 GET 权威投影。

## 11. 外部边界

### 主模型与 Web

模型绑定由 `configs/model-bindings.yaml` v2 统一管理；purpose 决定 response contract/token budget。普通 Creator 使用一次严格 cognitive act。ARMI 网页研究由 `web_research` 决定触发，Web owner 只允许 search/open/find，并把来源/content 作为 Evidence；普通 cognition tools 列表为空，不自动给主模型上网。

### Codex

`codex.enabled` 默认关闭，由现有配置管理保存、重启生效。Context 和 Runtime 状态读取同一份实际可用性，包括开启状态、本地执行器与凭据是否就绪及失败原因。关闭或不可用时新任务明确失败；旧幂等键仍指向原任务，不重跑。

主链为：Creator／代理提交任务 → ARMI 决定是否委托 → Subject Commit 原子登记主体变化、委托意图和 Effect/outbox → 执行与核验 → 结果进入认知。普通对话不自主生成 Codex 任务。申请、申请依据与决定、grant、policy decision、effect registration 六类表和审批接口均已删除。任务制品在事务外保存，提交登记引用，执行时验证实际内容；outbox 无业务有效期，执行器继续执行既有超时与隔离限制。

停机、崩溃或 Runtime 更换后，未启动的委托取消；已启动且无可靠结果的保留 unknown，取消信号终止子进程树并清理临时工作区，不重跑、不回读临时目录。已提交主体事实、核验结果和受治理制品保留。原任务和独立结果机会链及其派生工作均由现有 owner 收尾；收尾后的旧执行结果不能越过 fence 和终态，也不能派生工作。任务投影分别显示执行与后续认知状态，执行完成不代表结果已被 ARMI 理解或采纳。

Creator 可逐任务选择 `gpt-5.6-sol|terra|luna`、`low..max` reasoning 和内置 Web Search。Runner 使用官方 SDK/订阅 auth、一次性 2GiB workspace、20MiB diff、500 modified files、workspace-write sandbox；shell network 始终 false。显式 Web Search 只打开 Codex 内置只读搜索。MCP/apps/skills/hooks/workspace dependencies/credentials 关闭。结果在私有 custody 副本验证后成为 Evidence/Opportunity，不能直接提交主体。

### QQ/NapCat

`armi-channel-napcat` 负责 OneBot/NapCat，`armi-adapter-qq` 映射 ARMI interaction/effect。环境必须显式 allow party/group 与回复政策；event secret 和 API token 分离。媒体进入 Perception；当前正式出站回复为文本。模糊发送结果不重发。

### Voice

WASAPI 精确设备 → 16kHz mono PCM16 → streaming ASR → 正式 Creator intake → Character strict compact JSON → Subject Commit → audio Effect → streaming TTS/playback receipt。模型 token 不提前播放；partial/unknown playback 不自动重播。

### Vision

`live-vision` 同时拥有 camera 与 screen：摄像头以 DirectShow moniker、DevicePath 和 USB LocationPaths 精确绑定；屏幕以 QueryDisplayConfig 的 source device、monitor path、EDID 名称、尺寸和边界精确绑定，锁屏、安全/非交互桌面及身份变化时拒绝采集。两路各有 session、内存帧缓冲、变化检测、cooldown 和小时预算；所有观察先登记 `live.vision.capture`，事务外抓取新帧，再登记视觉识别。自动或无 scene 结果进入受限私有视觉认知；对话内 subject request 保留原 scene/relationship，并通过 follow-up cognition 回答 Creator。视觉结果先成为 Evidence/Opportunity，不能自行写成记忆。

## 12. Creator 与 Admin 接口

Creator HTTP 仅绑定 `127.0.0.1`。浏览器建立 process-local bearer session，token 存在 `sessionStorage`；API 拒绝 cookie，客户端 `credentials: omit`。Runtime 验证 same-origin/Fetch Metadata/Host，限制 header/body/连接，提供 CSP/COOP/Permissions Policy，并只托管 manifest 枚举且 digest 匹配的静态资源。

当前 OpenAPI 52 paths，覆盖 scene/message/operation/effect、Activity、Memory、Material、Relationship、Prompt、Capability、Maintenance、Export/Data Rights、Subject、QQ、Voice、Vision。分页 cursor 绑定环境、Creator、资源、查询和 projection version；SSE 是有限 process-local invalidation broker，不是耐久事实源。

机器交互目录覆盖 52 个非浏览器业务/健康操作和 5 个本地上传操作，另有能力发现、有界等待与本机文件导入组合。所有操作直接调用 Runtime 应用服务：交流命令、主体生活、治理、渠道感知和记录查询按责任分组；HTTP 只负责浏览器鉴权和传输，机器调用不构造 Request 或调用 HTTP handler。`application/interaction_definitions.py` 的显式目录和应用请求/结果模型生成 CLI、MCP 与 OpenAPI，不读取打包 OpenAPI 反向拼装业务接口。本地分块上传属于机器传输合同，不新增浏览器上传路由。制品支持有界分块、完整内容摘要和 CLI 原子发布到不覆盖的输出路径。旧混合 Runtime CLI 已移除，私有 worker 仅接收固定 Runtime 启动参数；管理用例经正式 Admin 绑定调用。

Effect 的 Creator 制品读取用例统一返回实际交付内容及其摘要：补丁与验证报告复用已验证的源摘要，最终正文从内部 JSON 提取后单独计算摘要。进程内 LRU 仅缓存交付字节，最多 64 MiB／32 项，空闲 60 秒释放；20 MiB 单制品上限不变，冷加载串行，关闭文件后才复用内容。每次读取仍在 Runtime 与数据权利共享 custody 下检查 Creator 可见性、当前保留引用及完整性状态；冷加载在事务外执行，结束后重验引用和 Runtime fence。缓存命中不重复扫描磁盘，淘汰后重新验证；引用失效或 Runtime 更换不能返回旧缓存。Web 与机器端消费同一结果，分块仅切片，不逐块全量散列。缓存容量不包含临时加载和解析内存，也不构成持久副本。

本地媒体先分块导入，再显式 `message send` 接纳。上传接收记录绑定 environment、generation、Creator 和认证 delegate，保存进度、分块重复校验与稳定发布 identity；文件和散列校验位于权威事务外，完成后通过 Artifact owner 登记 Creator 可见引用。上传完成不触发认知。Interaction owner 将正文和逐附件引用接纳为一次输入，复用 Perception 的识别、恢复和结算，再向 Context 提供有来源的感知材料。操作引用在识别前后保持稳定，逐附件保留失败和 unknown；已经完成交流但附件有失败时汇总为 partial。识别工作失败或需要对账时从耐久 work 读取当前事实，不无限等待回复文本。

Admin 因果追踪从输入、认知、操作或效果引用沿 owner ports 连接 Evidence、Opportunity、冻结 Context 制品、Subject Commit、Effect、outbox 与交付，不读取私有制品正文。私有主体快照另需 `subject_snapshot.private`。Agent 的相关数据删除通过 `data_deletion_preview/apply`：预览和执行复用 Data Rights participant 的目标发现逻辑，授权绑定目标摘要；owner 在短事务中重算摘要，确认范围未变后才登记及执行删除。Creator Web 的本人申请保留，普通机器交互及混合 other-human 删除请求不能绕过一次性授权。

Admin CLI/MCP 共用 `application/service.py` 和显式操作目录，配置为 `armi.admin-config.v8`。支持显式绑定的 `active`、`development`、`system_test`、`acceptance`；正式环境禁止 test controls。绑定记录 `operator_id` 和逐项 `authorized_operations`，普通配置编辑不能修改本身的管理权限。

管理 wire 为 `5.0`。生命周期、配置应用及管理写请求用稳定环境、incarnation、操作者和幂等键保存耐久回执；包升级和普通配置修改不改变回执身份。读取与预览获取当前事实，不复用写回执。`invocation get/wait` 返回阶段；运行中、已结算和中断后的 unknown 分开，不自动重放副作用，读取旧回执仍核验当前权限。

重置及主体内容校正使用一次性 Ed25519 授权凭据：独立 Creator 授权绑定持有签发 locator，普通 Agent 绑定只持有验证公钥。凭据绑定具体预览、目标/版本/影响、环境 incarnation、操作者与参数，最长 10 分钟且不晚于预览到期；支持查询、撤销和耐久消费。执行继续经过停机、版本及 owner 检查，文字授权引用只作审计说明。重置不做数据库 dump 或整环境归档，正式 Creator 导出独立保留。

`environment_start/status/stop/restart` 默认管理整个明确归属的环境，单组件复用同一实现；生命周期、初始化、写入维护和重置使用环境互斥，控制文件位于重置目录之外。停止确认 Runtime 排空退出后才停止附属进程，共享依赖只报告、不回收。`start_armi.ps1` 是薄入口，正常启动不安装依赖、建库、出生或构建 Web。

配置使用完整消费者模型、文件版本和进程锁原子保存。无效文件可安全读取版本及错误码，并使用完整候选文档修复；候选不能更换绑定环境和 data root。消费者验证并采用配置后登记当前版本，重载替换原登记，准备失败不发布新版本。状态区分已生效、部分消费者生效、需要重启、未运行、环境变量覆盖和无法核验；仅文件读取或保存不证明生效。模型与 Web research 的环境覆盖从 `<root>/configs/` 加载。综合诊断读取获授权凭据的可解析性、渠道状态、设备枚举与绑定比较，以及 owner 的 work、lease、恢复与制品状态；物理制品核验在数据库事务之外，有明确对象/字节预算并报告抽样覆盖，不触发模型或设备采集。

Admin 的业务结果模型由操作目录统一生成 CLI/MCP 合同并校验返回值，维护和其他人管理进一步按子操作核验。`invocation_reconcile` 重新核验原操作权限，使用环境互斥锁及独立执行证据恢复中断调用：生命周期完成阶段、配置原子替换前登记的文件身份和版本、owner 校正状态及删除请求幂等记录。控制目录不随重置清除，不保存配置或主体内容副本；证据不足保持 unknown，不重新执行效果。scope graph v2 另行报告关系展开上限与截断，分页结束不代表完整展开。

## 13. 数据库与配置

当前数据库要求 PostgreSQL 18.4、UTF-8/UTC/builtin `C.UTF-8`、vector 0.8.6、pg_trgm 1.6、唯一 `0000`、baseline `armi.schema-baseline.v16` 和精确 role policy。Schema 是 package resource，十份有序 baseline SQL 当前创建 101 tables/1269 columns/1 read-only view/62 explicit indexes。安装只接受无用户 relation 且无现存 `armi` namespace 的目标库：namespace 先在独立短事务建立，随后 `0000` 在一个事务组内写入表、约束、ACL、revision、identity 与 digests；中段失败可以留下空 namespace，但不会留下业务表或前移 revision。Runtime 只验证，不安装/迁移。

配置合并顺序：仓库 `configs/runtime.yaml` → 环境根 `environment.yaml` → 登记的 `ARMI_*` 覆盖。当前 schema v3，strict/frozen/extra-forbid。环境根必须有普通 `environment.yaml`、`data/`、`secrets/`；data root 精确相等，禁止 reparse。Secret 只用 `env:ARMI_SECRET_*` 或位于 `secrets/` 的 `file:` locator，最大 64KiB，经 scoped handle 消费后清零。

## 14. 失败语义

| 情况 | 当前处理 |
|---|---|
| Config/schema/ACL 不匹配 | 启动或操作明确失败，不自动修复 |
| 可选能力未配置 | disabled/unavailable，与核心 readiness 分开 |
| 模型明确可恢复错误 | 同一 work/attempt 预算内重试 |
| 确定性合同/权限错误 | 不重试；保存失败原因 |
| Provider/平台已受理但无法确认 | unknown，对账，不重新制造副作用 |
| Subject/owner version 已过期 | stale conflict，不最后写入者覆盖 |
| 派生投影缺失/旧 binding | 标记不完整并耐久重建，不改 owner head |
| Artifact 缺失/摘要错 | integrity failure，不能用空正文继续 |
| Admin/Recovery finding 阻塞 | 保持 blocked，不能 warning 后开放业务 |

正式 `no_action`、`no_change` 和 `decline` 是主体决定，不是运行错误 fallback。

## 15. 验证边界

Fast gate 覆盖锁、格式、lint、类型、离线 tests、架构/安全和 Web；Release 增加 build/wheel；System 增加临时真实 PostgreSQL、固定 Chromium 和 Creator 系统旅程。System 不连接真实模型、Web、Codex、QQ 或设备。

声称目标环境 Creator 闭环可用必须显式运行 `tools/verify_live_creator_roundtrip.py`，证明 cognition、Subject Commit、reply Effect、outbox 与非空 reply artifact；它会产生真实记录与模型成本。模型/Web/Codex/QQ/Voice/Vision/display 各有独立 live 边界，未运行时只能报告离线实现/合同通过。

## 16. 变更原则

- 新能力先判断事实 owner；没有独立生命周期、关系、权限/保留或查询模式，不新增模块/表。
- 慢 I/O 保持事务外；先登记稳定 identity，回库重新验证 current state。
- 公共合同变化原子同步生产者、消费者、baseline/constraint、配置、OpenAPI/生成代码和 tests，并删除旧版本/别名/双读。
- Schema 直接更新唯一 baseline 并替换 identity；不增加历史 revision、downgrade 或迁移兼容。
- 新适配器只在 composition root 选择；没有第二个真实实现时不建通用框架。
- 设计正文只描述当前有效结论。外部研究先作为证据，未吸收前不进入产品合同。

更细的产品、系统、实现和运行资料见 [docs/README.md](docs/README.md)。
