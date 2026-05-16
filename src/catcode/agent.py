"""Claude Code Agent — 调用本地 claude CLI，通过 CWD 隔离会话"""

import asyncio
import logging
import os
import shutil

from pathlib import Path

logger = logging.getLogger(__name__)

CLAUDE_BIN = shutil.which("claude") or "claude"


async def run_agent(
    prompt: str,
    cwd: str,
    conv_id: str = "",
    channel_type: str = "feishu",
    hook_port: int = 8080,
    continue_session: bool = False,
) -> str:
    """调用 claude CLI，PreToolUse Hook 负责审批。"""
    Path(cwd).mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.setdefault("CLAUDE_CODE_SIMPLE", "1")
    env["CATCODE_SERVER_URL"] = f"http://localhost:{hook_port}"
    env["CATCODE_CONVERSATION_ID"] = conv_id
    env["CATCODE_CHANNEL_TYPE"] = channel_type

    cmd = [
        CLAUDE_BIN,
        "--print",
        "--output-format", "text",
        "--max-budget-usd", "5",
        "--add-dir", cwd,
        "--permission-mode", "auto",
    ]
    if continue_session:
        cmd.append("--continue")
    cmd.append(prompt)

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
    proj_name = resolved.lstrip("/").replace("/", "-")
    return os.path.join(os.path.expanduser("~/.claude/projects"), proj_name)
