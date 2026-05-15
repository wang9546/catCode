import asyncio
import logging
import os
import shutil

from pathlib import Path
from . import config

logger = logging.getLogger(__name__)

CLAUDE_BIN = shutil.which("claude") or "claude"


async def run_agent(prompt: str, max_turns: int = 10) -> str:
    """调用本地 Claude Code CLI 执行任务，返回文本结果"""
    Path(config.WORK_DIR).mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.setdefault("CLAUDE_CODE_SIMPLE", "1")

    cmd = [
        CLAUDE_BIN,
        "--print",
        "--output-format", "text",
        "--no-session-persistence",
        "--max-budget-usd", "5",
        "--add-dir", config.WORK_DIR,
        "--permission-mode", "acceptEdits",
        prompt,
    ]

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
        output = stdout.decode("utf-8", errors="replace").strip()
        if stderr:
            err_text = stderr.decode("utf-8", errors="replace").strip()
            if err_text:
                logger.warning("claude stderr: %s", err_text[:500])
        return output or "已完成（无文字输出）"
    except asyncio.TimeoutError:
        proc.kill()
        return "任务执行超时 (10 分钟)"
