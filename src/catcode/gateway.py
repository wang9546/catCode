"""网关核心 — 协调渠道 → 会话管理 → Agent → 回复"""

import asyncio
import logging

from .agent import run_agent
from .channels.base import AbstractChannel
from .message import Message
from .session_manager import SessionManager

logger = logging.getLogger(__name__)

# 触发重置会话的关键词
RESET_KEYWORDS = {"重置会话", "重置对话", "新对话", "reset", "/reset", "/new"}


class Gateway:
    def __init__(self, session_manager: SessionManager | None = None):
        self._channels: dict[str, AbstractChannel] = {}
        self._queue_locks: dict[str, asyncio.Lock] = {}
        self._session = session_manager or SessionManager()

    def register(self, channel: AbstractChannel) -> None:
        """注册渠道"""
        self._channels[channel.channel_type] = channel
        logger.info("注册渠道: %s", channel.channel_type)

    async def start(self) -> None:
        """启动所有已注册的渠道"""
        if not self._channels:
            logger.warning("没有注册任何渠道")
            return

        async def on_message(msg: Message) -> None:
            await self._dispatch(msg)

        coros = [ch.start(on_message) for ch in self._channels.values()]
        await asyncio.gather(*coros)

    async def _dispatch(self, msg: Message) -> None:
        """收到消息后的调度链路：去重 → 会话 → Agent → 回复"""
        channel = self._channels.get(msg.channel_type)
        if not channel:
            return

        conv_key = f"{msg.channel_type}:{msg.conversation_id}"

        # 排队锁：同一个 conversation 串行处理
        lock = self._queue_locks.setdefault(conv_key, asyncio.Lock())

        async with lock:
            status_msg_id: str | None = None
            try:
                if msg.content_text.strip() in RESET_KEYWORDS:
                    self._session.reset(conv_key)
                    await channel.send(msg.conversation_id, "会话已重置，开始新对话。")
                    return

                session_id = self._session.get_session_id(conv_key)

                # 先发键盘表情占位
                status_msg_id = await channel.send(msg.conversation_id, "⌨️ ...")

                result = await run_agent(msg.content_text, session_id=session_id)
                reply = result or "已完成（无文字输出）"

                # 原地编辑替换为结果
                if status_msg_id:
                    await channel.edit(status_msg_id, reply)
                else:
                    await channel.send(msg.conversation_id, reply)

            except Exception as e:
                logger.exception("处理消息失败 msg_id=%s", msg.message_id)
                err_text = f"⌨️ ❌ 出错: {e}"
                try:
                    if status_msg_id:
                        await channel.edit(status_msg_id, err_text)
                    else:
                        await channel.send(msg.conversation_id, err_text)
                except Exception:
                    pass
