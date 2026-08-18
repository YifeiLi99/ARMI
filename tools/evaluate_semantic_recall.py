"""Run the fixed Chinese semantic-recall quality set against the local model."""

# ruff: noqa: RUF001

from __future__ import annotations

import argparse
import asyncio
import json
import math
import selectors
import time
from pathlib import Path
from typing import Any

import psycopg
from armi_context.api import load_embedding_binding
from armi_kernel.application import CredentialPurpose
from armi_runtime.adapters.model.local_embedding import LocalLlamaCppEmbeddingAdapter
from armi_runtime.composition.config_assets import runtime_config_path
from armi_runtime.composition.environment import prepare_environment
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
    (
        "外婆的助听器电池型号是 A312，每周日晚上检查余量。",
        ("外婆助听器用什么电池", "A312 是哪件设备的", "周日晚上要检查什么"),
    ),
    (
        "工作室打印机叫 CloudInk，彩色墨盒编号 C-881。",
        ("工作室打印机叫什么", "C-881 是什么耗材", "CloudInk 的彩色墨盒编号"),
    ),
    (
        "给陈医生复诊的日期是十二月六日，带上最近三次血压记录。",
        ("什么时候去找陈医生复诊", "复诊要带哪些记录", "十二月六日有什么安排"),
    ),
    (
        "阳台薄荷每天早晨浇水，连续阴雨天暂停。",
        ("薄荷什么时候浇水", "什么天气不用浇薄荷", "阳台香草的养护习惯"),
    ),
    (
        "摄影硬盘的卷标是 NightHarbor，恢复密钥纸放在灰色文件夹。",
        ("摄影硬盘叫什么", "NightHarbor 的恢复密钥在哪", "灰色文件夹放了什么"),
    ),
    (
        "小顾喝拿铁只要燕麦奶，不加肉桂粉。",
        ("小顾的拿铁用什么奶", "谁不在咖啡里加肉桂", "给小顾点咖啡要避开什么"),
    ),
    (
        "租用储物柜编号 B-042，合同到期日是 2028-03-31。",
        ("储物柜编号是多少", "B-042 的合同何时到期", "2028年三月底到期的是什么"),
    ),
    (
        "周五例会使用链接别名 orbit-sync，会议提前五分钟进入。",
        ("周五例会链接别名", "orbit-sync 是什么", "例会应该提前多久进入"),
    ),
    (
        "给雪球买的猫砂必须无香，颗粒直径不超过两毫米。",
        ("雪球的猫砂能不能有香味", "猫砂颗粒尺寸要求", "给哪只猫买无香猫砂"),
    ),
    (
        "厨房净水器滤芯型号 RF-9，累计九个月更换一次。",
        ("净水器滤芯型号", "RF-9 多久换一次", "九个月要更换哪件东西"),
    ),
    (
        "夏季电费自动扣款卡尾号 2841，每月预留八百元。",
        ("电费从哪张卡扣", "2841 对应什么付款", "夏天每月要预留多少电费"),
    ),
    (
        "阿岚的英文名拼作 Arlen，不是 Allen。",
        ("阿岚英文名怎么拼", "Arlen 指的是谁", "哪个英文拼法是错的"),
    ),
    (
        "蓝门诊所的停车入口在北侧，导航搜索 Gate-N2。",
        ("蓝门诊所从哪边停车", "Gate-N2 用来导航到哪里", "诊所停车导航词"),
    ),
    (
        "项目账本只在每月最后一个工作日归档，文件名以 ledger-z 开头。",
        ("项目账本什么时候归档", "账本文件名前缀", "ledger-z 是什么文件"),
    ),
    (
        "客厅投影仪的 HDMI 2 接游戏机，HDMI 1 留给电视盒。",
        ("游戏机接投影仪哪个口", "HDMI 1 接什么", "电视盒使用哪个接口"),
    ),
    (
        "雨伞维修取件码是 RAIN-530，取件点晚上九点关门。",
        ("雨伞维修取件码", "RAIN-530 去哪里用", "取件点几点关门"),
    ),
    (
        "爷爷的围棋课在文化馆三楼 307 室，每隔周六上课。",
        ("爷爷在哪里上围棋课", "307 室是什么课程", "围棋课多久一次"),
    ),
    (
        "烘焙用电子秤校准砝码是五百克，编号 WT-500C。",
        ("电子秤用多重砝码校准", "WT-500C 是什么", "烘焙秤校准编号"),
    ),
    (
        "露营炉只能使用丁烷罐，仓库里那箱丙烷罐不要拿。",
        ("露营炉用哪种燃料", "哪箱燃气不能拿", "为什么不要带丙烷罐"),
    ),
    (
        "送给苏老师的书要寄到东湖校区收发室，备注编号 T-19。",
        ("苏老师的书寄到哪里", "T-19 是什么备注", "东湖校区收发室要收什么"),
    ),
)

_NEGATIVE_TOPICS = (
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
    "说明拜占庭税制",
    "分析深海热泉生态",
    "介绍量子霍尔效应",
    "比较两种火箭燃料",
    "讲解珊瑚白化原因",
    "推导傅里叶变换",
    "介绍玛雅历法",
    "解释恒星核聚变",
    "说明冰川地貌形成",
    "设计一座公共图书馆",
)


def _positive_queries(queries: tuple[str, str, str]) -> tuple[str, ...]:
    return (
        *queries,
        f"你还记得{queries[0]}吗",
        f"帮我回想一下：{queries[1]}",
    )


_NEGATIVES = tuple(
    variant
    for topic in _NEGATIVE_TOPICS
    for variant in (
        topic,
        f"请简单{topic}",
        f"我想了解：{topic}",
        f"能不能详细{topic}",
        f"关于这个问题，请{topic}",
    )
)


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True)) / math.sqrt(
        sum(a * a for a in left) * sum(b * b for b in right)
    )


def _database_conninfo(environment_root: Path) -> str:
    prepared = prepare_environment(
        environment_root,
        credential_scope={"database.benchmark": "database.runtime"},
    )
    locator = prepared.effective.config.secret_locators["database.runtime"]
    with prepared.credential_port.resolve(
        locator, CredentialPurpose("database.benchmark")
    ) as handle:
        return handle.consume(lambda value: bytes(value).decode("utf-8"))


def _hybrid_ranking(
    connection: psycopg.Connection[Any],
    query: str,
    vector: tuple[float, ...],
    documents: list[tuple[float, ...]],
    texts: tuple[str, ...],
    *,
    dense_threshold: float,
    lexical_threshold: float,
    rrf_k: int,
) -> list[int]:
    lexical_rows = connection.execute(
        """SELECT ordinal-1,
                  armi_extensions.word_similarity(%s,retrieval_text),
                  position(lower(%s) in lower(retrieval_text))>0
           FROM unnest(%s::text[]) WITH ORDINALITY
             AS source(retrieval_text,ordinal)""",
        (query, query, list(texts)),
    ).fetchall()
    dense_rows = tuple(
        (index, _cosine(vector, document))
        for index, document in enumerate(documents)
    )
    dense = [
        int(row[0])
        for row in sorted(
            dense_rows, key=lambda row: (-float(row[1]), int(row[0]))
        )
        if float(row[1]) >= dense_threshold
    ][:32]
    lexical = [
        int(row[0])
        for row in sorted(
            lexical_rows,
            key=lambda row: (-bool(row[2]), -float(row[1]), int(row[0])),
        )
        if float(row[1]) >= lexical_threshold or bool(row[2])
    ][:32]
    scores: dict[int, float] = {}
    for channel in (dense, lexical):
        for rank, document_id in enumerate(channel, 1):
            scores[document_id] = scores.get(document_id, 0.0) + 1 / (rrf_k + rank)
    return sorted(scores, key=lambda item: (-scores[item], item))


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
    hybrid_positive: list[tuple[int, list[int]]] = []
    hybrid_negative_recalls = 0
    query_latencies_ms: list[float] = []
    with psycopg.connect(_database_conninfo(environment_root)) as connection:
        for expected, (_document, queries) in enumerate(_CASES):
            for query in _positive_queries(queries):
                started = time.perf_counter()
                vector = (await adapter.embed_query(query)).vector
                query_latencies_ms.append((time.perf_counter() - started) * 1000)
                ranked = sorted(
                    (
                        (index, _cosine(vector, document))
                        for index, document in enumerate(documents)
                    ),
                    key=lambda item: (-item[1], item[0]),
                )
                positive_rankings.append((expected, ranked))
                hybrid_positive.append(
                    (
                        expected,
                        _hybrid_ranking(
                            connection,
                            query,
                            vector,
                            documents,
                            texts,
                            dense_threshold=adapter.binding.dense_min_similarity,
                            lexical_threshold=adapter.binding.lexical_min_similarity,
                            rrf_k=adapter.binding.fusion_rrf_k,
                        ),
                    )
                )
        negative_maxima: list[float] = []
        for query in _NEGATIVES:
            started = time.perf_counter()
            vector = (await adapter.embed_query(query)).vector
            query_latencies_ms.append((time.perf_counter() - started) * 1000)
            negative_maxima.append(
                max(_cosine(vector, document) for document in documents)
            )
            hybrid_negative_recalls += bool(
                _hybrid_ranking(
                    connection,
                    query,
                    vector,
                    documents,
                    texts,
                    dense_threshold=adapter.binding.dense_min_similarity,
                    lexical_threshold=adapter.binding.lexical_min_similarity,
                    rrf_k=adapter.binding.fusion_rrf_k,
                )
            )
    grid: list[dict[str, float]] = []
    for threshold in (0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60):
        hits = sum(
            expected in [index for index, score in ranked if score >= threshold][:6]
            for expected, ranked in positive_rankings
        )
        top1_hits = sum(
            bool(ranked)
            and ranked[0][0] == expected
            and ranked[0][1] >= threshold
            for expected, ranked in positive_rankings
        )
        false_recalls = sum(score >= threshold for score in negative_maxima)
        grid.append(
            {
                "threshold": threshold,
                "top1": round(top1_hits / len(positive_rankings), 4),
                "recall_at_6": round(hits / len(positive_rankings), 4),
                "negative_false_recall_rate": round(false_recalls / len(_NEGATIVES), 4),
            }
        )
    eligible = [item for item in grid if item["negative_false_recall_rate"] <= 0.1]
    selected = max(
        eligible,
        key=lambda item: (
            item["recall_at_6"],
            item["top1"],
            item["threshold"],
        ),
    )
    hybrid_top1 = sum(
        bool(ranked) and ranked[0] == expected
        for expected, ranked in hybrid_positive
    ) / len(hybrid_positive)
    hybrid_recall_at_6 = sum(
        expected in ranked[:6] for expected, ranked in hybrid_positive
    ) / len(hybrid_positive)
    hybrid_false_recall = hybrid_negative_recalls / len(_NEGATIVES)
    return {
        "positive_samples": len(positive_rankings),
        "negative_samples": len(_NEGATIVES),
        "binding_dense_threshold": adapter.binding.dense_min_similarity,
        "selected": selected,
        "grid": grid,
        "query_embedding_p95_ms": round(
            sorted(query_latencies_ms)[math.ceil(len(query_latencies_ms) * 0.95) - 1],
            2,
        ),
        "hybrid": {
            "top1": round(hybrid_top1, 4),
            "recall_at_6": round(hybrid_recall_at_6, 4),
            "negative_false_recall_rate": round(hybrid_false_recall, 4),
        },
        "passed": selected["threshold"] == adapter.binding.dense_min_similarity
        and selected["recall_at_6"] >= 0.9333
        and selected["top1"] >= 0.9167,
        "hybrid_passed": hybrid_recall_at_6 >= 0.9333
        and hybrid_top1 >= 0.9167
        and hybrid_false_recall <= 0.1,
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
    return 0 if result["passed"] and result["hybrid_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
