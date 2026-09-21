# Jev 隔离试验入口

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

## 官方依据

- [HTTP API 与 Noul 返回](https://docs.typesafe.ai/api)：Bearer Key，`state/model/questions`，`answers/usage`。
- [模型与价格](https://docs.typesafe.ai/models)：2026-09-21 核对 Jev 1.13.0，输入 $0.042/百万 tokens，输出免费。
- [已知局限](https://docs.typesafe.ai/model-jaggedness/jev-1.13)：中文、上下文干扰、隐含条件和概率一致性须独立检验。

此工具的成功响应只证明隔离 API 调用与所测场景结果，不证明 ARMI 正式接入或生产行为已经验证。
