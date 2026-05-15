"""
🚀 SUI Buy Bot - Telegram Bot for SUI DEX Buy Notifications
Main entry point
"""

import asyncio
import logging
import sys
from bot import SuiBuyBot
from config import Config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("sui_buy_bot.log"),
    ],
)
logger = logging.getLogger(__name__)


async def main():
    logger.info("🚀 Starting SUI Buy Bot...")
    config = Config.from_env()
    config.validate()

    bot = SuiBuyBot(config)
    await bot.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
