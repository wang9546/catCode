"""飞书渠道 — FeishuChannel 长连接"""

import asyncio
import json
import logging
import re

from lark_oapi.channel.channel import FeishuChannel as LarkChannel
from lark_oapi.channel.types import CardActionEvent as LarkCardActionEvent

from .base import AbstractChannel, OnMessageCallback, CardActionCallback
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
        self._card_action_cb: CardActionCallback | None = None

    async def start(
        self,
        on_message: OnMessageCallback,
        on_card_action: CardActionCallback | None = None,
    ) -> None:
        self._card_action_cb = on_card_action
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

        if on_card_action:
            async def card_handler(event: LarkCardActionEvent) -> None:
                value = event.action.value
                action_id = event.action.tag or ""
                cb = self._card_action_cb
                if cb:
                    await cb(action_id, value if isinstance(value, dict) else {})

            self._client.on("cardAction", card_handler)

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

    async def send_card(self, conversation_id: str, card: dict) -> str | None:
        """发送交互卡片消息。card 包含 title, body, buttons 字段。"""
        feishu_card = _build_feishu_card(card)
        result = await self._client.send(conversation_id, feishu_card)
        return result.message_id


def _build_feishu_card(card: dict) -> dict:
    """构建飞书交互卡片"""
    elements = []

    if card.get("body"):
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": card["body"]},
        })
    else:
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": ""}})

    if card.get("buttons"):
        actions = []
        for btn in card["buttons"]:
            actions.append({
                "tag": "button",
                "text": {"tag": "plain_text", "content": btn.get("text", "")},
                "type": btn.get("type", "default"),
                "value": btn.get("value", {}),
            })
        elements.append({"tag": "action", "actions": actions})

    header = card.get("header", "")
    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": header},
                "template": card.get("header_color", "red"),
            },
            "elements": elements,
        },
    }
