"""CatCode 入口 — 组装渠道 → 启动网关"""

import asyncio
import logging
import os
import sys

from . import config
from .channels.feishu import FeishuChannel
from .gateway import Gateway
from .session_manager import SessionManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


async def main_async():
    store_path = config.SESSION_STORE or os.path.expanduser("~/.catcode/sessions.json")
    session_mgr = SessionManager(store_path)
    gateway = Gateway(session_manager=session_mgr)

    # 注册飞书渠道
    if config.FEISHU_APP_ID and config.FEISHU_APP_SECRET:
        feishu = FeishuChannel(
            app_id=config.FEISHU_APP_ID,
            app_secret=config.FEISHU_APP_SECRET,
        )
        gateway.register(feishu)
    else:
        logger.warning("未配置 FEISHU_APP_ID，跳过飞书渠道")

    # TODO: 未来注册更多渠道
    # if config.WECOM_TOKEN:
    #     gateway.register(WecomChannel(...))

    logger.info("启动网关... work_dir=%s", config.WORK_DIR)

    try:
        await gateway.start()
        # 渠道 start 返回后保持运行，定期清理过期会话
        while True:
            await asyncio.sleep(600)
            session_mgr.expire_idle(ttl=3600)
    except KeyboardInterrupt:
        logger.info("服务已停止")


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
