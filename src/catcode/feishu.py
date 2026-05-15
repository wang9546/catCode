import httpx.exceptions
import json
import logging

import httpx

from . import config

logger = logging.getLogger(__name__)

TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
SEND_URL = "https://open.feishu.cn/open-apis/im/v1/messages"


async def get_tenant_access_token() -> str:
    """获取飞书 tenant_access_token"""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            TOKEN_URL,
            json={
                "app_id": config.FEISHU_APP_ID,
                "app_secret": config.FEISHU_APP_SECRET,
            },
            timeout=10,
        )
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"获取飞书 token 失败: {data}")
        return data["tenant_access_token"]


async def send_message(chat_id: str, text: str) -> None:
    """发送文本消息到飞书群聊"""
    token = await get_tenant_access_token()
    body = {
        "receive_id": chat_id,
        "msg_type": "text",
        "content": json.dumps({"text": text}, ensure_ascii=False),
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            SEND_URL,
            params={"receive_id_type": "chat_id"},
            json=body,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        data = resp.json()
        if data.get("code") != 0:
            logger.error("发送飞书消息失败: %s", data)
