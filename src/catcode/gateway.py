"""网关核心 — 协调渠道 → 会话管理 → Agent → 回复"""

import asyncio
import logging
import os
import re
import uuid

from .agent import run_agent_with_check, continue_with_approval, reset_session
from .channels.base import AbstractChannel
from .message import Message

logger = logging.getLogger(__name__)

RESET_KEYWORDS = {"重置会话", "重置对话", "新对话", "reset", "/reset", "/new"}


class Gateway:
    def __init__(self, work_dir: str = "/root/workspace"):
        self._channels: dict[str, AbstractChannel] = {}
        self._queue_locks: dict[str, asyncio.Lock] = {}
        self._work_dir = work_dir
        # approval_id → {"event": asyncio.Event, "result": bool, "cmd": str}
        self._pending_approvals: dict[str, dict] = {}

    def register(self, channel: AbstractChannel) -> None:
        self._channels[channel.channel_type] = channel
        logger.info("注册渠道: %s", channel.channel_type)

    async def start(self) -> None:
        if not self._channels:
            logger.warning("没有注册任何渠道")
            return

        async def on_message(msg: Message) -> None:
            await self._dispatch(msg)

        async def on_card_action(action_id: str, value: dict) -> None:
            approval_id = value.get("approval_id", "")
            if approval_id and approval_id in self._pending_approvals:
                entry = self._pending_approvals[approval_id]
                entry["result"] = value.get("action") == "approve"
                entry["event"].set()

        coros = [
            ch.start(on_message, on_card_action=on_card_action)
            for ch in self._channels.values()
        ]
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

                # 第一步：用 default 权限运行，检测是否需要批准
                reaction_id = await channel.add_reaction(msg.message_id, "Typing")
                output, blocked_cmd = await run_agent_with_check(
                    msg.content_text, cwd=conv_dir,
                )

                if blocked_cmd:
                    approved = await self._request_approval(channel, msg, blocked_cmd)
                    if approved:
                        # 把 Typing 换成 Done，继续执行
                        if reaction_id:
                            await channel.remove_reaction(msg.message_id, reaction_id)
                        reaction_id = await channel.add_reaction(msg.message_id, "DONE")
                        result = await continue_with_approval(
                            "已授权，请继续执行。", cwd=conv_dir,
                        )
                        # DONE 已添加，跳过最后的 remove+add
                        reaction_id = None
                    else:
                        result = "用户拒绝了该命令的执行。"
                else:
                    result = output or "已完成（无文字输出）"

                if reaction_id:
                    await channel.remove_reaction(msg.message_id, reaction_id)
                    await channel.add_reaction(msg.message_id, "DONE")
                await channel.send(msg.conversation_id, result)

            except Exception as e:
                logger.exception("处理消息失败 msg_id=%s", msg.message_id)
                err_text = f"❌ 出错: {e}"
                try:
                    if reaction_id:
                        await channel.remove_reaction(msg.message_id, reaction_id)
                    await channel.send(msg.conversation_id, err_text)
                except Exception:
                    pass

    async def _request_approval(
        self, channel: AbstractChannel, msg: Message, blocked_cmd: str,
    ) -> bool:
        """发送审批卡片给用户，等待回复。返回 True=批准, False=拒绝。"""
        approval_id = str(uuid.uuid4())[:8]
        event = asyncio.Event()
        self._pending_approvals[approval_id] = {
            "event": event, "result": False, "cmd": blocked_cmd,
        }

        card = {
            "header": "⚠️ 需要批准",
            "header_color": "yellow",
            "body": f"Claude 需要执行以下命令，是否批准？\n\n```\n{blocked_cmd}\n```",
            "buttons": [
                {
                    "text": "✅ 批准",
                    "type": "primary",
                    "value": {"action": "approve", "approval_id": approval_id},
                },
                {
                    "text": "❌ 拒绝",
                    "type": "danger",
                    "value": {"action": "deny", "approval_id": approval_id},
                },
            ],
        }
        await channel.send_card(msg.conversation_id, card)
        logger.info("发送审批卡片 approval_id=%s cmd=%s", approval_id, blocked_cmd)

        # 等待用户点击（最长 5 分钟）
        try:
            await asyncio.wait_for(event.wait(), timeout=300)
            approved = self._pending_approvals.get(approval_id, {}).get("result", False)
        except asyncio.TimeoutError:
            approved = False
        finally:
            self._pending_approvals.pop(approval_id, None)

        return approved


def _safe_dirname(key: str) -> str:
    """把 conversation_key 转成安全的目录名"""
    return re.sub(r"[^a-zA-Z0-9_:.-]", "_", key)
