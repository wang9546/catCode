import os
import sys

from dotenv import load_dotenv

load_dotenv()


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        print(f"缺少环境变量: {name}", file=sys.stderr)
        sys.exit(1)
    return value


# ── 频道配置 ──────────────────────────────
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")

# ── 通用配置 ──────────────────────────────
WORK_DIR = os.getenv("WORK_DIR", "/root/workspace")
HOOK_PORT = int(os.getenv("CATCODE_HOOK_PORT", "8080"))
