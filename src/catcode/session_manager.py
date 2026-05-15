"""会话映射管理 — 只存 conversation_id → session_id 的映射"""

import json
import logging
import os
import time
import uuid

from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_STORE_PATH = os.path.expanduser("~/.catcode/sessions.json")


class SessionManager:
    """管理 conversation → session_id 的映射。

    对话历史由 Claude Code 自身通过 --session-id 持久化，
    这里只维护一个极简映射表，存储在 JSON 文件中。
    """

    def __init__(self, store_path: str = DEFAULT_STORE_PATH):
        self._store_path = Path(store_path)
        self._mapping: dict[str, str] = {}       # conversation_key → session_id
        self._last_active: dict[str, float] = {}  # session_id → timestamp
        self._lock = __import__("asyncio").Lock()
        self._load()

    # ── 公共接口 ──────────────────────────────────────────

    def get_session_id(self, conversation_key: str) -> str:
        """获取或创建会话 ID"""
        if conversation_key in self._mapping:
            sid = self._mapping[conversation_key]
        else:
            sid = str(uuid.uuid4())
            self._mapping[conversation_key] = sid
            self._save()
        self._last_active[sid] = time.time()
        return sid

    def reset(self, conversation_key: str) -> str:
        """重置会话（删除旧 ID，生成新 ID）"""
        old = self._mapping.pop(conversation_key, None)
        if old:
            self._last_active.pop(old, None)
        new_sid = str(uuid.uuid4())
        self._mapping[conversation_key] = new_sid
        self._last_active[new_sid] = time.time()
        self._save()
        logger.info("会话已重置: %s → %s", conversation_key, new_sid)
        return new_sid

    def expire_idle(self, ttl: int = 3600) -> int:
        """清理空闲超过 ttl 秒的会话，返回清理数量"""
        now = time.time()
        stale_keys = [
            k for k, sid in self._mapping.items()
            if now - self._last_active.get(sid, 0) > ttl
        ]
        for k in stale_keys:
            sid = self._mapping.pop(k)
            self._last_active.pop(sid, None)
        if stale_keys:
            self._save()
            logger.info("清理 %d 个过期会话", len(stale_keys))
        return len(stale_keys)

    # ── 持久化 ────────────────────────────────────────────

    def _load(self) -> None:
        try:
            if self._store_path.exists():
                data = json.loads(self._store_path.read_text())
                self._mapping = data.get("mapping", {})
                self._last_active = data.get("last_active", {})
                logger.info("加载 %d 个会话映射", len(self._mapping))
        except Exception as e:
            logger.warning("加载会话映射失败: %s", e)

    def _save(self) -> None:
        try:
            self._store_path.parent.mkdir(parents=True, exist_ok=True)
            self._store_path.write_text(json.dumps({
                "mapping": self._mapping,
                "last_active": self._last_active,
            }, indent=2))
        except Exception as e:
            logger.error("保存会话映射失败: %s", e)
