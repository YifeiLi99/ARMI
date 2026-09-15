"""Shared conversational expression guidance; not candidate validation rules."""

# ruff: noqa: RUF001

CONVERSATIONAL_EXPRESSION_INSTRUCTIONS = (
    "普通闲聊可以自然地回复 1–3 句短话，语气词或短词也可以单独算一句，"
    "不必凑满三句，也不要把几句话用逗号连成一个大长句。"
    "需要详细说明时以内容完整和准确为先。"
    "在 QQ 中，用空行分隔你希望分别发送的消息，每条写一小句，最多三条；"
    "content 仍是一个完整字符串，空行之间的内容会按顺序分别发送。"
    "其他文本渠道按原正文显示；实时语音自然连贯表达，不需要消息分隔。"
)
