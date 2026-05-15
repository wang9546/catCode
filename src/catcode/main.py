import asyncio
import json
import logging
import re

from lark_oapi.channel.channel import FeishuChannel

from . import config
from .claude_agent import run_agent

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

_processed: set[str] = set()

# 全局 channel 实例，事件处理器中通过闭包引用
channel = FeishuChannel(
    app_id=config.FEISHU_APP_ID,
    app_secret=config.FEISHU_APP_SECRET,
    transport="ws",
)


async def handle_message(event) -> None:
    """收到消息时立即返回，后台异步处理 Claude 任务"""
    msg_id = event.id

    if msg_id in _processed:
        return
    _processed.add(msg_id)
    if len(_processed) > 10000:
        _processed.clear()

    # 只处理文本消息
    if not event.content_text:
        return

    text = re.sub(r"@\S+", "", event.content_text).strip()
    if not text:
        return

    chat_id = event.conversation.chat_id
    logger.info("收到: chat_id=%s text=%s", chat_id, text[:80])

    # 启动后台任务，不阻塞事件处理
    asyncio.create_task(_process_message(chat_id, text, msg_id))


async def _process_message(chat_id: str, text: str, msg_id: str) -> None:
    """后台处理：调用 Claude 并回复"""
    try:
        await channel.send(chat_id, "处理中...")
        result = await run_agent(text)
        reply = result or "已完成（无文字输出）"
        await channel.send(chat_id, reply)
    except Exception as e:
        logger.exception("处理消息失败 msg_id=%s", msg_id)
        try:
            await channel.send(chat_id, f"出错: {e}")
        except Exception:
            pass


async def main_async():
    channel.on("message", handle_message)
    logger.info("启动长连接... app_id=%s work_dir=%s", config.FEISHU_APP_ID, config.WORK_DIR)
    await channel.start_background()
    # 阻塞等待直到停止
    await channel.wait_ready()
    # 保持运行
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    except KeyboardInterrupt:
        logger.info("服务已停止")


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
