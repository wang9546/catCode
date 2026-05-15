"""Claude Code Agent — 调用本地 claude CLI，通过 CWD 隔离会话"""

import asyncio
import logging
import os
import shutil

from pathlib import Path
from . import config

logger = logging.getLogger(__name__)

CLAUDE_BIN = shutil.which("claude") or "claude"


async def run_agent(prompt: str, cwd: str) -> str:
    """调用 claude CLI，通过 CWD 隔离会话上下文。

    每个 conversation 使用独立子目录，claude --continue 自动维护上下文。
    """
    Path(cwd).mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.setdefault("CLAUDE_CODE_SIMPLE", "1")

    cmd = [
        CLAUDE_BIN,
        "--print",
        "--continue",
        "--output-format", "text",
        "--max-budget-usd", "5",
        "--add-dir", cwd,
        "--permission-mode", "auto",
        prompt,
    ]

    logger.info("执行 claude cwd=%s: %s ...", cwd, prompt[:80])

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
    # Claude Code 将路径中的 / 替换为 -
    proj_name = resolved.lstrip("/").replace("/", "-")
    return os.path.join(os.path.expanduser("~/.claude/projects"), proj_name)
