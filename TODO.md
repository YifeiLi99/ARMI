# ARMI 代码清理 TODO

> 2026-08-20 首轮静态审计；同日按用户要求进入自动修复。当前工作区改动均未提交。
>
> 当前结果：实时语音生产链、账本 owner、快答后的 appraisal-only 继任、恢复终结和组合根已补齐；确定不可达的历史写分支及一批孤立 API 已清理。需要权威数据库数据分布才能安全退出的兼容读路径仍保留，不能在没有环境根和迁移证据时猜测删除。
>
> 口径：
>
> - **确定**：仓库内生产代码没有运行消费者，或控制流可证明不可达。测试和 `__init__` 重导出不算生产消费者。
> - **兼容**：当前写路径已经收敛，但读路径仍接受历史结构。删除前必须先检查权威数据库中的实际版本分布。
> - **无头**：表、配置、适配器或 HTTP 面存在，但缺少能完成闭环的组合根接线、正式写入 owner 或可发现的首方入口。
> - 本次没有连接运行中的 ARMI、权威 PostgreSQL、真实语音/模型 provider 或外部调用者，因此外部约定消费只能标为“待确认”，不能凭静态搜索直接删除。

## P0：实时语音是一条确定未接线的整链

- [x] 选择并完成“补齐正式闭环”；没有删除已有语音实现。
  - `apps/armi-runtime/src/armi_runtime/composition/runtime.py:302` 把 `live_voice_service` 初始化为 `None`，全仓没有赋值；控制面只能在 `:1547` 返回 `VOICE_PIPELINE_UNAVAILABLE`。
  - `apps/armi-creator-web/src/features/maintenance/LiveVoiceCard.tsx:31` 也明确显示“实时语音链路尚未完成运行接线”。
  - `ArkResponsesFastModel`、`VolcStreamingAsr`、`VolcStreamingTts` 和 `LiveVoiceService` 只有定义及测试，没有生产组合根消费者：
    - `apps/armi-runtime/src/armi_runtime/adapters/voice/ark.py:12`
    - `apps/armi-runtime/src/armi_runtime/adapters/voice/volc.py:181`
    - `apps/armi-runtime/src/armi_runtime/adapters/voice/volc.py:291`
    - `modules/live-voice/src/armi_live_voice/service.py:28`
  - `configs/runtime.yaml`、Creator HTTP `/v1/voice/*`、设备枚举和前端卡片都已暴露，因此这是可达的“永远 unavailable”，不是尚未公开的内部草稿。
  - 基线已创建 `live_voice_sessions`、`live_voice_turns`、`live_voice_text_fragments`、`live_voice_provider_attempts`、`live_voice_playback_attempts` 并授予运行时写权限，但生产代码没有这些表的 session/turn/attempt 写入实现；目前只有 data-rights 读取和 recovery 更新。
- [x] 已补齐 PostgreSQL owner、session/turn/provider/playback 账本、正式 Creator intake、当前主体 context、SPEAK/SILENT appraisal-only 继任、WAIT 慢链、组合根、关闭与重启恢复，并增加定向测试。真实 provider、WASAPI 真机和真实 PostgreSQL gate 尚未获得环境/凭据证据，未声称通过。
- [ ] 如果暂不实现：同步移除语音配置、HTTP/前端假入口、未接线 provider/service、无消费者表及权限，并修正文档；正式数据库只能用新 Alembic revision 处理，不能改写冻结的 `0000`。

## P1：可直接进入删除批次的确定废代码

### 1. Cognition 中已经不可达的历史写分支

- [x] 删除 `modules/cognition/src/armi_cognition/_validator.py` 的 `_legacy_change_set_version` 计算。
  - 该局部变量全仓只出现一次，结果没有被读取。
  - 紧接着 `:1358` 无条件使用 `ACTIVE_CHANGE_SET_VERSION`（当前为 `armi.subject-change-set.v29`）。
- [x] 删除同一函数中只可能在旧 `change_set_version` 下执行的条件分支，并把当前 v29 写出收敛为单一路径。
  - `change_set_version == ACTIVE_CHANGE_SET_VERSION` 恒真。
  - 仅检查 `MEMORY_CHANGE_SET_VERSION`、`MATERIAL_CHANGE_SET_VERSION`、`PROMPT_CHANGE_SET_VERSION` 等旧版本的分支恒假。
  - 若仍需按 `source_version` 兼容历史候选，只保留真正影响 v29 结果的转换，不再模拟旧 change-set 写出路径。

### 2. Relationship 中只有测试消费的旧 v22 实现

- [x] 删除 `modules/relationship/src/armi_relationship/_domain.py` 及只保护它的测试。
  - `apply_boundary_operations`、`apply_fact_operations` 仅被 `modules/relationship/tests/test_lifecycle.py` 调用。
- [x] 删除 `modules/relationship/src/armi_relationship/_model_contract.py` 及只验证它的旧测试。
  - `RelationshipFactChangeV22`、`RelationshipBoundaryChangeV22`、`RelationshipChangeV22` 没有生产调用者。
  - 当前生产链使用 `CandidateRelationshipDraft`、`_codec.py`、`_application.py`，候选模型合同由 cognition 持有。

### 3. Runtime / composition 中无生产消费者的残留

- [x] 已清理本节列出的内部残留及重导出；没有发现仓库内生产消费者：
  - `composition/birth.py:227`：`run_birth_transaction`；当前入口 `execute_birth_with_conninfo` 直接调用正式 birth transaction。
  - `composition/database.py:568`：`inspect_creator_party_id`；已被返回完整上下文的 `inspect_creator_context` 取代。
  - `composition/configuration/loader.py:311`：`environment_override_manifest`；只有两层重导出，没有消费者。
  - `composition/configuration/loader.py:322`：`sha256_hex`；只有定义，没有消费者。
  - `composition/audit.py:13`：`AuditQueryGateway`；文件自身写明“never wired to product surfaces”，只有集成测试使用。
  - `adapters/persistence/role_policy.py:367`：`RoleBoundConnectionPool`；只有集成测试使用，Runtime 走当前 UoW pool。
  - `packages/armi-postgresql-contract/src/armi_postgresql_contract/catalog_fingerprint.py:222`：`legacy_database_catalog_digest`；只有定义和重导出，当前恢复/管理路径使用 `database_catalog_digest`。

### 4. 冻结但未激活、且无消费者的 schema helper

- [x] 删除 `candidate_v5_schema`。
- [x] 删除 `dialogue_model_output_schema` 及仅由它使用的 schema 注释剥离器。
- [x] 删除 Prompt 的 `decode_legacy` 两层孤立入口。

### 5. 模块 API、bootstrap 和通用 contract 中的孤立符号

- [x] 按模块删除下列“定义/重导出/测试存在，但生产代码无消费者”的符号；本轮已完成 attention、capability、codex、cognition、effect、interaction、mood、live-voice、armi-kernel 和 armi-runtime-foundation 中可由仓库证据确认的孤立项。`AttemptOutcome` 因新语音账本已成为正式生产合同，明确保留。`SceneId`、`PageRequest`/`Page` 属于注明为 frozen public transport v1 的机器合同，仅凭仓库内无消费者不足以授权破坏性变更，因此留在待外部消费证据确认项：
  - attention：`LifeOpportunitySourceSnapshot`、`require_life_token`、`bootstrap_opportunity_operation`、`bootstrap_opportunity_context`。
  - capability：`CapabilityAvailability`、`CapabilityId`、`GrantMatcher`。
  - codex：`CodexArtifactCatalogPort`。
  - cognition：`HotDialogueAggregateOutcome`。
  - effect：`dispatch_cancellation_reason`、`PolicyDecisionOutcome`、`EffectSettlement`、`EffectAttemptState`、`EffectAttemptResult`、`EffectRegistrationPort`、`bootstrap_effect_dispatch_boundary`。
  - interaction：`bootstrap_interaction_cognition`。
  - mood：`AffectiveEvent`。
  - live-voice：`AttemptOutcome`、`BoundedAudioQueue`、`speech_chunks`；后两者只有测试使用，`LiveVoiceService` 自己没有使用它们。
  - armi-kernel：已删除 `BirthPort`、`CognitiveEpisodeStatus`、`RecoveryPort`、`SubjectCommitPort`、`UnitOfWork`、`classify_cas_rows`；`SceneId`、通用 `PageRequest`/`Page` 属于 frozen transport v1，保留待外部消费证据确认。
  - armi-runtime-foundation：`PostgreSQLAdminAuthorityLease`。
- [x] 删除后已用全仓引用搜索、ruff、受影响模块测试、架构/边界测试确认没有恢复旧入口。当前环境没有安装项目未声明的 pyright，不能把该项伪报为通过；全量非 PostgreSQL pytest 已覆盖导入与运行合同。

## P1：需要数据迁移后退出的兼容链路

### 1. Mood v1 双读和无写入旧表

- [ ] 先在唯一权威数据库盘点 `armi.mood_affective_events` 行数、时间范围、主体和与当前 appraisal 事件的重叠关系；没有数据也要留下可核验结果。
- [ ] 若存在旧数据，用新的 Alembic revision 一次性归一到当前 `mood_appraisal_events`/当前 mood 状态语义；验证幂等、失败回滚和数据保持。
- [ ] 迁移完成后删除：
  - `modules/mood/src/armi_mood/_postgresql.py:117-126` 的 `legacy_rows` 双读。
  - `_postgresql.py:383` 与 `_domain.py:63,144` 对 `cpm-fuzzy.v1` 的接受。
  - `mood_affective_events` 的 data-rights 分支、表、索引、外键和运行时 `INSERT` 权限。
- [ ] 收敛标准：生产只写 `mood_appraisal_events`（当前已经如此），也只从当前事件模型恢复 mood；Alembic head 对应的当前 schema 不再携带没有当前写路径的历史表。冻结的 `0000` 不回改。

### 2. Cognition / Subject State 的多代持久合同网

- [ ] 在删除任何 parser 前，先对权威表做版本分布盘点，至少覆盖：model attempt 输出、candidate、subject change set、subject state/mind、Creator dialogue、other-human dialogue，以及仍可能引用这些 payload 的 audit/data-rights 记录。
- [ ] 为每个实际存在的历史版本决定以下唯一结果之一：
  - 必须永久原样审计读取：隔离到明确的 archive/audit codec，不进入当前写路径。
  - 仍被正常运行读取：用一次性 revision/归一化任务升级到当前合同，并设退出条件。
  - 数据不存在：直接删除兼容 parser、常量、schema 和测试。
- [ ] 重点清理面：
  - `_change_set_codec.py:171-200` 同时接受 `armi.subject-change-set.v1` 到 `v29`，并为历史 relationship fact 合成 ID。
  - `_dialogue_contract.py` 保留 Creator dialogue candidate `v5-v20`，当前是 `v21/v22`。
  - `_other_human_contract.py` 保留 other-human candidate `v1/v2/v3/v5`，当前是 `v6`。
  - `_model_contract.py` 保留 cognition candidate `v3 -> v4` 转换及 `v4/v5/v6`，当前是 `v7`。
  - cognition 与 subject-state 仍接受 `armi.mind.v1`，当前是 `armi.mind.v2`。
- [ ] 收敛标准：当前生成器只产生当前版本；正常运行读路径只接受当前版本；确需保留的旧 payload 只能通过明确的历史审计读取边界访问，不能继续扩大业务 validator。

### 3. Codex `allowed_paths` 旧语义

- [ ] 盘点未完成和需恢复的 Codex task manifest 中非空 `allowed_paths` 的数量。
  - 当前任务生成固定写出 `"allowed_paths": []`（`modules/codex/src/armi_codex/_application.py:765`）。
  - `_delegation_contract.py:113` 和 `_workspace.py:125-129` 仍保留“非空 allow-list 仅供 legacy task”的校验路径。
- [ ] 若没有仍需恢复的旧 task，删除非空 allow-list 兼容语义并从当前合同移除该字段；若有，先归一或让这些任务终结，再删除。不要把旧字段永久保留在新 task manifest。

## P2：需要产品决定的无头入口

### 1. Runtime-local other-human 写入与数据权利接口不可发现

- [x] 已明确 `creator_routes_local_other_humans.py` 是 caller-declared 本地其他人边界，并补上 `armi other-human` 首方 CLI。六个 HTTP 路由继续 `include_in_schema=False`，不会混入 Creator 公共 OpenAPI；CLI 通过带本机 token 的 Runtime 私有控制协议调用相同 owner，不直写数据库。
  - 注册 party。
  - 更新 scene。
  - 写入 message。
  - 创建、列表和读取 data-rights order。
- [x] 已提供 party 注册、scene 开关、message 接纳、data-rights order 创建/列表/详情的 CLI；message 与 order 创建支持显式稳定幂等键，省略时只为单次交互生成本机键。Runtime control descriptor/token/instance identity 负责本机授权，并新增 CLI 与 control 转发测试。

### 2. Operational audit gateway 没有产品入口

- [x] 删除未接线的 `composition/audit.py` gateway；保留并直接测试正式 `AuditEventRepository` 读取边界。

## P3：误导性残留，不是废链

- [x] 修正 Web observation 的过期 docstring：
  - `_provider_contract.py:1` 称自身为 “inactive”。
  - `_evidence_postgresql.py:63` 称 admission/evidence path 为 “inactive”。
  - 实际上 `composition/runtime.py:980-1003` 会在 `web.enabled` 时组合并打开 `WebSearchPipeline`/research pipeline，随后启动 worker；不能据此删除 Web 链。

## 删除前后统一验收

- [x] 删除前已重新跑仓库内生产引用搜索，区分定义、重导出、测试、动态注册和真实运行消费者。
- [ ] 涉及持久合同/表的项，必须先拿到权威数据库的数据分布证据；本 TODO 不能替代迁移证据。
- [ ] 每个清理批次只覆盖一个独立责任，删除源码、重导出、测试、配置、接线、schema 权限和失效文档，不留同名旧路径。
- [x] 最小验证：ruff、前端 lint/typecheck、受影响模块测试、架构/边界检查均通过；pyright 未安装且不在项目依赖中，已明确记录为未运行。
- [ ] 数据库清理按项目规则验证空库 `0000 -> 唯一 head`，以及已有库 revision 的前态、执行、后态、重复执行、失败不前移和回滚数据保持。

## 本次已排除的常见误报

- FastAPI 装饰器注册的 route function、MCP tool 注册函数和 OpenAPI schema callback 不能仅凭静态工具的“unused function”提示删除。
- Web observation 的 `S034` provider/evidence 代码有真实组合根和 worker 消费，只是默认可关闭且注释过期。
- durable work kind 静态核对未发现明显“只有 producer 没有 consumer”或“只有 consumer 没有 producer”的孤儿种类。
- `capabilities` 没有普通运行时写入是静态目录/seed 的预期行为；不能与 `mood_affective_events` 这种已被新写路径替代的旧表等同。
