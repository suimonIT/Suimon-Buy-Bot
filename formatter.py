"""
Message Formatter
Builds the Telegram HTML message for each buy event.
"""

from dataclasses import dataclass
from typing import Optional
from monitor import SwapEvent
from config import Config


@dataclass
class BuyAlert:
    swap: SwapEvent
    token_price_usd: float
    sui_price_usd: float
    spend_usd: float
    received_usd: float
    market_cap_usd: float
    volume_24h_usd: float
    config: Config


def _fmt_usd(value: float) -> str:
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"${value / 1_000:.1f}K"
    if value >= 1:
        return f"${value:.2f}"
    return f"${value:.4f}"


def _fmt_token(amount: float, symbol: str) -> str:
    if amount >= 1_000_000:
        return f"{amount / 1_000_000:.2f}M {symbol}"
    if amount >= 1_000:
        return f"{amount / 1_000:.1f}K {symbol}"
    return f"{amount:,.2f} {symbol}"


def _buy_emoji(usd: float, cfg: Config) -> str:
    if usd >= 1_000:
        return cfg.emoji_whale
    if usd >= 100:
        return cfg.emoji_medium
    return cfg.emoji_small


def _bar(usd: float) -> str:
    """A simple visual progress bar based on buy size."""
    levels = [10, 50, 100, 250, 500, 1000, 5000, 10000]
    filled = sum(1 for lvl in levels if usd >= lvl)
    total = len(levels)
    bar = "🟢" * filled + "⚪" * (total - filled)
    return bar


def _short_addr(addr: str) -> str:
    if len(addr) > 10:
        return addr[:6] + "…" + addr[-4:]
    return addr


def format_buy_message(alert: BuyAlert) -> str:
    sw = alert.swap
    cfg = alert.config
    emoji = _buy_emoji(alert.spend_usd, cfg)

    # Coin-in label
    if "sui::SUI" in sw.coin_in_type or sw.coin_in_type == "0x2::sui::SUI":
        coin_in_label = "SUI"
        amount_in_str = f"{sw.amount_in_ui:,.4f} SUI"
    elif "usdc" in sw.coin_in_type.lower():
        coin_in_label = "USDC"
        amount_in_str = f"{sw.amount_in_ui:,.2f} USDC"
    elif "usdt" in sw.coin_in_type.lower():
        coin_in_label = "USDT"
        amount_in_str = f"{sw.amount_in_ui:,.2f} USDT"
    else:
        coin_in_label = _short_addr(sw.coin_in_type.split("::")[-1])
        amount_in_str = f"{sw.amount_in_ui:,.4f} {coin_in_label}"

    received_str = _fmt_token(sw.amount_out_ui, cfg.token_symbol)
    sui_explorer = f"https://suiexplorer.com/txblock/{sw.tx_digest}"
    suivision = f"https://suivision.xyz/txblock/{sw.tx_digest}"

    lines = [
        f"{emoji} <b>New {cfg.token_symbol} Buy!</b> {emoji}",
        "",
        f"💰 <b>Spent:</b>    {amount_in_str} <i>({_fmt_usd(alert.spend_usd)})</i>",
        f"🪙 <b>Got:</b>      {received_str} <i>({_fmt_usd(alert.received_usd)})</i>",
        f"📈 <b>Price:</b>    {_fmt_usd(alert.token_price_usd)}",
        "",
        f"{_bar(alert.spend_usd)}",
        "",
    ]

    if alert.market_cap_usd:
        lines.append(f"🏦 <b>Mkt Cap:</b>  {_fmt_usd(alert.market_cap_usd)}")
    if alert.volume_24h_usd:
        lines.append(f"📊 <b>24h Vol:</b>  {_fmt_usd(alert.volume_24h_usd)}")

    lines += [
        "",
        f"🔗 <b>DEX:</b>      {sw.dex}",
        f"👤 <b>Buyer:</b>    <code>{_short_addr(sw.sender)}</code>",
        "",
        f"🔍 <a href='{sui_explorer}'>Explorer</a>  |  "
        f"<a href='{suivision}'>SuiVision</a>",
    ]

    if cfg.show_chart_link:
        chart_url = cfg.chart_url_template.format(pool_address=sw.pool_address)
        lines.append(f"📉 <a href='{chart_url}'>Chart</a>")

    return "\n".join(lines)
