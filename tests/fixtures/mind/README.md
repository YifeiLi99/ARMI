# Mind 已验证对话回归数据

这些是2026-09-22隔离Jev实验的40个合成对话及实际返回，供
`tests/integration/test_mind_recorded_dialogues.py` 离线消费。生产Runtime不读取本目录。

| 文件 | 来源实验 | 场景数 |
| --- | --- | --- |
| original.json | mind-old-regression3-20260922 | 10 |
| mixed.json | mind-new-a5-20260922 | 10 |
| continuous.json | mind-new-b4-20260922 | 10 |
| boundaries.json | mind-new-c4-20260922 | 10 |

`case`保存原对话、合成来源及调用前冻结的预期，`response`保存实际Jev返回，
包括choice、confidence、probabilities与usage，没有重新生成概率或修改答案。
连续批的同对象事件依序更新状态；所有测试不访问网络、不读取凭据、不写主体数据。

`validated_questions.json`保存最终实际送给Jev的完整18题请求片段。
测试从正式Cognition共享入口取题逐项比较，以防生产题库偏离已验证版本。
提示语义变化时应先完成相应实验，再更新该片段；不能只从当前代码生成新快照来消除失败。
数值与资格预期按需求核对，不因代码结果变化就跟随改写。

运行 `./tools/test.ps1 -Group mind`，或定向运行上述pytest文件。
该测试会被全仓代码测试自动收集。它证明记录可被当前代码正确消费、状态轨迹符合预期，
不证明未来Jev调用仍会给出相同答案，也不替代真实效果验收。

完整失败历史和费用仍保留在本地实验目录与设计报告；本目录只保存回归所需的数据，
不得把它的成功样本集称作首次测试准确率。源头说明见
[DESIGN](../../../DESIGN.md#mind-提示词独立验证)。
