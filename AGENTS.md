# ARMI 项目协作规则

本文件适用于整个仓库，只保存项目决策边界、工作入口和容易踩错的约定。通用授权、安全、Windows、Git、沟通与协作方式沿用已加载的全局规则；当前用户明确要求和更高优先级指令优先。修改子目录前检查路径上的规则，同目录优先读取 `AGENTS.override.md`。

## 1. 工作方式与事实源

以用户目标为范围，完成实现、必要验证和收尾。允许自主比较方案、做可逆实验、调整妨碍目标的结构并补齐必要依赖，不需要用户逐行指定。历史路线图、研究建议和旧阶段清单不构成新任务授权；可以提出更好的方向，但不擅自改变产品目标或外部影响。

- **Agent/LLM 优先**：交互与管理链路首先服务 Agent/LLM，优先完整、直接、高效、可自动化的机器接口。人类界面是第二优先级，不能要求机器通过页面、按钮、人工搬运结果或逐步确认才能完成已有能力；人类界面适配同一用例，不反向决定机器流程。
- **功能完整，流程简单**：功能在设置中开启即代表在配置范围内持续允许使用，由 ARMI 自主决定何时行动；范围内直接执行，不再叠加申请、审核、批准或一次性许可消费。普通回复作为基础能力直接可用。缺少必要信息或超出配置范围时明确返回原因与所缺信息，不自动建立审批工作流。
- **按实际职责瘦身**：删除或合并没有独立作用的中间状态、重复记录、重复校验、纯转发层和人工步骤，不以统一流程为理由让简单动作套用完整审批机制。校验保留在负责的边界；跨异步间隔确实可能变化的事实才重验。真实性、隐私范围、原子提交、幂等和效果核验仍须完整，不能靠减少功能或隐藏失败实现简化。
- **普通对话范围内直接执行，中断即结束**：Creator 文本、实时语音、QQ 私聊及共用回复链的主动表达，不生成回复申请、grant、policy 或业务有效期。Subject Commit 同事务登记回复意图及 Effect/outbox，发送边界核验渠道、接收目标和数据权利。停机、崩溃或 Runtime 更换后，未完成的这一轮不续算、不补答、不补发；保留已提交事实和已发生的发送结果，未发送取消，结果不确定保留 unknown/部分完成且不阻塞新对话。Codex 委托和管理端授权仍按各自现行合同处理。
- 上述原则约束产品链路，不自动扩大开发代理的外部操作授权；既定的数据保护和破坏性管理操作边界继续适用，不外推为日常功能的审批要求。现存申请/许可机制是待按真实职责简化的实现，不因代码、测试或旧文档存在就成为必须保留的产品要求。

首次进入项目读 [README.md](README.md)、[DESIGN.md](DESIGN.md) 和存在时的 [docs/README.md](docs/README.md)，已读且未失效的内容直接复用。随后按问题查调用链、机器合同和相关设计，不默认通读全部资料。

- **预期行为**由用户需求、产品不变量和正式接口约定决定；**实际行为**用当前代码、packaged schema、配置、锁文件、测试和目标环境证据判断。旧实现或测试不能成为保留缺陷的理由。
- `docs/` 被 Git 忽略，但设计语义变化仍须同步相关正文。缺失时先用可提交文档与机器合同推进，只有影响判断或必须同步时才报告缺口。外部研究未被正式设计吸收前只是证据。
- 工程机制可在目标内改进；触及产品不变量、事实 owner、权限或效果语义时，先明确变化及影响，并同步最接近事实源头的设计与消费者。

## 2. 产品与真实性边界

- ARMI 承载一个自主电子人长期存在：一个 subject、一个当前 generation、一条权威生命线、一个被承认的活动 Runtime。模型、进程、渠道、设备与外部 Agent 都不是第二主体，不扩展为多租户、多角色或通用 Agent 平台。
- 出生只建立最小身份、唯一 primary Creator 和人格锚点。名字、经历、兴趣、目标、偏好、价值、关系与自我描述在正式生活中形成，不能由 bootstrap/sample 预写。
- 每类主体、生活、关系、权限、表达、效果和数据权利事实都有唯一 owner 与正式写入路径。缓存、索引、摘要、向量和客户端等投影不能反向覆盖权威事实。
- 客观记录与主观经历、记忆分离：普通认知不能从日志补全遗忘，遗忘也不改写运行记录。系统权限与主体意愿分离，Creator 的管理权不等于关系中的绝对命令权。
- 模型、Web、平台、Codex、工具和设备只返回候选、证据或回执，不能提交主体状态、扩大权限或生成权威身份、版本、现实结果。表达与现实动作先登记、后执行、再核验；拒绝、不可用、失败、unknown、部分完成与核验完成分别保留。
- 正式能力、配置、凭据或数据缺失时明确失败，不用 mock、fixture、缓存、sample、默认值或角色化文案伪造真实闭环。`no_action`、`no_change`、`decline` 是主体决定，不是错误兜底。

## 3. 实现中必须守住的合同

当前采用单权威 Runtime 的模块化单体，详细结构见 [DESIGN.md](DESIGN.md)。

- 依赖方向为 `Interface → Application → Domain`，适配器通过稳定 port 接入，只在 [composition root](apps/armi-runtime/src/armi_runtime/composition/) 选择。业务模块公共面为 `api.py`，组合入口为 `bootstrap.py`，`_*.py` 私有，不跨模块深导入或通过共享 repository 绕过 owner。
- Owner 负责自己的表、DML、版本、恢复、数据权利和 Admin 校正；生产写入遵守 [schema ownership](tools/schema_ownership.py)。认知候选由各 owner 校验，最多一次原子 Subject Commit，任一失败不留下半提交。
- 慢模型、网络、文件、设备及 Codex I/O 在权威写事务外。先用短事务登记稳定 identity/work/effect，结算时重验 fence、lease、generation、subject/owner version 和幂等状态；旧候选 stale 后不能靠重放 JSON 或最后写入者覆盖解决。
- Durable work 使用 `armi_kernel.application.durable_work.WorkType` 闭集与责任 registry，新增时同步 owner、reconciliation、恢复和测试。数据库承载耐久事实，进程 wakeup 只优化延迟。实验使用隔离环境、离线回放或只读 shadow，未激活前不写 Active 主体、work 或 effect。
- 新能力先确定事实 owner；新增表或模块应有独立生命周期、关系、权限/保留策略或查询需求，不能只因渠道或枚举不同而拆分。替换机制后清理失效入口、接线与兼容路径，不为假想需求预建框架。
- 标准 Creator 文本、实时语音、精确生命查询结果各只做一次主认知调用，不在同 episode 隐藏追加评价调用。Context 按 purpose profile 冻结来源与版本，落实 forbidden section；提示词不能替代隐私隔离。模型不直接填写 Mood VAD/强度。

## 4. 数据库与配置变更

- PostgreSQL 是唯一权威关系数据库；开发/测试使用项目固定的 Docker PostgreSQL 与扩展。精确版本查配置、[工具链 manifest](tools/toolchain-manifest.json) 和 packaged contract，不在此维护第二份版本快照。
- [Schema 资源](packages/armi-postgresql-contract/src/armi_postgresql_contract/resources/schema/) 只保留可重做的唯一 Alembic `0000`。结构变化直接更新 baseline SQL、`0000` 资源列表、identity、owner registry、ACL 和消费者；不增加历史 revision、autogenerate、downgrade 或旧库迁移兼容。目标库显式重装，修改 schema 的授权不包含删除目标库。
- Admin `maintenance` 的 `database_install` 只接受无用户 relation 且无 `armi` namespace 的库：namespace 独立短事务建立，`0000` 原子安装其余内容。失败可留下空 namespace，不能留下业务表或前移 revision。普通启动只验证版本、摘要和精确 ACL，不自动安装/迁移或用超级用户掩盖漂移。
- 同一内部合同族只保留一个当前数字版本。升级同步生产者、消费者、DDL、配置、OpenAPI、生成代码、工具和测试，删除旧解析器、字段、双读双写及缺字段补默认值。第三方协议遵守其自身合同。
- 人工业务/部署配置集中在 `configs/`，环境配置也使用严格 YAML；Codex MCP TOML、OpenAPI、JSON Schema、lock 与 wire 保留要求的格式。Runtime 按仓库默认 → `environment.yaml` → 登记的 `ARMI_*` 合并，拒绝 unknown/extra、错误类型和敏感明文。Secret 只用 scoped locator。
- 接线由 Python composition root 定义，不维护重复清单或把接线摘要当成主体连续性。JSON 使用 UTF-8、2 空格、末尾换行；只在真实消费者需要时使用摘要或 RFC 8785。

## 5. 目标环境与外部操作

本文件不预授权 Docker、持久服务、真实 Provider、账号、设备或付费调用。沿用会话中已明确授权的环境和动作范围；换环境、账号、凭据或生产资源时重新核对授权。

- 未经用户针对本次操作明确授权，不复制、打包或导出数据库、Artifact Store、环境配置或 secret 作为离线恢复制品。项目不提供此恢复功能；重装与删除目标数据需明确授权，不能先擅自备份再操作。
- 对外接口优先服务 Creator 委托的 Agent：交互使用 `armi` / `armi-mcp`，管理检查与调试使用 `armi-admin` / `armi-admin-mcp`。输入使用 `message send` 正式 intake 与稳定 idempotency key；代理来源由认证入口写入，不直写数据库、不伪造浏览器 session。Web 保留，界面操作与视觉验收才使用浏览器驱动。
  本地附件先经 `upload import` 或分块上传得到受治理引用，再显式接纳；上传完成不触发认知。`runtime_entrypoint` 是私有启动 worker，不承担业务或管理命令。私有主体快照另需 `subject_snapshot.private` 授权范围。
- 交互用例和操作合同位于 Runtime `application/`，HTTP、CLI、MCP 只适配传输，不经 HTTP handler 转接机器操作。重置与主体内容校正核验独立 Creator 绑定签发的一次性授权；普通代理不能签发或通过配置修改信任根。配置消费者仅在验证并实际采用后登记当前版本；读取文件或保存配置不等于生效。中断管理调用通过 `invocation reconcile` 核验，不以当前状态猜测历史成功或重放原效果。
- ARMI→Codex runner 与外部 Agent→ARMI MCP 隔离，不互相发现或继承 credential。Admin 支持显式绑定的 `active`、`development`、`system_test`、`acceptance`，采用独立 config、role、按需 pool 和 owner Admin ports；配置不能修改自己的管理授权。不暴露任意 SQL/Shell/Python。正式环境禁止故障注入；危险操作及主体内容校正需要具体授权。
- ARMI 的 Codex 委托使用官方 SDK/订阅 auth，按当前合同允许逐任务选择模型、reasoning 和内置 Web Search；这不指定开发仓库时的模型。Runner 只操作 manifest 的一次性 workspace，遵守路径边界，不访问 ARMI DB、Admin 或宿主 secret/配置；内容产出为 `result.md`，代码/文件产出经独立 validator 与 custody 副本核验。
- ARMI Web research 与 Codex 内置 Web Search 是独立只读链，后者不授予 shell 网络权限；结果先成为 Evidence/Opportunity，不直接写 Memory、Relationship 或回复。
- 项目当前未授予开源许可证，不擅自声明开源或复制不兼容源码/素材，保留研究来源和许可证记录。

## 6. 验证、文档与入口

按改动影响选择检查，完成条件满足后收尾；Fast/Release/System 不构成每次任务的固定流水线。公共合同、schema、依赖锁、生成器、composition 或启动变化要覆盖受影响消费者。使用项目受管工具，缺失时明确报告，不换未核对版本绕过门禁。

| 任务 | 入口与完成条件 |
|---|---|
| 工具链与质量检查 | Windows x86_64 / PowerShell 7，从仓库根运行。首次准备：`./tools/bootstrap_toolchain.ps1 -ApprovedOfficialDirect`，须有联网安装授权。定向：`./tools/quality.ps1 -Gate <ID>`；架构用 `ARC-SURFACE`，仓库卫生用 `SEC-REPOSITORY`。完整 gate 与依赖见 [tools/quality.py](tools/quality.py)。 |
| 扩大验证 | `./tools/quality.ps1` 为 Fast；`-Release` 增加构建与 wheel 隔离安装；`-System` 再增加隔离 PostgreSQL、固定 Chromium 与 Creator 系统旅程，不调用真实模型、Web、Codex、QQ 或设备。`-Gate`、`-Release`、`-System` 互斥；定向测试沿用脚本环境与 [pytest 配置](pyproject.toml)。 |
| 数据库变更 | 用获授权的真实 PostgreSQL 验证空库、唯一 `0000` 原子安装、head/identity/digests/ACL、重复 install 合同、注入失败后的业务表回滚与 revision 不前移，并核对残留空 namespace 和受影响 owner 主路径。 |
| Creator Web | `./tools/start_creator_web_dev.ps1 -EnvironmentRoot <环境根> -OpenBrowser` 连接已有 ready Runtime，Vite 固定 `127.0.0.1:5173`。视觉变更用真实页面验证受影响布局与交互，不以 mock 代替正式验收。 |
| 目标环境与 live | 安装、启动、重置按 [README.md](README.md) 和[运行手册](docs/05-运行与验证/01-安装、启动与维护.md)。声称真实 Creator 闭环可用，须在获授权后运行 [verify_live_creator_roundtrip.py](tools/verify_live_creator_roundtrip.py)，证明 cognition、Subject Commit、reply effect 核验、outbox 交付及非空回复 artifact。 |

文档沿用 [docs 索引](docs/README.md) 的目录职责：README 提供产品与快速入口，DESIGN 提供可提交实现总览，`docs/` 保存设计正文、运行证据和有来源的研究。只同步受影响内容，不新增路线图、阶段清单、临时审计或重复机器合同。Schema 变化从新 SQL 反算并同步 `docs/03-数据设计/` 字段快照。

文档使用简体中文、UTF-8、LF 和相对链接；检查链接、实现锚点及与机器合同的一致性，删除失效结论。纯文档改动不要求运行环境或 live 验证。区分代码存在、配置启用、环境就绪、外部可用与本轮端到端通过，历史性能记录保留日期和限制。

Git 提交与分支沿用全局规则；本地 `docs/` 变化单独报告，不强制加入提交。维护本文件时优先消除重复、歧义与失效事实，操作细节放回对应文档或工具，只把跨任务仍有价值的决策边界留在这里。
