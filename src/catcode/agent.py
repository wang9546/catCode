"""Claude Code Agent — 调用本地 claude CLI"""

import asyncio
import logging
import os
import shutil
import signal

from pathlib import Path
from . import config

logger = logging.getLogger(__name__)

CLAUDE_BIN = shutil.which("claude") or "claude"


def _kill_session_holder(session_id: str) -> None:
    """查找并 kill 占用指定 session 的 claude 进程"""
    try:
        import subprocess
        result = subprocess.run(
            ["ps", "-eo", "pid,args"],
            capture_output=True, text=True,
        )
        for line in result.stdout.splitlines():
            if "claude" in line and session_id in line:
                pid = int(line.strip().split()[0])
                logger.info("kill 占用 session 的进程 pid=%s", pid)
                os.kill(pid, signal.SIGTERM)
    except Exception as e:
        logger.warning("查找/kill session 占用进程失败: %s", e)


async def run_agent(prompt: str, session_id: str | None = None) -> str:
    """调用本地 Claude Code CLI 执行任务。

    session_id 被占用时自动 kill 旧进程、等待释放后重试（保留上下文）。
    """
    return await _call_claude_with_retry(prompt, session_id)


async def _call_claude_with_retry(prompt: str, session_id: str | None) -> str:
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

        if session_id and "already in use" in err_text:
            logger.info("Session 被占用，kill 旧进程后重试: %s", session_id)
            _kill_session_holder(session_id)
            await asyncio.sleep(2)
            return await _call_claude_once(prompt, session_id)

    return output or "已完成（无文字输出）"


async def _call_claude_once(prompt: str, session_id: str | None) -> str:
    """单次调用 claude，不处理重试"""
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

    return output or "已完成（无文字输出）"
