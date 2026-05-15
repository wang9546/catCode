"""飞书渠道 — FeishuChannel 长连接"""

import asyncio
import json
import logging
import re

from lark_oapi.channel.channel import FeishuChannel as LarkChannel

from .base import AbstractChannel, OnMessageCallback
from ..message import Message

logger = logging.getLogger(__name__)


class FeishuChannel(AbstractChannel):
    channel_type = "feishu"

    def __init__(self, app_id: str, app_secret: str):
        self._client = LarkChannel(
            app_id=app_id,
            app_secret=app_secret,
            transport="ws",
        )

    async def start(self, on_message: OnMessageCallback) -> None:
        processed: set[str] = set()

        async def handler(event) -> None:
            msg_id = event.id
            if msg_id in processed:
                return
            processed.add(msg_id)
            if len(processed) > 10000:
                processed.clear()

            if not event.content_text:
                return

            text = re.sub(r"@\S+", "", event.content_text).strip()
            if not text:
                return

            message = Message(
                content_text=text,
                conversation_id=event.conversation.chat_id,
                message_id=msg_id,
                channel_type=self.channel_type,
                sender_id=event.sender.open_id,
                raw={"event": event},
            )

            asyncio.create_task(on_message(message))

        self._client.on("message", handler)
        logger.info("飞书渠道启动")
        await self._client.start_background()

    async def send(self, conversation_id: str, text: str) -> str | None:
        result = await self._client.send(conversation_id, text)
        return result.message_id

    async def edit(self, message_id: str, text: str) -> None:
        await self._client.edit_message(message_id, text)

    async def add_reaction(self, message_id: str, emoji_type: str) -> str | None:
        result = await self._client.add_reaction(message_id, emoji_type)
        if result.success and result.raw:
            data = result.raw.get("data", {})
            return data.get("reaction_id") if isinstance(data, dict) else None
        return None

    async def remove_reaction(self, message_id: str, reaction_id: str) -> None:
        await self._client.remove_reaction(message_id, reaction_id)
