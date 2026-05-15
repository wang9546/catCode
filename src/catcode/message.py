"""统一消息模型 — 所有渠道收敛到此结构"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Message:
    content_text: str            # 消息正文（已去除 @提及）
    conversation_id: str         # 群/会话 ID
    message_id: str              # 消息 ID（去重用）
    channel_type: str            # "feishu" | "wecom" | ...
    sender_id: str = ""          # 发送者 ID
    raw: dict[str, Any] = field(default_factory=dict)  # 原始事件
