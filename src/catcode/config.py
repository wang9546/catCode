import os
import sys


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        print(f"缺少环境变量: {name}", file=sys.stderr)
        sys.exit(1)
    return value


ANTHROPIC_API_KEY = require_env("ANTHROPIC_API_KEY")
FEISHU_APP_ID = require_env("FEISHU_APP_ID")
FEISHU_APP_SECRET = require_env("FEISHU_APP_SECRET")
WORK_DIR = os.getenv("WORK_DIR", "/root/workspace")
PORT = int(os.getenv("PORT", "3000"))
