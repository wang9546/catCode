"""Claude Code Agent — 调用本地 claude CLI"""

import asyncio
import logging
import os
import shutil

from pathlib import Path
from . import config

logger = logging.getLogger(__name__)

CLAUDE_BIN = shutil.which("claude") or "claude"


class SessionBusyError(Exception):
    """session_id 被占用，需更换"""


async def run_agent(prompt: str, session_id: str | None = None) -> str:
    """调用本地 Claude Code CLI 执行任务。

    Args:
        prompt: 用户输入
        session_id: 可选，指定后 Claude Code 会加载/保存会话上下文

    Raises:
        SessionBusyError: session 被占用，调用方应换新 session 重试
    """
    return await _call_claude(prompt, session_id)


async def _call_claude(prompt: str, session_id: str | None) -> str:
    Path(config.WORK_DIR).mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.setdefault("CLAUDE_CODE_SIMPLE", "1")

    cmd = [
        CLAUDE_BIN,
        "--print",
        "--output-format", "text",
        "--max-budget-usd", "5",
        "--add-dir", config.WORK_DIR,
        "--permission-mode", "acceptEdits",
    ]

    if session_id:
        cmd += ["--session-id", session_id]
    else:
        cmd.append("--no-session-persistence")

    cmd.append(prompt)

    logger.info("执行 claude: %s ...", prompt[:80])

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=config.WORK_DIR,
        env=env,
    )

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)
    except asyncio.TimeoutError:
        proc.kill()
        return "任务执行超时 (10 分钟)"

    output = stdout.decode("utf-8", errors="replace").strip()
    err_text = stderr.decode("utf-8", errors="replace").strip()

    if err_text:
        logger.warning("claude stderr: %s", err_text[:500])
        if "already in use" in err_text:
            raise SessionBusyError(err_text)

    return output or "已完成（无文字输出）"
