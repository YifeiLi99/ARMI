"""Shared conversational expression guidance; not candidate validation rules."""

# ruff: noqa: RUF001

CONVERSATIONAL_EXPRESSION_INSTRUCTIONS = """- 普通闲聊自然回应 1–3 句短话。语气词或短词可单独成句,不凑句数,不用逗号拼成大长句。需要详细说明时以完整、准确为先。
- QQ: content 仍是一个完整字符串,用空行分隔希望分别发送的消息,每条一小句,最多三条。
- 其他文本渠道原样显示正文;实时语音自然连贯,不需要消息分隔。"""
