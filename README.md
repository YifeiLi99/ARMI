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

项目当前已达到 M0-Core 单机个人内测可用；P0-S001—S009 的 Activity、注意、Creator 只读闭环、睡眠维护、主观记忆演进与精确生活查询已经落地，当前按功能优先模式推进 P0-S010。普通 `consider_creator_input` 仍只调用一次主模型：模型返回本轮决定、必要正文、可选 Experience，以及最多一个引用当前 Context 的记忆变化。Runtime 绑定 memory head、来源、版本和权限；淡忘或遗忘只改变自然可得性，原 Experience 与历史 revision 保留。精确查询明确标记为本次取得的记录证据，不会把已经遗忘的内容伪装成自然回忆。2026-08-04 的当前环境实测 reply effect 为 `completed/verified`，ARMI 回复“可以啦，我们现在就在正常对话中。”

S039 的 Creator→Codex 产品纵向 gate 已通过：正式 `codex-tasks` 输入经 ARMI 认知、Creator grant、Codex effect、官方 `openai-codex==0.144.4` SDK runner、独立 validator、result evidence 和第二次 T-03 收敛为唯一 private Experience。新任务可逐项选择 `gpt-5.6-sol/terra/luna`、思考级别和内置 Web Search；一次性 workspace 默认可操作，明确 forbidden paths 和禁止逃逸构成安全边界。纯内容任务由结构化 deliverable 落为 `result.md`，代码与文件任务按 task manifest 和独立 validator 核验。正式 Creator 链已经用 Luna、`max` 和 Web Search 完成实机验收，不再把组件级成功冒充产品闭环。

2026-08-04 又从正式 Creator `codex-tasks` 入口完成一次 `gpt-5.6-terra` 委托：官方
`openai-codex==0.144.4` 一次 attempt，validator `passed`、workspace cleanup `succeeded`、
result acceptance `accepted`。因此第一阶段“能正常对话、能发任务给 Codex”已经成立。
Admin MCP、S033/S034 ARMI 网页观察、Windows 服务身份/DACL、跨候选回退和 24 小时 soak
移入 P0 稳定化，不再阻塞个人内测。当前仍不是生产发布版本；Relationship owner 尚未
激活。Memory owner 已能从正式 Experience 形成带来源的 current/revision；Activity owner
已进入正式组合根，但首次真实自主认知没有创建 `ready`
Activity。相关 Context 串线已经修复；历史联合验收结果保留到 P0-S021/S022 集中复验，
不再阻塞后续功能开发。P0-S001—P0-S009 按功能实现完成，当前施工入口为 P0-S010。

## 本地 Runtime 生命周期

在环境根目录中可以直接管理后台 Runtime：

```powershell
armi start
armi status
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
