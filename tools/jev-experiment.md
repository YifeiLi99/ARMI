# Jev 隔离试验入口

## 仅评价事实：提示与题型对照

`experiment_jev_facts.py` 不调用心理算法、不生成情绪、不写 Mood。每个合成输入在同一请求内比较正式题目的相关子集、简短中文题目、英文题目，并附加 Score/Noul 探针。问题独立，彼此答案不会进入其他问题；一次请求无隐藏重试。候选提示保存在实验工具内，尚未替换正式题库。

```powershell
.\.venv\Scripts\python.exe tools/experiment_jev_facts.py --config configs/jev-facts-experiment.yaml --output .tmp/jev-facts-preview
.\.venv\Scripts\python.exe tools/experiment_jev_facts.py --config configs/jev-facts-experiment.yaml --output .tmp/jev-facts-live --live
```

输出目录必须是新目录。默认离线，不读凭据；`--live` 沿用下述隔离 Jev 实验凭据。预期不发送给 Provider。Choice 校验原始选项及概率，Score 校验等级、分布与加权值，Noul 保留其概率；证据是否充分另作独立 Choice，不将 Score 的数字当成有证据的事实。无效单项保留并标记，网络或顶层合同失败结束本次批次。所有探针都只记录，不用于计算心情。详细研究与结果见本地 `docs/06-实验记录/Jev/08-Jev事实评价提示与题型对照.md`。

背景语言对照使用 `--context-language zh` 或 `--context-language en`，两组都只发送相同的四个英文 Choice 问题，分别读取 `context` 或人工核对的 `context_en`；`scene` 中文原话逐字保留，不启动翻译模型。现成双语输入是 `configs/jev-mood-generalization-experiment.yaml`。例如：

```powershell
.\.venv\Scripts\python.exe tools/experiment_jev_facts.py --config configs/jev-mood-generalization-experiment.yaml --context-language en --output .tmp/jev-facts-english-background --live
```

这是隔离实验选项，不自动翻译正式主体的经历或改写正式 Mood 题库。

中文评价对象对照使用 `--chinese-scoped`，与 `--context-language` 互斥。同一中文输入中比较原正式四题、上一版简短中文四题、按“主体／评价对象／问题”组织的中文四题，共 12 个 Choice，不含英文问题或 Score/Noul。新的独立检查输入为 `configs/jev-facts-chinese-transfer.yaml`；背景原话、预期均不因版本改变。候选规则将询问或计划表达与其提及的未来结果分开，尚未扩展到正式 Mood 的全部评价维度。

```powershell
.\.venv\Scripts\python.exe tools/experiment_jev_facts.py --config configs/jev-facts-chinese-transfer.yaml --chinese-scoped --output .tmp/jev-facts-chinese-scoped --live
```

从仓库根使用受管 `.venv/Scripts/python.exe` 运行 `tools/experiment_jev.py`。
此入口只发送 [配置](../configs/jev-experiment.yaml) 中的人工场景，不读取当前主体或安装版环境，
不接入 Runtime、不写数据库、不运行完整认知或发送消息。自主场景复用
`verify_live_autonomy_check.py` 的正式 Context 投影准备逻辑；记忆场景使用配置中的合成候选。

## 准备与运行

默认离线预览，不读取 Key、不联网：

```powershell
.\.venv\Scripts\python.exe tools/experiment_jev.py --output .tmp/jev-preview-01
```

获得 Key 后，在本机 `.armi/experiments/jev/api.key` 填入 Key 一行，UTF-8 编码。
该目录已由仓库 `.gitignore` 排除；这是本地明文秘密，勿提交或分享。
也可使用当前进程的 `TYPESAFE_API_KEY`；显式 `--key-file <路径>` 优先于环境变量，
环境变量优先于默认文件。Key 不接受命令行明文参数，不进入请求预览、结果或错误输出。

先运行开发场景（5 次请求），再运行独立评测；每次用新的输出目录：

```powershell
.\.venv\Scripts\python.exe tools/experiment_jev.py --live --suite autonomy --split development --output .tmp/jev-autonomy-01
.\.venv\Scripts\python.exe tools/experiment_jev.py --live --suite autonomy --split evaluation --output .tmp/jev-autonomy-eval-01
.\.venv\Scripts\python.exe tools/experiment_jev.py --live --suite memory --output .tmp/jev-memory-01
```

`--live` 会向 TypeSafe 官方 API 发送选定场景并产生真实调用。全部场景共 11 次请求，
每个自主场景一个 Noul，每个记忆场景在同一请求中分别判断各条记忆。
不自动重试，不跟随重定向，不读取系统代理环境变量；首次技术失败立即结束，返回非零退出码。
如所在网络无法直连，会明确失败，不能据此判断模型质量。
超时/网络错误保留 `outcome_unknown`，不能当作模型选择不行动；再次运行可能产生新的计费。

## 结果含义

输出目录保留配置快照、实际请求正文、HTTP 200 原始响应、每例结果和 `results.json`。
HTTP 错误不保存可能含敏感信息的响应正文或认证头。
接口固定为 `https://api.typesafe.ai/v1/systemone`，模型固定为 `jev-1.13.0`，
返回模型、问题集合、概率范围、usage 类型均须匹配合同。
本地请求上限为 24,000 UTF-8 字节，属于试验大小限制，不冒充 Provider tokenizer。

初始判断阈值为 0.5，概率大于等于阈值判为是；这是待校准试验参数。
`expected: null` 的模糊场景只记录结果，不参与正确率。
记忆结果同时给出概率排序，允许所有记忆均不相关。
只在 development 场景上调整问题与阈值，evaluation 用于后续检查，样本很小，不能宣称统计基准。
标签不会发给模型；对比主文本模型时应使用相同输入，主模型答案不自动作为标准答案。
当前入口只调用 Jev，不自动调用或付费运行其他 Provider。

耗时为客户端端到端时间；费用根据实际返回输入 tokens 和文档单价估算美元，
不是账单实付费用。无效响应和网络未知结果不计为已确认用量，也不宣称免费。
开发与评测结果按每例 split 分开保存，摘要数字仅用于快速检查。

## 三组记忆对照

`experiment_jev_memory.py` 使用独立合成场景，比较全部记忆直接交给 DeepSeek、
Jev 筛选后交给 DeepSeek、DeepSeek 自筛后回答。三个组的回答模型均为
`deepseek-flash`，关闭思考，temperature=0，JSON 输出；筛选阈值固定 0.5。
模型别名可能随供应商更新，原始返回模型标识保存在每次调用记录中。

```powershell
.\.venv\Scripts\python.exe tools/experiment_jev_memory.py --output .tmp/jev-memory-plan
.\.venv\Scripts\python.exe tools/experiment_jev_memory.py --live --environment-root <已授权环境根> --output .tmp/jev-memory-live
```

默认 20 个场景、3 次重复，共 180 次回答、60 次 Jev 和 240 次 DeepSeek 调用。
`--limit` 可限制场景数量。只通过所属环境的凭据 port 读取 DeepSeek 指定 locator，
Jev 使用前述实验 key；不读取主体数据、不启动 Runtime、不复制环境或凭据。
离线预览不读取凭据。真实调用须获得覆盖双方 Provider 的授权。

每个场景的三组共用相同输入顺序、问题与答案选项；重复时固定种子重排记忆和选项，
每个配对随机安排组顺序，最多三个配对并发。每次回答保留中文理由与引用记忆 ID。
主评分是预先固定的答案选项正确率，不能当作开放式回答质量或生产准确率。
筛选阶段不看答案选项或标准答案；标准答案不进入任何模型请求。

前 16 个场景附加 24 条无关记忆，后 4 个附加 96 条。96 条由同一套 24 条无关文本
循环生成，用于长度压力，不代表 96 种独立干扰。全部是开发者编写的合成场景，
例外、指代、更新、人物与虚构边界等均比较明确；不以这个小样本外推复杂生活表现。
不清除供应商缓存，记录缓存命中/未命中 tokens；三次重复并非三倍独立场景。

总耗时包含筛选及回答，费用同时计入两者。DeepSeek 按 2026-09-21 官方价格分别计算
全闲时和全忙时费用作为估算范围，不冒充实际账单；Jev 输出免费。
首次技术错误停止安排后续调用，允许已在途调用返回，不重试；无确认 usage 的调用
单独报告，不当作零费用。HTTP 错误正文及认证头不保存。

若中途停止，可显式指定 `--continue-from <上一次输出目录>` 与新的 `--output`。
配置和完整计划必须相同，仅执行从未尝试的项目，已失败项目也不重跑；
新目录汇集原有实验记录，历史失败继续进入总结果，退出码保持非零。

依据：[DeepSeek 价格](https://api-docs.deepseek.com/quick_start/pricing/)、
[思考模式](https://api-docs.deepseek.com/guides/thinking_mode/)。

## 新 Mood 连续事件实验

`tools/experiment_jev_mood.py` 使用 [16 个合成事件](../configs/jev-mood-experiment.yaml)，
复用正式 Jev 问题、严格返回合同、本地情绪规则与解析时间演化。每条连续链沿用前一步
实际返回形成的状态；参考标签只用于本地评分，不发送给模型。

```powershell
.\.venv\Scripts\python.exe tools/experiment_jev_mood.py --output .tmp/mood-preview
.\.venv\Scripts\python.exe tools/experiment_jev_mood.py --live --output .tmp/mood-live
```

Jev 凭据沿用上文实验槽，每事件一次请求，无重试和 Provider 切换；首次技术或合同失败
立即停止。离线不读取凭据。真实实验只发送合成内容，不读取安装版主体，不写数据库。
保存逐例请求、原响应、评价、情绪与 VA、未知项、延迟和 usage；失败响应中已确认用量
也计入估算。没有 usage 的请求单独列为未知，不能宣称免费。

结果分别报告语义评价错误、情绪规则结果及 Provider 合同错误。匹配通过率只对应人工
合成场景，不是模拟人类心理的准确率。费用是官方单价估算，不能替代实际账单。

旧明确场景及复杂语境对照保存在 `docs/06-实验记录/Jev/`；旧配置
`jev-mood-context-experiment.yaml` 属于历史协议，当前入口不支持旧字段或旧重评分命令。
新链路记录见 [实验记录](../docs/06-实验记录/Jev/04-新心情链路离线验证.md)。

## 官方依据

- [HTTP API 与 Noul 返回](https://docs.typesafe.ai/api)：Bearer Key，`state/model/questions`，`answers/usage`。
- [模型与价格](https://docs.typesafe.ai/models)：2026-09-21 核对 Jev 1.13.0，输入 $0.042/百万 tokens，输出免费。
- [已知局限](https://docs.typesafe.ai/model-jaggedness/jev-1.13)：中文、上下文干扰、隐含条件和概率一致性须独立检验。

此工具的成功响应只证明隔离 API 调用与所测场景结果，不证明 ARMI 正式接入或生产行为已经验证。
