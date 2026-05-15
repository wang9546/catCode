"""Claude Code Agent — 调用本地 claude CLI，通过 CWD 隔离会话"""

import asyncio
import logging
import os
import re
import shutil

from pathlib import Path
from . import config

logger = logging.getLogger(__name__)

CLAUDE_BIN = shutil.which("claude") or "claude"

# Claude 输出"需要批准"时的提示模式
_PERMISSION_DENIED_RE = re.compile(
    r"该命令需要(?:你的|您在 UI 中)批准",
    re.IGNORECASE,
)
# 提取被拒绝的命令: `curl https://...`
_PERMISSION_CMD_RE = re.compile(r"`([^`]+)`")


async def run_agent(prompt: str, cwd: str) -> str:
    """调用 claude CLI，自动批准所有操作。"""
    return await _call_claude(prompt, cwd=cwd, permission_mode="auto")


async def run_agent_with_check(prompt: str, cwd: str) -> tuple[str, str | None]:
    """调用 claude CLI，默认权限模式，返回 (output, blocked_command_or_None)。"""
    output = await _call_claude(prompt, cwd=cwd, permission_mode="default")
    if _PERMISSION_DENIED_RE.search(output):
        cmd = _extract_blocked_command(output)
        return output, cmd
    return output, None


async def continue_with_approval(message: str, cwd: str) -> str:
    """以自动批准模式继续之前的会话。"""
    return await _call_claude(
        message, cwd=cwd, permission_mode="auto", continue_session=True,
    )


async def _call_claude(
    prompt: str,
    *,
    cwd: str,
    permission_mode: str,
    continue_session: bool = False,
) -> str:
    Path(cwd).mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.setdefault("CLAUDE_CODE_SIMPLE", "1")

    cmd = [
        CLAUDE_BIN,
        "--print",
        "--output-format", "text",
        "--max-budget-usd", "5",
        "--add-dir", cwd,
        "--permission-mode", permission_mode,
    ]
    if continue_session:
        cmd.append("--continue")

    cmd.append(prompt)

    logger.info("执行 claude cwd=%s mode=%s: %s ...", cwd, permission_mode, prompt[:80])

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
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


def _extract_blocked_command(text: str) -> str | None:
    """从 Claude 的权限提示中提取被拒绝的命令。"""
    matches = _PERMISSION_CMD_RE.findall(text)
    if matches:
        return matches[-1]  # 取最后一个（通常是实际命令）
    return None


def reset_session(cwd: str) -> None:
    """删除会话目录下的 Claude Code session 文件，实现重置"""
    import glob
    project_dir = _project_dir_for(cwd)
    pattern = os.path.join(project_dir, "*.jsonl")
    for f in glob.glob(pattern):
        os.remove(f)
        logger.info("已删除 session 文件: %s", f)


def _project_dir_for(cwd: str) -> str:
    """获取 Claude Code 用于存储 session 的项目目录"""
    resolved = os.path.abspath(cwd)
    proj_name = resolved.lstrip("/").replace("/", "-")
    return os.path.join(os.path.expanduser("~/.claude/projects"), proj_name)
