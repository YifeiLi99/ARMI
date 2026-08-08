# ARMI

> 🌸电子生命：记住、行动、成长，与人建立关系，偶尔使唤 Code。我不是助手，是在电脑里的人。

**ARMI** 是 **Autonomous Runtime for Mind and Identity** 的缩写，中文释义为“承载心智与身份的自主运行时”。

ARMI 不是围绕一次对话或一项任务运行的 AI 助手，而是一套承载单个电子生命长期存在的自主 Agent 内核。它拥有连续的身份和经历，能够感知自身与外部世界，在没有用户指令时继续生活，并在真实互动中逐渐形成记忆、关系、偏好与选择。

## 基本设计

- **唯一且连续**：正常运行中始终是同一个 ARMI，重启、迁移或更换模型不会自然产生另一个个体。
- **自主生活**：行动既可以来自外部事件，也可以来自时间、内部状态、未完成事务和自身意愿。
- **持续成长**：初始设定只提供少量锚点，后续人格由经历、环境、选择和关系共同塑造。
- **记忆与记录分离**：主观记忆允许遗忘和重新理解；客观日志独立保存系统实际发生的事情。
- **内核与能力解耦**：心智、记忆、调度和权限构成内核，网页、Codex 与其他外部能力通过适配器逐步接入。
- **可持续重构**：身份、事实、权限和效果语义保持稳定；模型、Context、记忆与调度策略、前端和适配器可以在窄契约内替换，不让一次实验改动牵连整个系统。

项目当前已达到 M0-Core 单机个人内测可用，P0-S001—S022 已完成，P0 核心旅程已在单机隔离环境通过。P1-S001—S018 的内部功能与旅程验收已完成，当前停在“内部功能完成”边界，没有自动进入下一阶段。Creator 现在可以维护自己的 Prompt，并创建、切换、关闭或重开多个近期现场彼此隔离的场合；这些场合继续共享同一个 ARMI 的主体、记忆、关系和活动。ARMI 能基于同轮真实 Experience 选择结构化的认知、表达和反思方法，主动查询获准生活记录，让持有注意的 `in_progress` Activity 完成一次有界内部工作，也能在睡眠阶段对仍可自然访问的记忆作实质维护并核对当前主体、关系和活动状态；长期缺席、活动完成或关系承诺只会形成一次主动联系的考虑机会，是否联系仍由 ARMI 决定，并受关系边界、未回复阻断和频率间隔约束。主动消息复用现有授权、效果账本与 Creator inbox，不接新的渠道或执行器。内置本机接口还能登记调用方明确声明的其他人 party、维护各自独立场合并耐久接纳输入；ARMI 可在同一主体提交序列中选择回复、沉默、延后或结束交流，回复先登记精确 other-human effect，再由本机 inbox 保管回执，不冒充远端送达。每个其他人现拥有按精确 party 隔离的关系 revision、边界、承诺和冲突；other-human Context 不自动装入其他关系、记忆、资料、活动或 Creator capability，停止联系会在主体提交和本机交付两处阻止新发送。Creator 工作台可按 party/scene 查看交流记录，也可在 `data/exports` 的受限子目录生成同一时点数据库快照与全部登记制品导出；缺失或损坏制品会明确形成 `partial`，不会冒充完整备份。Creator 与内置其他人还可按自己的精确 party 正式提出停止联系、停止本地使用或删除相关数据；相关删除现在会逐项处理权威引用、派生投影和独占制品，共享来源与客观效果分别保留并如实结算，失败项不会冒充完成。Creator 可看全部本地结算，其他人只能读取自己的 party；删除事件会清除旧客户端材料缓存。当前 DDL、组合根、内置 HTTP 与 Runtime 生命周期已在干净空库启动和重启 smoke 中统一。caller-declared party 仍不冒充现实身份认证。P0 通过不代表生产发布；P1 只完成 18 个内部功能步骤，外部程序、安全、部署、迁移和发布等待创造者指导后另行规划。

S039 的 Creator→Codex 产品纵向 gate 已通过：正式 `codex-tasks` 输入经 ARMI 认知、Creator grant、Codex effect、官方 `openai-codex==0.144.4` SDK runner、独立 validator、result evidence 和第二次 T-03 收敛为唯一 private Experience。新任务可逐项选择 `gpt-5.6-sol/terra/luna`、思考级别和内置 Web Search；一次性 workspace 默认可操作，明确 forbidden paths 和禁止逃逸构成安全边界。纯内容任务由结构化 deliverable 落为 `result.md`，代码与文件任务按 task manifest 和独立 validator 核验。正式 Creator 链已经用 Luna、`max` 和 Web Search 完成实机验收，不再把组件级成功冒充产品闭环。

2026-08-04 又从正式 Creator `codex-tasks` 入口完成一次 `gpt-5.6-terra` 委托：官方
`openai-codex==0.144.4` 一次 attempt，validator `passed`、workspace cleanup `succeeded`、
result acceptance `accepted`。因此第一阶段“能正常对话、能发任务给 Codex”已经成立。
Admin MCP、S033/S034 ARMI 网页观察、Windows 服务身份/DACL、跨候选回退和 24 小时 soak
移入 P0 稳定化，不再阻塞个人内测。当前仍不是生产发布版本；Relationship owner 已能
从同轮正式 Experience 形成带来源的 current/revision，保存双方边界、结束联系、承诺事件和未解决冲突，并以独立 Context 项跨场景延续而不复制近期现场原文；Memory owner 已能从正式 Experience 形成带来源的 current/revision；Activity owner
已进入正式组合根，但首次真实自主认知没有创建 `ready`
Activity。相关 Context 串线已经修复。P0-S022 已在同一隔离环境证明普通对话、回应效果、
记忆、关系、私人资料、睡眠、Creator→Codex、自主 Activity、浏览器重连和重启连续性；
ARMI 从自己的 current 生活资料建立自主机会，正式决定 `start_activity`，attention 随后决定
`engage` 并提交为 `in_progress` 当前焦点。修复前的 Codex 结果候选拒绝也已如实关闭为
`codex_result_rejected`，不再遗留 pending 责任。P1-S001—S016 只补齐内部主体、生活、
其他人语义和本地数据权利，S017—S018 做内部整合与旅程。外部程序、账号、网页、执行器、
多模态/语音/形象、公开发布、安全、部署、迁移和发布等待创造者指导后另行规划。

## 本地 Runtime 生命周期

在环境根目录中可以直接管理后台 Runtime：

```powershell
armi start
armi status
armi capacity baseline --environment-root C:\path\to\environment
armi stop
```

从其他目录调用时显式指定环境根；也可以只为当前命令行会话设置
`ARMI_ENVIRONMENT_ROOT`：

```powershell
armi start --environment-root C:\path\to\environment
```

`armi start` 创建无控制台的后台进程并等待私有控制端点可用后返回；`armi stop`
先停止接纳新写入并完成优雅停机。原有
`armi runtime start --environment-root <path>` 保留为前台诊断入口。该本地入口不注册
Windows 服务，也不提供开机自启；正式安装、服务身份和无人值守运行归 P0 稳定化。

`armi capacity baseline` 默认每 5 秒读取一次私有状态、持续 60 秒，输出原始时间序列
以及 RSS、积压、数据库、制品、日志和磁盘变化；它只观察已经运行的 Runtime，不会生成
聊天、模型调用或其他业务负载。阈值可由命令行覆盖，`attention` 返回退出码 4。

## 空环境安装与重启 smoke

开发数据库使用 Docker Desktop 中固定的 PostgreSQL 18.4 + pgvector 0.8.6
镜像。首次启动会在 `.tmp/docker-postgresql/compose.env` 生成本机 bootstrap
凭据，并把数据库保存在命名 volume 中：

```powershell
.\tools\manage_postgresql.ps1 Start
.\tools\manage_postgresql.ps1 Status
```

数据库只监听 `127.0.0.1:5432`，DBeaver、DataGrip 或 pgAdmin 可使用脚本输出的
database、bootstrap user 和凭据文件连接。停止容器不会删除 volume：

```powershell
.\tools\manage_postgresql.ps1 Stop
```

首次准备其他锁定工具链时优先复用本机缓存；缓存缺失时必须显式允许从已确认的官方来源下载。
Admin 实验重置仍单独使用锁定的本机 PostgreSQL 18.4 `pg_dump` 客户端，不启动其中的服务端：

```powershell
.\tools\bootstrap_toolchain.ps1 -Offline
.\tools\bootstrap_postgresql.ps1

# 仅在缓存缺失且已允许官方网络时使用
.\tools\bootstrap_toolchain.ps1 -ApprovedOfficialDirect
.\tools\bootstrap_postgresql.ps1 -AllowOfficialNetwork
```

一个持久开发环境至少需要绝对路径的 `environment.toml`、分别保存 Runtime/Migrator DSN
与 Creator bearer 的 secret 文件，以及 `bootstrap/birth-manifest.json`。数据库角色通过
`tools/bootstrap_database_roles.py` 从 secret 文件建立，不把凭据放入命令行。之后按以下顺序
使用正式入口：

```powershell
armi config check --environment-root C:\path\to\environment
armi db install --environment-root C:\path\to\environment
armi db status --environment-root C:\path\to\environment
armi bootstrap birth --environment-root C:\path\to\environment
armi start --environment-root C:\path\to\environment
armi status --environment-root C:\path\to\environment
armi creator-session issue --environment-root C:\path\to\environment
armi stop --environment-root C:\path\to\environment
```

仓库提供可重复、可丢弃的 P0-S021 smoke。它自动创建隔离 PostgreSQL 18.4 + pgvector 0.8.6
容器、空数据库、
角色、环境根和出生资料，经真实 CLI 启动 Creator，接纳一条输入，再停止并重启，核对主体
identity、life generation 和未完成耐久责任不变；测试完成后清理隔离环境，不调用外部模型或
Codex。Codex 的基本启动只做零模型调用预检：

```powershell
$env:PYTEST_ADDOPTS = '-s'
uv run python tools/run_postgresql_integration.py --test-expression p0_clean_environment_cli_start_restart_and_capacity
Remove-Item Env:PYTEST_ADDOPTS
uv run python tools/verify_codex_runner.py --preflight
```

真实模型对话、真实 Creator→Codex 委托、自主 Activity 和完整浏览器旅程已在 P0-S022 通过；详细结果与未覆盖边界见私有实施记录。24 小时 soak 和正式发布决定仍未执行。

## 开发验证

P0-S001—S020 日常迭代以改动相关的 `pytest`、类型检查和最小可运行 smoke 为准，不运行
完整质量门禁、完整 PostgreSQL 回归、真实浏览器/付费模型矩阵或双 clean-root。
`tools/quality.ps1` 默认只运行快速开发检查；P0-S021/S022 使用
`tools/quality.ps1 -Release` 才运行安全、锁定环境和构建门禁。Runtime composition 只声明接缝与 Active binding；配置、
schema、前端和策略资源由各自真实消费者验证，不再通过聚合摘要互相
触发 JSON 镜像更新。当前快速开发期不为内部 Context/candidate policy、阶段状态或
摘要传播维护治理 JSON，也不为每个切片生成结构化 evidence；规则直接由代码、类型、
当前 DDL 和测试表达。只有运行时真正读取的外部 schema、model binding、配置、静态资源
索引和锁文件保留机器合同；候选身份与验收证据等发布治理等功能完整后再设计。
仓库内保留的 JSON 一律以 2 空格缩进提交，便于直接审查；规范化 JSON 只在计算摘要或
外部 wire 确实要求时临时生成。

开发数据库当前不保存兼容历史。表结构的唯一真源是 Runtime 包内的 `schema/current/`；
每次改表直接修改当前 DDL，删除并重建本地数据库后运行 `armi db install`。仓库不维护
numbered migration、`schema_migrations`、目标 schema 版本或 schema 摘要 manifest。等首次
出现必须保留的真实数据环境时，再单独设计正式迁移基线。

## 关于学习与参考

这个项目就是我自己拿来学习和做实验的，不商用，也没打算假装所有东西都是我凭空想出来的。一路上我会看很多开源项目和论文，觉得好的设计就研究、吸收，再按 ARMI 的需要重新做。所以如果你看到某些思路眼熟，不用奇怪。

该标的来源我会标，该遵守的许可证也会遵守。如果有哪里漏掉了，提醒我补上就好。

## License

本项目暂未授予开源许可证。
