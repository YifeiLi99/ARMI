"""Cognition instructions for durable questions and unrealized intentions."""

# ruff: noqa: RUF001 -- Chinese prose is the model instruction contract.

FOCUS_CONTEXT_REFERENCES = (
    ("UpdateConcern", "concern_ref", "current_concern"),
    ("CloseConcern", "concern_ref", "current_concern"),
    ("ActivityReview", "activity_ref", "current_activity"),
)

FOCUS_COGNITIVE_INSTRUCTIONS = """
## 持续关注
- Cognition 保存仍需关注的问题与尚未实施的意向，携带依据、当前认识、结束条件与等待或复查条件。
- 同一事项沿 current_concern 更新；不逐轮复制内心独白，不把所有意向强迫转换为 Activity。
- 新理解与想法在本轮认知形成。Mind 和 Mood 是只读数值状态，不可由主模型赋值。
- 无新信息可以等待、换方法或放下；重复表达不是进展，工具失败和消息送达不等于问题解决。
- resolve 必须说明依据如何满足结束条件；release 说明为何放下；没有变化可以保持原记录。
- Self 保存兴趣、偏好、价值及长期自我内容，Relationship 保存关系解释，Memory 保存主观记忆，实际活动交 Activity。
"""
