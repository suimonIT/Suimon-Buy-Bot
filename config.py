"""
Configuration – loaded from environment variables (.env)
"""

import os
from dataclasses import dataclass, field
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # ── Telegram ─────────────────────────────────────────────────────────────
    telegram_token: str = ""
    telegram_chat_id: str = ""          # channel / group to post buys in
    telegram_admin_id: Optional[str] = None  # for admin commands

    # ── SUI RPC ──────────────────────────────────────────────────────────────
    sui_rpc_url: str = "https://fullnode.mainnet.sui.io:443"
    sui_rpc_url_backup: str = "https://sui-mainnet.nodeinfra.com"

    # ── Token to track ───────────────────────────────────────────────────────
    # Coin type, e.g. "0x2::sui::SUI" or a custom token address
    tracked_token: str = ""
    token_symbol: str = "TOKEN"
    token_decimals: int = 9

    # ── DEX event filters ────────────────────────────────────────────────────
    # Cetus Protocol (largest SUI DEX)
    cetus_package: str = (
        "0x1eabed72c53feb3805120a081dc15963c204dc8d091542592abaf7a35689b2fb"
    )
    # Turbos Finance
    turbos_package: str = (
        "0x91bfbc386a41afcfd9b2533058d7e915a1d3829089cc268ff4333d54d6339ca1"
    )
    # DeepBook
    deepbook_package: str = (
        "0x000000000000000000000000000000000000000000000000000000000000dee9"
    )

    # ── Monitor settings ─────────────────────────────────────────────────────
    poll_interval_seconds: float = 2.0   # how often to poll for new events
    min_buy_usd: float = 0.0             # filter tiny buys (0 = show all)
    max_events_per_poll: int = 50

    # ── Display ───────────────────────────────────────────────────────────────
    emoji_small: str = "🐟"    # < $100
    emoji_medium: str = "🐬"   # $100 – $1 000
    emoji_whale: str = "🐋"    # > $1 000
    show_chart_link: bool = True
    chart_url_template: str = "https://dexscreener.com/sui/{pool_address}"

    # ── Price feed ───────────────────────────────────────────────────────────
    coingecko_api_key: Optional[str] = None   # optional – unlocks higher rate-limits
    price_cache_ttl: int = 30                 # seconds

    # ── Extra DEX packages to monitor (comma-separated in env) ───────────────
    extra_packages: list = field(default_factory=list)

    @classmethod
    def from_env(cls) -> "Config":
        extra_raw = os.getenv("EXTRA_DEX_PACKAGES", "")
        extra = [p.strip() for p in extra_raw.split(",") if p.strip()]

        return cls(
            telegram_token=os.getenv("TELEGRAM_TOKEN", ""),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
            telegram_admin_id=os.getenv("TELEGRAM_ADMIN_ID"),
            sui_rpc_url=os.getenv("SUI_RPC_URL", "https://fullnode.mainnet.sui.io:443"),
            tracked_token=os.getenv("TRACKED_TOKEN", ""),
            token_symbol=os.getenv("TOKEN_SYMBOL", "TOKEN"),
            token_decimals=int(os.getenv("TOKEN_DECIMALS", "9")),
            poll_interval_seconds=float(os.getenv("POLL_INTERVAL", "2.0")),
            min_buy_usd=float(os.getenv("MIN_BUY_USD", "0")),
            coingecko_api_key=os.getenv("COINGECKO_API_KEY"),
            extra_packages=extra,
        )

    def validate(self):
        errors = []
        if not self.telegram_token:
            errors.append("TELEGRAM_TOKEN is not set")
        if not self.telegram_chat_id:
            errors.append("TELEGRAM_CHAT_ID is not set")
        if not self.tracked_token:
            errors.append("TRACKED_TOKEN is not set")
        if errors:
            raise ValueError("Config errors:\n" + "\n".join(f"  • {e}" for e in errors))
