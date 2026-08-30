# ARMI 项目协作规则

本文件只保存 ARMI 特有、会长期改变实现行为的事实与边界。通用安全、Windows、Git、实现和验证规则继续遵循上级 `AGENTS.md`；冲突时按更高优先级指令执行。

## 1. 开始前先固定事实

- 先读根 `README.md`、`DESIGN.md`、`docs/README.md`，再按任务读取最接近事实源头的设计正文、当前代码、配置和测试。不要从目录名或旧文档猜实现。
- 事实优先级：当前代码 → `packages/armi-postgresql-contract/src/armi_postgresql_contract/resources/schema/` 与唯一 `0000` → `configs/`、锁文件、生成合同 → 测试与目标环境证据 → `DESIGN.md`/`docs/` 正文 → `docs/00-外部研究参考/`。
- 明确区分：代码存在、配置声明启用、目标环境完成配置、外部服务/设备可用、端到端 live 通过。证据只允许支撑对应强度的结论。
- `docs/` 被 Git 忽略但仍是本地设计资料；涉及设计语义时必须同步。外部研究只提供带来源证据，只有被正式正文吸收后才成为 ARMI 决策。
- 后续工作由用户逐项指定。不得从历史路线图、阶段号、研究建议或“顺手完善”自行扩大开发范围。
- 项目当前未授予开源许可证；不得擅自声明开源、复制不兼容源码/素材，或删除研究资料中的来源与许可证记录。

## 2. 产品不变量

- ARMI 承载一个自主电子人长期存在，不是通用助手、角色平台、多租户产品、多 Agent 编排器或可热插拔人格框架。
- 正常运行只有一个 ARMI、一个 subject、一个当前 generation、一条权威生命线和一个被承认的活动 Runtime。模型、进程、入口、scene、activity、设备、渠道与外部 Agent 都不是第二主体。
- 出生只建立最小身份、唯一 primary Creator 和人格锚点；名字、经历、兴趣、目标、偏好、价值、关系与自我描述必须在正式生活中形成，不能由 bootstrap/sample 预写。
- 主体、生活、关系、权限、表达、外部效果和数据权利各有唯一事实 owner 与正式写入路径。客户端、缓存、索引、摘要、向量和其他投影不能反向覆盖权威事实。
- 客观 interaction/evidence/attempt 与主观 experience/memory/relationship/mood 分离。日志不能在普通认知中补全遗忘，主观遗忘也不改写正常运行记录。
- 系统权限回答“能不能”，ARMI 的认知回答“想不想”。Creator 的系统管理权不自动成为社会关系中的绝对命令权。
- 模型、Web、平台、Codex、工具和设备都在信任边界外，只返回候选、证据或回执；不能提交主体状态、扩大权限、定义现实结果或生成权威版本/身份。
- 表达与现实动作必须先登记、后执行、再核验；请求、attempt、receipt、verification 可追溯。拒绝、不可用、明确失败、结果未知、部分完成与核验完成不得合并。
- 正式能力/配置/凭据/数据缺失时明确失败。不得用 mock、fixture、旧缓存、sample、默认字段或角色化文案伪造真实闭环。

## 3. 架构与实现边界

- 当前是单权威 Runtime 的模块化单体。依赖方向为 `Interface → Application → Domain`，适配器经稳定 port 接入，具体实现只在 `apps/armi-runtime/src/armi_runtime/composition/` 选择。
- 23 个业务 distribution 是事实 owner，不是微服务或 Agent。公共面只在模块 `api.py`，组合入口只在 `bootstrap.py`，`_*.py` 为私有；跨模块不得深导入、反向依赖或用共享 repository 绕过 owner。
- Owner 对自己的领域合同、表、DML、head/revisions、恢复、数据权利和 Admin 校正负责。跨 owner 变化通过公共端口和 Subject Commit；生产 SQL 写入必须符合 `tools/schema_ownership.py`。
- 模型、网络、文件、设备、Codex 与其他慢 I/O 不得处于权威数据库写事务内。短事务先登记稳定 identity/work/effect，事务外调用，结算事务重新验证 Runtime fence、lease、generation、subject/owner version 和幂等状态。
- 并发变化不得采用最后写入者覆盖。旧候选返回时若版本已推进，明确 stale/失败或重新认知；不能只重放旧 JSON。
- Durable work 使用 `armi_kernel.application.durable_work.WorkType` 闭集和责任 registry。进程 wakeup 只优化延迟，不能承载唯一 payload/完成事实；新增 work 同步 owner kind、reconciliation owner、恢复和测试。
- 高变化机制接收冻结、获准、带版本输入，只返回候选/证据/回执。实验 variant 仅在隔离环境、离线回放或只读 shadow 比较，未激活前不得写 Active 主体、work 或 effect。
- 新能力优先进入现有 owner。只有存在独立 owner、生命周期、一对多关系、权限/保留策略或显著独立查询模式才新增表/模块；渠道、party kind、枚举或 adapter 差异本身不构成理由。
- 只有第二个真实实现、外部消费者或已声明扩展合同存在时才引入通用抽象。机制替换完成后删除旧入口、接线、selector、配置、类型、别名和无调用者兼容路径。
- 不为未来可能性预建微服务、多 ARMI、跨设备多活、通用插件市场、运行时热加载、万能数据模型或永久兼容层。

## 4. 数据库、配置与机器合同

- PostgreSQL 是唯一权威关系数据库。开发/测试固定使用 Docker PostgreSQL 18.4 + pgvector 0.8.6；Runtime 只通过 DSN 使用它，容器和 volume 不是第二事实源。
- Schema 资源位于 `packages/armi-postgresql-contract/src/armi_postgresql_contract/resources/schema/`。只保留可重做的唯一 Alembic `0000`，不使用 autogenerate、后续 revision、downgrade、历史迁移或旧数据库兼容。
- 结构变化直接更新 baseline SQL、`0000` 文档列表、baseline identity、owner registry、ACL、生产者/消费者和测试；目标数据库显式删库重装，不迁移历史数据库、消息或制品。
- `armi db install` 只接受空库并原子安装。Runtime/普通启动只核验 PostgreSQL/扩展、唯一 revision、baseline/resource/catalog/role digests 与精确 ACL，不自动安装、迁移或用超级用户掩盖权限漂移。
- 同一 ARMI 内部合同族只保留一个当前数字版本。升级要原子同步生产者、消费者、DDL/约束、配置、OpenAPI、生成代码、工具与测试，并删除旧解析器、旧字段、双读双写和缺字段补默认值。第三方 MCP/NapCat/Provider 协议按其当前标准处理，不恢复 ARMI 旧合同。
- 人工维护的业务/部署配置集中在 `configs/` 并使用 YAML；环境根也使用严格 YAML。Codex MCP 注册保留其要求的 TOML；OpenAPI、JSON Schema、lock、生成资源和 wire 使用各自机器格式。
- Runtime config 当前由仓库默认 → 环境 `environment.yaml` → 登记的 `ARMI_*` 合并；unknown/extra/错误类型/敏感明文字段必须拒绝。Secret 只以 scoped locator 出现，不进入仓库、命令行、日志、摘要或导出。
- JSON 使用 UTF-8、2 空格、结尾换行。RFC 8785 只在摘要输入/wire 有真实消费时使用；不提交重复配置 schema、内部策略镜像、阶段状态或验收结果 JSON。
- Runtime 接线只由 Python composition root 定义，不维护重复 JSON 清单，也不把进程/接线摘要绑定为主体连续性。

## 5. 认知、模型、Codex 与管理面

- 标准 Creator 文本、实时语音和精确生命查询结果各只做一次主认知调用，返回本轮实际决定与必要正文/提议；不要恢复“回复分支 + 评价分支”或同 episode 隐藏追加调用。
- Context 必须由 purpose profile 冻结并保存来源/版本；other-human、视觉、Codex、睡眠等 purpose 遵守各自 forbidden section，不能靠提示词替代隐私隔离。
- 模型 identity、usage、subject/party/scene、version、digest、权限和现实结果由 adapter/Runtime 绑定。模型不得生成这些权威字段，也不得直接填写 Mood VAD/强度。
- Owner 分别验证 cognition candidate，最终最多一次原子 Subject Commit；任何 owner 失败不留下半提交。`no_action`/`no_change`/`decline` 是主体决定，不是错误 fallback。
- ARMI 自身 Web research 与 Codex built-in Web Search 是两条独立只读链；启用 Web Search 不等于 shell 有网络。网页结果先成为 Evidence/Opportunity，不能直接写 Memory/Relationship/回复。
- ARMI→Codex 使用官方 SDK和用户订阅 auth。每项委托可显式选择当前批准的 `gpt-5.6-sol|terra|luna`、reasoning 和内置 Web Search；不得固定退回某模型/低思考/一律禁网。
- Codex runner 只操作 task manifest 的一次性 workspace，遵守 allowed/forbidden paths；不得读取 ARMI DB、Admin、宿主 secret/配置或未经授权的外部系统。纯内容生成 `result.md`，代码/文件任务由独立 validator 和 custody 副本核验。
- ARMI→Codex runner 与 Codex→ARMI Admin MCP 必须隔离，不能互相发现、调用或继承 credential。Admin 仅限 `development`、`system_test`、`acceptance`，使用独立 config、role、pool 和 owner Admin ports，不暴露任意 SQL。
- 通过 Codex/自动化向运行中 ARMI 发话时使用 Admin `inject_creator_input` 或 `armi creator send` 正式 intake，并复用稳定 idempotency key；不得直写数据库或伪造浏览器 session。只有用户要求界面操作/视觉验收时才驱动浏览器。
- 未获授权不得连接真实 Provider/账号/设备或产生付费调用。已明确授权的任务只可使用该任务指定环境、provider、credential locator 和边界；换账号、凭据、环境或生产资源需另行授权。

## 6. 文档规则

- 根 `README.md` 是产品与最快入口，`DESIGN.md` 是可提交实现总览；`docs/` 按 `01-产品定义/`、`02-系统设计/`、`03-实现参考/`、`04-运行与验证/` 分层，外部证据只放 `00-外部研究参考/`。不要恢复根下扁平编号正文。
- `docs/` 只保留有助理解“ARMI 是谁、为何这样设计、当前实现如何承载她”的正文、运行证据和来源清楚的研究。不要加入路线图、需求编号矩阵、排期、阶段清单、单次门禁流水、临时评审或字段级合同镜像。
- 精确字段、路由、表、状态、版本和依赖放代码、DDL、配置、lock、OpenAPI 和测试；文档集中写不变量、责任、闭环、实现锚点和证据边界，避免同一易变数字在多处复制。
- 使用简体中文、UTF-8、LF 和相对链接。重写时删除失效结论/术语/入口，不保留旧版兼容页；性能记录保留日期、环境、方法和未验证边界，历史结果不得冒充本轮复测。
- 设计变化先分类为产品不变量、owner/跨模块合同、可替换机制、权威 schema、可重建投影或隔离实验。触及不变量、owner、权限或效果语义时，先改最接近事实源头的叙述，再同步代码与下游文档。
- 不为“完整感”填写占位方案、模拟结果或未经确认的选型。未知项写明未知、所需证据和不影响的边界。

## 7. 验证与收尾

- 先把任务变成可观察成功标准，运行能回答当前未知的最小静态检查/定向测试。只有风险命中公共合同、schema、依赖锁、生成器、composition、启动或跨模块边界时才扩大。
- Fast/Release/System、真实 PostgreSQL、浏览器、付费 live gate、外部程序、soak 与部署验证只在风险需要或用户明确授权时运行；不要用测试数量制造完成感。
- 数据库变化至少用真实 PostgreSQL 证明：空库前态、更新后的唯一 `0000` 原子安装、唯一 head/identity/digests/ACL、重复 install 合同、注入失败回滚且 revision 不前移，以及受影响 owner 主路径。项目没有历史回填/迁移验证。
- 视觉/UI 改动必须在目标 viewport 运行真实页面，用受控浏览器检查层级、比例、重叠、溢出、滚动、关键操作、空态和错误态；只读源码不能宣称视觉完成。
- 声称目标环境部署或真实 Creator 对话可用，必须在已授权真实调用后运行 `tools/verify_live_creator_roundtrip.py`，确认 cognition、Subject Commit、reply effect 核验、outbox 交付和非空回复 artifact。Component ready、数据库行或 mock/System test 不能替代。
- 文档变化至少检查：全部相对链接、实现锚点路径、旧目录/术语、当前合同版本、UTF-8/LF，以及与代码/配置/schema 的冲突。未运行的环境/Browser/live 验证明确列出。
- 修改前后检查 Git 状态并保留用户已有变化。仓库修改默认按可独立验证模块提交，只暂存本任务文件；`docs/` 被忽略不进入提交，最终同时报告本地 docs 变化和实际提交文件。
