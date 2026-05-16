"""CatCode 入口 — 组装渠道 → 启动网关"""

import asyncio
import logging

from . import config
from .channels.feishu import FeishuChannel
from .gateway import Gateway

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


async def main_async():
    gateway = Gateway(work_dir=config.WORK_DIR, hook_port=config.HOOK_PORT)

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
    except KeyboardInterrupt:
        logger.info("服务已停止")


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
