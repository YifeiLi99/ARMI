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

项目目前处于 M0 候选收尾阶段，当前实现基线仍为 S001 5.7、schema v27。普通 `consider_creator_input` 只调用一次主模型，并使用紧凑的 `armi.creator-dialogue-candidate.v1`：模型只返回本轮决定、必要正文和可选 Experience；固定 identity、usage、subject、scene、版本、digest、basis 与 grant scope 由适配器和 Runtime 保管。普通对话不使用多模型流水线，也不让模型重复回显数据库合同。全新隔离 PostgreSQL 环境的真实回复闭环为 2.327 秒，其中方舟模型 1.774 秒。

S039 的 Creator→Codex 产品纵向 gate 已通过：正式 `codex-tasks` 输入经 ARMI 认知、Creator grant、Codex effect、官方 `openai-codex==0.144.4` SDK runner、独立 validator、result evidence 和第二次 T-03 收敛为唯一 private Experience。新任务可逐项选择 `gpt-5.6-sol/terra/luna`、思考级别和内置 Web Search；一次性 workspace 默认可操作，明确 forbidden paths 和禁止逃逸构成安全边界。纯内容任务由结构化 deliverable 落为 `result.md`，代码与文件任务按 task manifest 和独立 validator 核验。正式 Creator 链已经用 Luna、`max` 和 Web Search 完成实机验收，不再把组件级成功冒充产品闭环。

Admin MCP 保持 SDK 2.0.0、协议 `2026-07-28`、stdio 和 23 个静态工具。S033/S034 的 ARMI 网页证据 live gate 仍延至 M0 总验收，不能用 Codex Web Search 的成功替代。原 M0-S040—S043 不再单独实施，其必要检查并入 M0-S044—S046。S044 已从固定 revision 生成并核验不可变 M0 候选，下一施工入口为 M0-S045。Memory、Relationship 与 Activity owner 仍未激活，因此当前还不是发布版本。

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
Windows 服务，也不提供开机自启；正式安装和服务身份仍归 S045。

## 开发验证

日常迭代以改动相关的 `pytest` 和最终实机闭环为准，不在每次编辑后运行完整
质量门禁、完整 PostgreSQL 回归或双 clean-root。`tools/quality.ps1` 保留为稳定后
的提交/阶段验收入口。Runtime composition 只声明接缝与 Active binding；配置、
schema、migration、前端和策略资源由各自真实消费者验证，不再通过聚合摘要互相
触发 JSON 镜像更新。

## 关于学习与参考

这个项目就是我自己拿来学习和做实验的，不商用，也没打算假装所有东西都是我凭空想出来的。一路上我会看很多开源项目和论文，觉得好的设计就研究、吸收，再按 ARMI 的需要重新做。所以如果你看到某些思路眼熟，不用奇怪。

该标的来源我会标，该遵守的许可证也会遵守。如果有哪里漏掉了，提醒我补上就好。

## License

本项目暂未授予开源许可证。
