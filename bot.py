"""
Telegram Bot
Handles commands (/start, /status, /setmin, /pause, /resume)
and sends buy alerts to the configured chat.
"""

import asyncio
import logging
from typing import Optional
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)
from telegram.constants import ParseMode

from config import Config
from monitor import SuiMonitor, SwapEvent
from price_feed import PriceFeed
from formatter import BuyAlert, format_buy_message

logger = logging.getLogger(__name__)


class SuiBuyBot:
    def __init__(self, config: Config):
        self.config = config
        self.monitor = SuiMonitor(config)
        self.price_feed = PriceFeed(
            coingecko_api_key=config.coingecko_api_key,
            ttl=config.price_cache_ttl,
        )
        self._paused = False
        self._total_buys = 0
        self._total_volume_usd = 0.0
        self._app: Optional[Application] = None
        self._bot: Optional[Bot] = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self):
        self._app = (
            Application.builder()
            .token(self.config.telegram_token)
            .build()
        )
        self._bot = self._app.bot

        # Register command handlers
        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("pause", self._cmd_pause))
        self._app.add_handler(CommandHandler("resume", self._cmd_resume))
        self._app.add_handler(CommandHandler("setmin", self._cmd_setmin))
        self._app.add_handler(CommandHandler("help", self._cmd_help))

        logger.info("Bot initialized, starting polling & monitor loop...")

        # Run monitor loop and telegram polling concurrently
        await self._send_startup_message()
        async with self._app:
            await self._app.start()
            await self._app.updater.start_polling(drop_pending_updates=True)
            await self._monitor_loop()
            await self._app.updater.stop()
            await self._app.stop()

    # ── Monitor loop ──────────────────────────────────────────────────────────

    async def _monitor_loop(self):
        logger.info("Monitor loop started.")
        try:
            async for swap in self.monitor.watch():
                if self._paused:
                    continue
                await self._handle_swap(swap)
        except asyncio.CancelledError:
            pass
        finally:
            await self.monitor.stop()
            await self.price_feed.close()

    async def _handle_swap(self, swap: SwapEvent):
        try:
            sui_price = await self.price_feed.get_sui_price()
            token_address = self.config.tracked_token.replace("0x", "")
            token_price = await self.price_feed.get_token_price_from_dexscreener(
                token_address, swap.pool_address
            )

            # Compute USD amounts
            if "usdc" in swap.coin_in_type.lower() or "usdt" in swap.coin_in_type.lower():
                spend_usd = swap.amount_in_ui
            else:
                spend_usd = swap.amount_in_ui * sui_price

            received_usd = swap.amount_out_ui * token_price if token_price else 0.0

            # Filter tiny buys
            if spend_usd < self.config.min_buy_usd:
                logger.debug("Buy filtered (%.2f USD < %.2f min)", spend_usd, self.config.min_buy_usd)
                return

            market_cap = await self.price_feed.get_market_cap(token_address)
            volume_24h = await self.price_feed.get_24h_volume(token_address)

            alert = BuyAlert(
                swap=swap,
                token_price_usd=token_price,
                sui_price_usd=sui_price,
                spend_usd=spend_usd,
                received_usd=received_usd,
                market_cap_usd=market_cap,
                volume_24h_usd=volume_24h,
                config=self.config,
            )

            message = format_buy_message(alert)
            await self._send_alert(message)

            self._total_buys += 1
            self._total_volume_usd += spend_usd

        except Exception as exc:
            logger.error("Error handling swap: %s", exc, exc_info=True)

    async def _send_alert(self, text: str):
        try:
            await self._bot.send_message(
                chat_id=self.config.telegram_chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            logger.info("Alert sent.")
        except Exception as exc:
            logger.error("Failed to send alert: %s", exc)

    async def _send_startup_message(self):
        msg = (
            f"🤖 <b>SUI Buy Bot Online!</b>\n\n"
            f"👁 Tracking: <code>{self.config.tracked_token}</code>\n"
            f"💲 Symbol:  <b>{self.config.token_symbol}</b>\n"
            f"🔔 Min buy: <b>${self.config.min_buy_usd:.2f}</b>\n\n"
            f"Type /help for commands."
        )
        try:
            await (await self._app.bot.get_me())  # warm up connection
            await self._bot.send_message(
                chat_id=self.config.telegram_chat_id,
                text=msg,
                parse_mode=ParseMode.HTML,
            )
        except Exception as exc:
            logger.warning("Could not send startup message: %s", exc)

    # ── Command handlers ──────────────────────────────────────────────────────

    async def _cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_html(
            f"👋 <b>SUI Buy Bot</b>\n\n"
            f"Tracking <b>{self.config.token_symbol}</b> buys on SUI DEXes.\n\n"
            f"Use /help to see available commands."
        )

    async def _cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_html(
            "📋 <b>Commands</b>\n\n"
            "/status – Show current stats\n"
            "/pause – Pause buy alerts\n"
            "/resume – Resume buy alerts\n"
            "/setmin &lt;usd&gt; – Set minimum buy USD\n"
            "  e.g. <code>/setmin 50</code>\n"
        )

    async def _cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        status = "🟢 Running" if not self._paused else "⏸ Paused"
        await update.message.reply_html(
            f"📊 <b>Bot Status</b>\n\n"
            f"Status:     {status}\n"
            f"Token:      <b>{self.config.token_symbol}</b>\n"
            f"Min buy:    <b>${self.config.min_buy_usd:.2f}</b>\n"
            f"Buys seen:  <b>{self._total_buys}</b>\n"
            f"Total vol:  <b>${self._total_volume_usd:,.2f}</b>\n"
        )

    async def _cmd_pause(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update):
            return
        self._paused = True
        await update.message.reply_text("⏸ Buy alerts paused.")

    async def _cmd_resume(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update):
            return
        self._paused = False
        await update.message.reply_text("▶️ Buy alerts resumed.")

    async def _cmd_setmin(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update):
            return
        try:
            val = float(ctx.args[0])
            self.config.min_buy_usd = val
            await update.message.reply_html(f"✅ Minimum buy set to <b>${val:.2f}</b>")
        except (IndexError, ValueError):
            await update.message.reply_text("Usage: /setmin <amount>  e.g. /setmin 50")

    def _is_admin(self, update: Update) -> bool:
        if not self.config.telegram_admin_id:
            return True  # No admin set → everyone can use admin commands
        return str(update.effective_user.id) == str(self.config.telegram_admin_id)
