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

项目目前处于从零重建的实验阶段，当前设计基线为 S001 5.7、schema v27。普通 `consider_creator_input` 不再让通用 candidate v7 承担整套权威数据库合同，而是单次调用紧凑的 `armi.creator-dialogue-candidate.v1`：模型只直接返回顶层 `kind`、必要正文和可选 Experience，不回传固定协议版本、解释理由或权威身份；模型/请求 identity 与 usage 由适配器单独保管。subject、scene、Creator、base、版本、digest、basis 和 grant scope 全部由 Runtime 从冻结 Context 确定性绑定，再进入原有 validation、T-03、grant/effect 与审计链。Codex task/result 和未来网页证据仍使用 v7，不把对话优化误扩成多模型或万能编排。全新隔离 PostgreSQL 环境的真实回复闭环为 2.327 秒，其中方舟模型 1.774 秒、3,079 输入 token、51 输出 token，最终形成 `completed/verified` effect 和 Creator inbox 正文；此前基线为 8.935 秒、模型 8.354 秒。提交后定向唤醒仍只传递“数据库可能有责任”的信号，1 秒轮询继续承担丢失通知和重启恢复兜底。S039 的早期 gate 已证明内部 task source、`doubao-seed-evolving`、grant/effect、`gpt-5.6-sol` runner、validator 和第二次认知分别成立，但复核发现它没有提供 Creator 可直接使用的任务入口，且 runner 仍以固定 conformance marker 作为交付；该结论已被纠正。当前实现增加显式 Creator `codex-tasks` 接纳、一般 `result.md` validator 和含真实交付物的 result evidence，完整产品纵向 gate 通过前不再把组件拼接冒充人类可用闭环。Codex 继续使用官方 `openai-codex==0.144.4` Python SDK、同版随包 runtime、Windows `unelevated/workspace-write`、临时认证、ephemeral thread、Job Object 和独立结果校验，不接触用户真实仓库，也不把 `workspace-write` 冒充同一 Windows 用户下的文件读取隔离，后者归 S045 的服务身份与 DACL。Admin MCP 保持 SDK 2.0.0、协议 `2026-07-28`、stdio 和 23 个静态工具。S033/S034 正式联网验收仍延至 M0 总验收，`M0-SEAM-WEB.active_binding` 为空；Memory、Relationship 与 Activity owner 仍未激活，S040—S046 尚未完成，因此还不是发布版本。

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
