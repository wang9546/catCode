import asyncio
import logging
import os
import subprocess
from pathlib import Path

import anthropic

from . import config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are an AI coding assistant running on a Linux server. You can execute shell commands,
read files, and write files to accomplish tasks. Always work within the given working directory.

Guidelines:
- Use the bash tool to run commands. Check outputs before proceeding.
- Use write_file to create new files only — prefer bash + sed for small edits.
- Break complex tasks into manageable steps.
- If a command fails, diagnose the error before retrying.
- Report clearly what you did and why."""

TOOLS = [
    {
        "name": "bash",
        "description": "Execute a shell command in the working directory. Returns stdout and stderr.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to execute"}
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "Read the contents of a file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file (absolute or relative to working directory)"}
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Create or overwrite a file with the given content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file (absolute or relative to working directory)"},
                "content": {"type": "string", "description": "Content to write to the file"},
            },
            "required": ["path", "content"],
        },
    },
]


def _resolve_path(path: str) -> str:
    """解析路径，限制在 WORK_DIR 内"""
    work = Path(config.WORK_DIR).resolve()
    target = (work / path).resolve() if not os.path.isabs(path) else Path(path).resolve()
    if not str(target).startswith(str(work)):
        raise ValueError(f"路径越权: {path}")
    return str(target)


async def _execute_tool(name: str, inputs: dict) -> str:
    """执行工具调用"""
    if name == "bash":
        cmd = inputs["command"]
        try:
            proc = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                cwd=config.WORK_DIR, timeout=120,
            )
            result = proc.stdout or ""
            if proc.stderr:
                result += "\n[stderr]\n" + proc.stderr
            return (result or "(no output)").strip()
        except subprocess.TimeoutExpired:
            return "命令执行超时 (120s)"

    elif name == "read_file":
        filepath = _resolve_path(inputs["path"])
        try:
            content = Path(filepath).read_text()
            if len(content) > 8000:
                return content[:8000] + "\n... (文件太长，已截断)"
            return content
        except FileNotFoundError:
            return f"文件不存在: {filepath}"
        except Exception as e:
            return f"读取失败: {e}"

    elif name == "write_file":
        filepath = _resolve_path(inputs["path"])
        content = inputs["content"]
        try:
            Path(filepath).parent.mkdir(parents=True, exist_ok=True)
            Path(filepath).write_text(content)
            return f"已写入: {filepath}"
        except Exception as e:
            return f"写入失败: {e}"

    return f"未知工具: {name}"


async def run_agent(prompt: str, max_turns: int = 10) -> str:
    """运行 Claude Code 智能体，返回最终结果"""
    client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    messages = [{"role": "user", "content": prompt}]

    for _ in range(max_turns):
        response = await client.messages.create(
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=messages,
            model="claude-sonnet-4-6",
            tools=TOOLS,
        )

        # 收集助手返回内容
        tool_use_blocks = []
        text_blocks = []

        for block in response.content:
            if block.type == "text":
                text_blocks.append(block.text)
            elif block.type == "tool_use":
                tool_use_blocks.append(block)

        # 将助手消息加入历史
        messages.append({"role": "assistant", "content": response.content})

        # 没有工具调用 → 返回文本结果
        if not tool_use_blocks:
            return "\n".join(text_blocks).strip()

        # 执行工具调用，收集结果
        tool_results = []
        for tool in tool_use_blocks:
            logger.info("执行工具: %s %s", tool.name, tool.input)
            output = await _execute_tool(tool.name, dict(tool.input))
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool.id,
                "content": output[:4000],  # 限制单次返回长度
            })

        messages.append({"role": "user", "content": tool_results})

    return "达到最大轮次限制，任务可能未完成。"
