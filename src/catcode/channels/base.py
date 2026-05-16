"""渠道抽象基类 — 所有渠道实现此接口"""

from abc import ABC, abstractmethod
from collections.abc import Callable, Awaitable

from ..message import Message

OnMessageCallback = Callable[[Message], Awaitable[None]]
# card_action: action_id, value dict → None
CardActionCallback = Callable[[str, dict], Awaitable[None]]


class AbstractChannel(ABC):
    """渠道基类。

    属性:
        channel_type: 渠道标识，如 "feishu"、"wecom"
    """

    channel_type: str

    @abstractmethod
    async def start(
        self,
        on_message: OnMessageCallback,
        on_card_action: CardActionCallback | None = None,
    ) -> None:
        """启动渠道连接，收到消息时调用 on_message(message)。"""
        ...

    @abstractmethod
    async def send(self, conversation_id: str, text: str) -> str | None:
        """发送消息，返回 message_id（不支持返回 None）。"""
        ...

    async def edit(self, message_id: str, text: str) -> None:
        """编辑已发送的消息（原地替换）。默认回退到 send。"""
        await self.send(None, text)  # type: ignore[arg-type]

    async def add_reaction(self, message_id: str, emoji_type: str) -> str | None:
        """给消息添加表情回应，返回 reaction_id。默认无操作。"""
        return None

    async def remove_reaction(self, message_id: str, reaction_id: str) -> None:
        """移除消息的表情回应。默认无操作。"""
        pass

    async def send_card(self, conversation_id: str, card: dict) -> str | None:
        """发送交互卡片消息。默认回退到 send 文本。"""
        title = card.get("header", {}).get("title", {}).get("content", "")
        return await self.send(conversation_id, str(title))

    async def update_approval_card(
        self, message_id: str, cmd: str, approved: bool
    ) -> None:
        """将审批卡片更新为结果状态（无按钮）。默认无操作。"""
        pass
