"""Run the fixed Chinese semantic-recall quality set against the local model."""

# ruff: noqa: RUF001

from __future__ import annotations

import argparse
import asyncio
import json
import math
import selectors
from pathlib import Path

from armi_context.api import load_embedding_binding
from armi_runtime.adapters.model.local_embedding import LocalLlamaCppEmbeddingAdapter
from armi_runtime.composition.config_assets import runtime_config_path
from armi_runtime.composition.semantic_recall_process import (
    SemanticRecallProcessManager,
)

_CASES = (
    (
        "团团是一只橘猫，吃三文鱼会过敏。",
        ("那只橘猫不能吃什么", "团团的忌口", "猫咪对哪种鱼过敏"),
    ),
    (
        "主人偏爱埃塞俄比亚浅烘咖啡，手冲水温九十二度。",
        ("主人爱喝哪种咖啡", "手冲应该用多少度的水", "咖啡豆偏好是什么"),
    ),
    (
        "我们的纪念日是五月二十日。",
        ("什么时候是纪念日", "5月20日有什么意义", "我们要庆祝的日子"),
    ),
    (
        "极光计划的内部代号是 Aurora-17。",
        ("极光项目代号", "Aurora-17 指什么", "那个十七号计划叫什么"),
    ),
    (
        "下次旅行想去冰岛看极光，避免红眼航班。",
        ("下一趟旅行目的地", "不想坐哪类航班", "想去哪里看北极光"),
    ),
    (
        "书房路由器管理地址是 192.168.50.1。",
        ("书房网络设备地址", "192.168.50.1 是什么", "路由器后台 IP"),
    ),
    (
        "周三晚上固定练习四十五分钟钢琴。",
        ("钢琴安排在什么时候", "周三晚上的固定活动", "每次练琴多久"),
    ),
    (
        "主人不喜欢香菜，但可以接受欧芹。",
        ("主人不吃哪种香草", "香菜和欧芹的偏好", "哪种绿色配菜会被拒绝"),
    ),
    (
        "紧急联系人是林晓，电话尾号 7319。",
        ("紧急联系人叫什么", "林晓的电话尾号", "7319 对应谁"),
    ),
    (
        "生日蛋糕要低糖，不放芒果，使用蓝莓装饰。",
        ("生日蛋糕不能放什么", "蛋糕装饰用哪种水果", "低糖甜点要求"),
    ),
    (
        "车辆保养每一万公里一次，下次里程是 48000。",
        ("汽车多久保养", "下次保养里程", "48000 代表什么"),
    ),
    (
        "常用开发分支前缀是 codex/，提交说明使用中文。",
        ("代码分支前缀", "提交信息用什么语言", "codex 斜杠的用途"),
    ),
    (
        "卧室空调睡眠温度设为二十四度，风速最低。",
        ("睡觉时空调几度", "卧室夜间风速", "睡眠环境温度偏好"),
    ),
    (
        "每月十五号给绿萝施肥，冬季暂停。",
        ("绿萝哪天施肥", "冬天是否继续施肥", "植物每月养护安排"),
    ),
    (
        "牙医预约在九月三日上午十点半。",
        ("牙医什么时候", "九月三日的安排", "上午十点半要去哪里"),
    ),
    (
        "NAS 名称是 MoonVault，备份窗口从凌晨两点开始。",
        ("家里存储设备叫什么", "MoonVault 的备份时间", "凌晨两点开始什么任务"),
    ),
    (
        "跑步鞋穿四十二码，宽楦，避免碳板。",
        ("跑鞋尺码", "鞋楦偏好", "不想要哪种跑鞋结构"),
    ),
    (
        "电影清单优先科幻片，暂时不看恐怖片。",
        ("最近想看什么类型电影", "暂时避开什么影片", "观影类型偏好"),
    ),
    (
        "药箱里的布洛芬有效期到 2027-11。",
        ("布洛芬什么时候过期", "2027-11 对应哪件物品", "药箱止痛药有效期"),
    ),
    (
        "会议室预订名称是 Nebula，门禁临时码 6048。",
        ("会议室预订名", "Nebula 的门禁码", "6048 用在哪里"),
    ),
)

_NEGATIVES = (
    "今天国际金价是多少",
    "解释量子色动力学",
    "推荐一款最新手机",
    "巴西国家队昨晚比分",
    "如何制作陶瓷釉料",
    "火星大气主要成分",
    "写一首关于海浪的诗",
    "查询上海实时降雨",
    "介绍古罗马元老院",
    "计算木星逃逸速度",
)


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True)) / math.sqrt(
        sum(a * a for a in left) * sum(b * b for b in right)
    )


async def _evaluate(environment_root: Path) -> dict[str, object]:
    endpoint = SemanticRecallProcessManager(environment_root).endpoint()
    adapter = LocalLlamaCppEmbeddingAdapter(
        binding=load_embedding_binding(runtime_config_path("model-bindings.yaml")),
        base_url=endpoint.base_url,
        api_key=endpoint.api_key,
    )
    documents: list[tuple[float, ...]] = []
    texts = tuple(item[0] for item in _CASES)
    for offset in range(0, len(texts), 8):
        documents.extend(
            response.vector
            for response in await adapter.embed_documents(texts[offset : offset + 8])
        )
    positive_rankings: list[tuple[int, list[tuple[int, float]]]] = []
    for expected, (_document, queries) in enumerate(_CASES):
        for query in queries:
            vector = (await adapter.embed_query(query)).vector
            ranked = sorted(
                (
                    (index, _cosine(vector, document))
                    for index, document in enumerate(documents)
                ),
                key=lambda item: (-item[1], item[0]),
            )
            positive_rankings.append((expected, ranked))
    negative_maxima: list[float] = []
    for query in _NEGATIVES:
        vector = (await adapter.embed_query(query)).vector
        negative_maxima.append(max(_cosine(vector, document) for document in documents))
    grid: list[dict[str, float]] = []
    for threshold in (0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60):
        hits = sum(
            expected in [index for index, score in ranked if score >= threshold][:6]
            for expected, ranked in positive_rankings
        )
        false_recalls = sum(score >= threshold for score in negative_maxima)
        grid.append(
            {
                "threshold": threshold,
                "recall_at_6": round(hits / len(positive_rankings), 4),
                "negative_false_recall_rate": round(false_recalls / len(_NEGATIVES), 4),
            }
        )
    eligible = [item for item in grid if item["negative_false_recall_rate"] <= 0.1]
    selected = max(
        eligible,
        key=lambda item: (item["recall_at_6"], item["threshold"]),
    )
    return {
        "positive_samples": len(positive_rankings),
        "negative_samples": len(_NEGATIVES),
        "binding_dense_threshold": adapter.binding.dense_min_similarity,
        "selected": selected,
        "grid": grid,
        "passed": selected["threshold"] == adapter.binding.dense_min_similarity
        and selected["recall_at_6"] >= 0.9,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment-root", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(
        _evaluate(args.environment_root.resolve(strict=True)),
        loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
