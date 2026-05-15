import asyncio
import json
import logging
import time

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response

from . import config
from .claude_agent import run_agent
from .feishu import send_message

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# 消息去重
_processed: dict[str, float] = {}


def _cleanup_processed():
    """清理过期的去重记录"""
    now = time.time()
    stale = [k for k, v in _processed.items() if now - v > 60]
    for k in stale:
        del _processed[k]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时确保工作目录存在"""
    import os
    os.makedirs(config.WORK_DIR, exist_ok=True)
    logger.info("启动完成，工作目录: %s，端口: %s", config.WORK_DIR, config.PORT)
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(request: Request):
    body = await request.json()

    # 飞书 URL 验证
    if body.get("type") == "url_verification":
        return {"challenge": body["challenge"]}

    event = body.get("event") or {}
    message = event.get("message")
    if not message:
        return Response(status_code=204)

    msg_id = message.get("message_id", "")
    _cleanup_processed()
    if msg_id in _processed:
        return Response(status_code=204)
    _processed[msg_id] = time.time()

    if message.get("message_type") != "text":
        return Response(status_code=204)

    # 解析消息内容
    try:
        content = json.loads(message["content"])
        user_text = content["text"]
    except (json.JSONDecodeError, KeyError):
        return Response(status_code=204)

    # 去掉 @机器人 提及
    import re
    user_text = re.sub(r"@\S+", "", user_text).strip()
    if not user_text:
        return Response(status_code=204)

    chat_id = event["message"]["chat_id"]

    # 异步处理，不阻塞 webhook 响应
    asyncio.create_task(_handle_message(chat_id, user_text, msg_id))
    return Response(status_code=200)


async def _handle_message(chat_id: str, user_text: str, msg_id: str):
    """后台异步处理消息"""
    try:
        await send_message(chat_id, "处理中...")
        result = await run_agent(user_text)
        reply = result or "已完成（无文字输出）"
        await send_message(chat_id, reply)
    except Exception as e:
        logger.exception("处理消息失败 msg_id=%s", msg_id)
        await send_message(chat_id, f"出错: {e}")


def main():
    import uvicorn
    uvicorn.run("catcode.main:app", host="0.0.0.0", port=config.PORT, log_level="info")


if __name__ == "__main__":
    main()
