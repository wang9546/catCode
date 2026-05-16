"""网关核心 — 协调渠道 → 会话管理 → Agent → 回复"""

import asyncio
import json
import logging
import os
import re
import stat
import uuid

from aiohttp import web

from .agent import run_agent, reset_session
from .channels.base import AbstractChannel
from .message import Message

logger = logging.getLogger(__name__)

RESET_KEYWORDS = {"重置会话", "重置对话", "新对话", "reset", "/reset", "/new"}

_HOOK_SCRIPT = """\
#!/bin/bash
TOOL_INPUT=$(cat)
SERVER="${CATCODE_SERVER_URL:-http://localhost:8080}"
CONV_ID="${CATCODE_CONVERSATION_ID}"
CHANNEL="${CATCODE_CHANNEL_TYPE:-feishu}"

CMD=$(echo "$TOOL_INPUT" | python3 -c \
  "import json,sys; print(json.load(sys.stdin).get('tool_input',{}).get('command',''))" 2>/dev/null)

# 只拦截有副作用的危险操作，其余直接放行
needs_approval() {
  local cmd="$1"
  # 网络请求
  echo "$cmd" | grep -qE '\\bcurl\\b|\\bwget\\b|\\bssh\\b|\\bscp\\b|\\brsync\\b.*@|\\bnc\\b|\\bnetcat\\b' && return 0
  # 破坏性删除
  echo "$cmd" | grep -qE '\\brm\\b.+-[a-z]*r|\\brm\\b.+-[a-z]*f' && return 0
  # 磁盘/分区操作
  echo "$cmd" | grep -qE '\\bdd\\b|\\bmkfs\\b|\\bfdisk\\b|\\bparted\\b|\\bgdisk\\b|\\bshred\\b|\\bwipe\\b' && return 0
  # 提权
  echo "$cmd" | grep -qE '\\bsudo\\b|\\bsu\\b ' && return 0
  # 进程终止
  echo "$cmd" | grep -qE '\\bkill\\b|\\bpkill\\b|\\bkillall\\b' && return 0
  # 系统关机/重启
  echo "$cmd" | grep -qE '\\breboot\\b|\\bshutdown\\b|\\bhalt\\b|\\bpoweroff\\b|\\binit\\b [016]' && return 0
  # 服务管理（停止/禁用）
  echo "$cmd" | grep -qE 'systemctl (stop|disable|mask|kill)|service .* stop' && return 0
  # 防火墙规则
  echo "$cmd" | grep -qE '\\biptables\\b|\\bnft\\b|\\bufw\\b' && return 0
  # 用户/权限管理
  echo "$cmd" | grep -qE '\\buseradd\\b|\\buserdel\\b|\\busermod\\b|\\bpasswd\\b|\\bchown\\b.+-R|\\bchmod\\b.+-R' && return 0
  # 定时任务
  echo "$cmd" | grep -qE 'crontab\\b' && return 0
  # 全局包安装/卸载
  echo "$cmd" | grep -qE 'pip3? (install|uninstall)|apt(-get)? (install|remove|purge)|npm (install -g|uninstall -g)|brew (install|uninstall)' && return 0
  return 1
}

if ! needs_approval "$CMD"; then
  exit 0
fi

RESPONSE=$(echo "$TOOL_INPUT" | curl -sf -X POST "$SERVER/hook/approval" \\
  -H "Content-Type: application/json" \\
  -H "X-Conversation-Id: $CONV_ID" \\
  -H "X-Channel-Type: $CHANNEL" \\
  -d @-)

REQUEST_ID=$(echo "$RESPONSE" | python3 -c \\
  "import json,sys; print(json.load(sys.stdin).get('request_id',''))" 2>/dev/null)

if [ -z "$REQUEST_ID" ]; then
  echo "审批服务不可用"; exit 2
fi

for i in $(seq 1 60); do
  sleep 5
  DECISION=$(curl -sf "$SERVER/hook/approval/$REQUEST_ID" | \\
    python3 -c "import json,sys; print(json.load(sys.stdin).get('decision','pending'))" 2>/dev/null)
  [ "$DECISION" = "approved" ] && exit 0
  [ "$DECISION" = "denied"   ] && echo "飞书用户拒绝了此操作" && exit 2
done

echo "审批超时（5分钟无响应）"; exit 2
"""


class Gateway:
    def __init__(self, work_dir: str = "/root/workspace", hook_port: int = 8080):
        self._channels: dict[str, AbstractChannel] = {}
        self._queue_locks: dict[str, asyncio.Lock] = {}
        self._work_dir = work_dir
        self._hook_port = hook_port
        self._hook_script: str = ""
        # approval_id → {"status": "pending"|"approved"|"denied"}
        self._pending_approvals: dict[str, dict] = {}

    def register(self, channel: AbstractChannel) -> None:
        self._channels[channel.channel_type] = channel
        logger.info("注册渠道: %s", channel.channel_type)

    async def start(self) -> None:
        if not self._channels:
            logger.warning("没有注册任何渠道")
            return

        self._hook_script = _setup_hook(self._work_dir, self._hook_port)

        async def on_message(msg: Message) -> None:
            await self._dispatch(msg)

        async def on_card_action(action_id: str, value: dict) -> None:
            approval_id = value.get("approval_id", "")
            if approval_id and approval_id in self._pending_approvals:
                action = value.get("action")
                approved = action == "approve"
                entry = self._pending_approvals[approval_id]
                entry["status"] = "approved" if approved else "denied"

                channel = self._channels.get(entry.get("channel_type", ""))
                card_msg_id = entry.get("card_message_id")
                if channel and card_msg_id:
                    await channel.update_approval_card(
                        card_msg_id, entry.get("cmd", ""), approved
                    )

        coros = [
            self._start_http_server(),
            *[ch.start(on_message, on_card_action=on_card_action)
              for ch in self._channels.values()],
        ]
        await asyncio.gather(*coros)

    async def _start_http_server(self) -> None:
        app = web.Application()
        app.router.add_post("/hook/approval", self._handle_create_approval)
        app.router.add_get("/hook/approval/{request_id}", self._handle_get_approval)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "localhost", self._hook_port)
        await site.start()
        logger.info("Hook HTTP 服务器启动: http://localhost:%d", self._hook_port)

        while True:
            await asyncio.sleep(3600)

    async def _handle_create_approval(self, request: web.Request) -> web.Response:
        try:
            tool_info = await request.json()
            conv_id = request.headers.get("X-Conversation-Id", "")
            channel_type = request.headers.get("X-Channel-Type", "feishu")

            channel = self._channels.get(channel_type)
            if not channel:
                return web.json_response({"error": "channel not found"}, status=404)

            tool_input = tool_info.get("tool_input", {})
            cmd = tool_input.get("command", json.dumps(tool_input))

            approval_id = str(uuid.uuid4())[:8]
            self._pending_approvals[approval_id] = {
                "status": "pending",
                "card_message_id": None,
                "channel_type": channel_type,
                "cmd": cmd,
            }

            card = {
                "header": "⚠️ 需要批准",
                "header_color": "yellow",
                "body": f"Claude 需要执行以下命令，是否批准？\n\n```\n{cmd}\n```",
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
            card_msg_id = await channel.send_card(conv_id, card)
            self._pending_approvals[approval_id]["card_message_id"] = card_msg_id
            logger.info("发送审批卡片 approval_id=%s cmd=%.80s", approval_id, cmd)
            return web.json_response({"request_id": approval_id})

        except Exception as e:
            logger.exception("创建审批请求失败")
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_get_approval(self, request: web.Request) -> web.Response:
        request_id = request.match_info["request_id"]
        entry = self._pending_approvals.get(request_id)
        if not entry:
            return web.json_response({"decision": "not_found"}, status=404)
        return web.json_response({"decision": entry["status"]})

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

                _write_conv_settings(conv_dir, self._hook_script)
                reaction_id = await channel.add_reaction(msg.message_id, "Typing")
                result = await run_agent(
                    msg.content_text,
                    cwd=conv_dir,
                    conv_id=msg.conversation_id,
                    channel_type=msg.channel_type,
                    hook_port=self._hook_port,
                )

                await channel.remove_reaction(msg.message_id, reaction_id)
                await channel.add_reaction(msg.message_id, "DONE")
                reaction_id = None
                await channel.send(msg.conversation_id, result)

            except Exception as e:
                logger.exception("处理消息失败 msg_id=%s", msg.message_id)
                try:
                    if reaction_id:
                        await channel.remove_reaction(msg.message_id, reaction_id)
                    await channel.send(msg.conversation_id, f"❌ 出错: {e}")
                except Exception:
                    pass


def _setup_hook(work_dir: str, port: int) -> str:
    """写入共享 hook 脚本，返回脚本绝对路径。"""
    hooks_dir = os.path.join(work_dir, ".claude", "hooks")
    os.makedirs(hooks_dir, exist_ok=True)

    script_path = os.path.join(hooks_dir, "catcode-approve.sh")
    with open(script_path, "w") as f:
        f.write(_HOOK_SCRIPT)
    os.chmod(script_path, os.stat(script_path).st_mode | stat.S_IXUSR | stat.S_IXGRP)

    logger.info("Hook 脚本已写入 %s", script_path)
    return script_path


def _write_conv_settings(conv_dir: str, script_path: str) -> None:
    """在 conv_dir/.claude/ 写入 settings.json，使 hook 对该会话生效。"""
    claude_dir = os.path.join(conv_dir, ".claude")
    os.makedirs(claude_dir, exist_ok=True)

    settings_path = os.path.join(claude_dir, "settings.json")
    if os.path.exists(settings_path):
        return

    settings = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": script_path}],
                }
            ]
        }
    }
    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
    logger.info("会话 Hook 配置已写入 %s", claude_dir)


def _safe_dirname(key: str) -> str:
    """把 conversation_key 转成安全的目录名"""
    return re.sub(r"[^a-zA-Z0-9_:.-]", "_", key)
