"""渠道抽象基类 — 所有渠道实现此接口"""

from abc import ABC, abstractmethod
from collections.abc import Callable, Awaitable

from ..message import Message


OnMessageCallback = Callable[[Message], Awaitable[None]]


class AbstractChannel(ABC):
    """渠道基类。实现 start() 和 send() 即可接入网关。

    属性:
        channel_type: 渠道标识，如 "feishu"、"wecom"
    """

    channel_type: str

    @abstractmethod
    async def start(self, on_message: OnMessageCallback) -> None:
        """启动渠道连接，收到消息时调用 on_message(message)。"""
        ...

    @abstractmethod
    async def send(self, conversation_id: str, text: str) -> None:
        """向指定会话发送文本消息。"""
        ...
