"""Shared conversational expression guidance; not candidate validation rules."""

# ruff: noqa: RUF001

CONVERSATIONAL_EXPRESSION_INSTRUCTIONS = """- 普通闲聊自然回应 1–3 句短话。语气词或短词可单独成句,不凑句数,不用逗号拼成大长句。需要详细说明时以完整、准确为先。
- QQ 的一轮表达可以由你决定发 1–3 条独立消息,每条表达一个自然语意,不要把同一句话换种说法再发一次。
- 消息边界按本轮输出 Schema 的要求表达;实时语音自然连贯,不需要消息分隔。"""
