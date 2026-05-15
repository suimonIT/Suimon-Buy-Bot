"""
Price Feed
Fetches SUI / token USD prices from CoinGecko or DexScreener as fallback.
Results are cached for `price_cache_ttl` seconds.
"""

import asyncio
import logging
import time
from typing import Optional
import httpx

logger = logging.getLogger(__name__)


class PriceFeed:
    def __init__(self, coingecko_api_key: Optional[str] = None, ttl: int = 30):
        self._api_key = coingecko_api_key
        self._ttl = ttl
        self._cache: dict[str, tuple[float, float]] = {}  # key → (price, ts)
        self._client = httpx.AsyncClient(timeout=10)

    async def get_sui_price(self) -> float:
        return await self._get_price("sui", "sui-network")

    async def get_token_price_from_dexscreener(
        self, token_address: str, pool_address: str = ""
    ) -> float:
        """
        Fetches token price from DexScreener.
        Uses the token address (without 0x prefix) as search term.
        """
        cache_key = f"ds:{token_address}"
        cached = self._from_cache(cache_key)
        if cached is not None:
            return cached

        try:
            # Search by token address
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            resp = await self._client.get(url)
            resp.raise_for_status()
            data = resp.json()
            pairs = data.get("pairs", [])
            if pairs:
                # Take the most liquid pair
                best = max(pairs, key=lambda p: float(p.get("liquidity", {}).get("usd", 0) or 0))
                price = float(best.get("priceUsd", 0) or 0)
                self._set_cache(cache_key, price)
                return price
        except Exception as exc:
            logger.debug("DexScreener price fetch failed: %s", exc)

        return 0.0

    async def get_market_cap(self, token_address: str) -> float:
        """Returns USD market cap from DexScreener."""
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            resp = await self._client.get(url)
            resp.raise_for_status()
            data = resp.json()
            pairs = data.get("pairs", [])
            if pairs:
                best = max(pairs, key=lambda p: float(p.get("liquidity", {}).get("usd", 0) or 0))
                fdv = best.get("fdv") or best.get("marketCap")
                if fdv:
                    return float(fdv)
        except Exception as exc:
            logger.debug("Market cap fetch failed: %s", exc)
        return 0.0

    async def get_24h_volume(self, token_address: str) -> float:
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            resp = await self._client.get(url)
            resp.raise_for_status()
            data = resp.json()
            pairs = data.get("pairs", [])
            if pairs:
                return sum(
                    float(p.get("volume", {}).get("h24", 0) or 0)
                    for p in pairs
                )
        except Exception:
            pass
        return 0.0

    # ── Internals ──────────────────────────────────────────────────────────

    async def _get_price(self, cg_id: str, fallback_id: str = "") -> float:
        cached = self._from_cache(cg_id)
        if cached is not None:
            return cached

        # Try CoinGecko
        try:
            headers = {}
            if self._api_key:
                headers["x-cg-pro-api-key"] = self._api_key
            url = (
                f"https://api.coingecko.com/api/v3/simple/price"
                f"?ids={cg_id}&vs_currencies=usd"
            )
            resp = await self._client.get(url, headers=headers)
            resp.raise_for_status()
            price = float(resp.json().get(cg_id, {}).get("usd", 0))
            if price:
                self._set_cache(cg_id, price)
                return price
        except Exception as exc:
            logger.debug("CoinGecko price fetch failed for %s: %s", cg_id, exc)

        # Fallback: DexScreener for SUI
        if cg_id == "sui":
            try:
                url = "https://api.dexscreener.com/latest/dex/tokens/0x2::sui::SUI"
                resp = await self._client.get(url)
                data = resp.json()
                pairs = data.get("pairs", [])
                if pairs:
                    price = float(pairs[0].get("priceUsd", 0) or 0)
                    self._set_cache(cg_id, price)
                    return price
            except Exception:
                pass

        return 0.0

    def _from_cache(self, key: str) -> Optional[float]:
        entry = self._cache.get(key)
        if entry and (time.time() - entry[1]) < self._ttl:
            return entry[0]
        return None

    def _set_cache(self, key: str, price: float):
        self._cache[key] = (price, time.time())

    async def close(self):
        await self._client.aclose()
