"""网关核心 — 协调渠道 → 会话管理 → Agent → 回复"""

import asyncio
import logging
import os
import shutil
import re

from .agent import run_agent, reset_session
from .channels.base import AbstractChannel
from .message import Message

logger = logging.getLogger(__name__)

RESET_KEYWORDS = {"重置会话", "重置对话", "新对话", "reset", "/reset", "/new"}


class Gateway:
    def __init__(self, work_dir: str = "/root/workspace"):
        self._channels: dict[str, AbstractChannel] = {}
        self._queue_locks: dict[str, asyncio.Lock] = {}
        self._work_dir = work_dir

    def register(self, channel: AbstractChannel) -> None:
        self._channels[channel.channel_type] = channel
        logger.info("注册渠道: %s", channel.channel_type)

    async def start(self) -> None:
        if not self._channels:
            logger.warning("没有注册任何渠道")
            return

        async def on_message(msg: Message) -> None:
            await self._dispatch(msg)

        coros = [ch.start(on_message) for ch in self._channels.values()]
        await asyncio.gather(*coros)

    async def _dispatch(self, msg: Message) -> None:
        channel = self._channels.get(msg.channel_type)
        if not channel:
            return

        conv_key = f"{msg.channel_type}:{msg.conversation_id}"
        conv_dir = os.path.join(self._work_dir, _safe_dirname(conv_key))

        lock = self._queue_locks.setdefault(conv_key, asyncio.Lock())

        async with lock:
            reaction_id: str | None = None
            try:
                if msg.content_text.strip() in RESET_KEYWORDS:
                    reset_session(conv_dir)
                    await channel.send(msg.conversation_id, "会话已重置，开始新对话。")
                    return

                reaction_id = await channel.add_reaction(msg.message_id, "⏳")
                result = await run_agent(msg.content_text, cwd=conv_dir)
                reply = result or "已完成（无文字输出）"

                if reaction_id:
                    await channel.remove_reaction(msg.message_id, reaction_id)
                await channel.send(msg.conversation_id, reply)

            except Exception as e:
                logger.exception("处理消息失败 msg_id=%s", msg.message_id)
                err_text = f"❌ 出错: {e}"
                try:
                    if reaction_id:
                        await channel.remove_reaction(msg.message_id, reaction_id)
                    await channel.send(msg.conversation_id, err_text)
                except Exception:
                    pass


def _safe_dirname(key: str) -> str:
    """把 conversation_key 转成安全的目录名"""
    return re.sub(r"[^a-zA-Z0-9_:.-]", "_", key)
