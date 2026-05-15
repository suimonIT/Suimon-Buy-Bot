"""
SUI Blockchain Monitor
Polls swap events from Cetus, Turbos and other DEXes via JSON-RPC.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional
import httpx

from config import Config

logger = logging.getLogger(__name__)


# ── Data models ──────────────────────────────────────────────────────────────

@dataclass
class SwapEvent:
    """Normalised swap event – DEX-agnostic."""
    tx_digest: str
    dex: str                   # "Cetus" | "Turbos" | "DeepBook" | …
    pool_address: str
    sender: str
    coin_in_type: str
    coin_out_type: str
    amount_in_raw: int         # smallest unit
    amount_out_raw: int
    timestamp_ms: int
    is_buy: bool = False       # True when coin_out == tracked_token
    amount_in_ui: float = 0.0
    amount_out_ui: float = 0.0


# ── RPC helpers ───────────────────────────────────────────────────────────────

class SuiRpcClient:
    def __init__(self, url: str, backup_url: str):
        self.url = url
        self.backup_url = backup_url
        self._client = httpx.AsyncClient(timeout=15)
        self._req_id = 0

    async def call(self, method: str, params: list) -> dict:
        self._req_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._req_id,
            "method": method,
            "params": params,
        }
        for url in [self.url, self.backup_url]:
            try:
                resp = await self._client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                if "error" in data:
                    logger.warning("RPC error from %s: %s", url, data["error"])
                    continue
                return data.get("result", {})
            except Exception as exc:
                logger.warning("RPC call to %s failed: %s", url, exc)
        return {}

    async def close(self):
        await self._client.aclose()


# ── Event parsers ─────────────────────────────────────────────────────────────

class CetusParser:
    """
    Parses Cetus pool::SwapEvent.
    Event fields: pool, amount_in, amount_out, a2b (bool), atob (bool),
                  before_sqrt_price, after_sqrt_price, steps, fee_amount
    The coin types are derived from the pool object.
    """
    SWAP_EVENT_SUFFIX = "::pool::SwapEvent"

    @staticmethod
    def matches(event_type: str, package: str) -> bool:
        return event_type.startswith(package) and "SwapEvent" in event_type

    @staticmethod
    def parse(raw: dict, tx_digest: str) -> Optional[SwapEvent]:
        try:
            parsed = raw.get("parsedJson", {})
            event_type: str = raw.get("type", "")

            # Extract coin types from generic params: pkg::pool::Pool<CoinA, CoinB>
            # The event type itself often looks like:
            # 0x<pkg>::pool::SwapEvent
            # Coin types are embedded in the pool field or we read from the pool object.
            # For now we derive direction from a2b flag.
            a2b: bool = parsed.get("a2b", True)
            amount_in = int(parsed.get("amount_in", 0))
            amount_out = int(parsed.get("amount_out", 0))
            pool = parsed.get("pool", "")

            # The coin types must be fetched separately via sui_getObject(pool).
            # We embed them as placeholders – the monitor resolves them.
            return SwapEvent(
                tx_digest=tx_digest,
                dex="Cetus",
                pool_address=pool,
                sender=raw.get("sender", ""),
                coin_in_type="__RESOLVE__",
                coin_out_type="__RESOLVE__",
                amount_in_raw=amount_in,
                amount_out_raw=amount_out,
                timestamp_ms=int(raw.get("timestampMs", int(time.time() * 1000))),
                # a2b == True means CoinA→CoinB; we flag direction after resolution
                is_buy=not a2b,  # updated by monitor after coin type resolution
            )
        except Exception as exc:
            logger.debug("Cetus parse error: %s | raw=%s", exc, raw)
            return None


class TurbosParser:
    """
    Parses Turbos pool::SwapEvent.
    Fields: pool, token_a_amount, token_b_amount, a_to_b, ...
    """

    @staticmethod
    def matches(event_type: str, package: str) -> bool:
        return event_type.startswith(package) and "SwapEvent" in event_type

    @staticmethod
    def parse(raw: dict, tx_digest: str) -> Optional[SwapEvent]:
        try:
            parsed = raw.get("parsedJson", {})
            a_to_b: bool = parsed.get("a_to_b", True)
            amount_in = int(parsed.get("token_a_amount" if a_to_b else "token_b_amount", 0))
            amount_out = int(parsed.get("token_b_amount" if a_to_b else "token_a_amount", 0))
            pool = parsed.get("pool", "")
            return SwapEvent(
                tx_digest=tx_digest,
                dex="Turbos",
                pool_address=pool,
                sender=raw.get("sender", ""),
                coin_in_type="__RESOLVE__",
                coin_out_type="__RESOLVE__",
                amount_in_raw=amount_in,
                amount_out_raw=amount_out,
                timestamp_ms=int(raw.get("timestampMs", int(time.time() * 1000))),
                is_buy=not a_to_b,
            )
        except Exception as exc:
            logger.debug("Turbos parse error: %s", exc)
            return None


# ── Pool coin-type cache ──────────────────────────────────────────────────────

class PoolCache:
    """Caches pool_address → (coinA_type, coinB_type) to avoid repeated RPC calls."""

    def __init__(self, rpc: SuiRpcClient):
        self._rpc = rpc
        self._cache: dict[str, tuple[str, str]] = {}

    async def get_coins(self, pool_address: str) -> tuple[str, str]:
        if pool_address in self._cache:
            return self._cache[pool_address]

        result = await self._rpc.call("sui_getObject", [
            pool_address,
            {"showType": True, "showContent": False},
        ])
        obj_type: str = result.get("data", {}).get("type", "")
        # Pool type looks like: 0x<pkg>::pool::Pool<0x2::sui::SUI, 0x<token>::token::TOKEN>
        coin_a, coin_b = self._extract_generic_params(obj_type)
        self._cache[pool_address] = (coin_a, coin_b)
        return coin_a, coin_b

    @staticmethod
    def _extract_generic_params(type_str: str) -> tuple[str, str]:
        start = type_str.find("<")
        end = type_str.rfind(">")
        if start == -1 or end == -1:
            return "", ""
        inner = type_str[start + 1: end]
        # Split on the comma that separates the two top-level generics
        depth = 0
        split_idx = -1
        for i, ch in enumerate(inner):
            if ch == "<":
                depth += 1
            elif ch == ">":
                depth -= 1
            elif ch == "," and depth == 0:
                split_idx = i
                break
        if split_idx == -1:
            return inner.strip(), ""
        return inner[:split_idx].strip(), inner[split_idx + 1:].strip()


# ── Main monitor ──────────────────────────────────────────────────────────────

class SuiMonitor:
    """
    Continuously polls SUI DEX swap events and yields SwapEvent objects
    that match the tracked token.
    """

    def __init__(self, config: Config):
        self.config = config
        self.rpc = SuiRpcClient(config.sui_rpc_url, config.sui_rpc_url_backup)
        self.pool_cache = PoolCache(self.rpc)
        self._cursors: dict[str, Optional[dict]] = {}   # package → cursor
        self._running = False

    # ── Public API ────────────────────────────────────────────────────────────

    async def watch(self) -> AsyncIterator[SwapEvent]:
        """Async generator that yields resolved buy events for the tracked token."""
        self._running = True
        packages = self._all_packages()
        logger.info("Monitoring %d DEX package(s) for token: %s",
                    len(packages), self.config.tracked_token)

        while self._running:
            for pkg in packages:
                events = await self._fetch_events(pkg)
                for raw_event, tx in events:
                    swap = self._parse_event(raw_event, tx, pkg)
                    if swap is None:
                        continue
                    swap = await self._resolve_coins(swap)
                    if self._is_tracked_buy(swap):
                        swap.is_buy = True
                        swap = self._compute_ui_amounts(swap)
                        yield swap

            await asyncio.sleep(self.config.poll_interval_seconds)

    async def stop(self):
        self._running = False
        await self.rpc.close()

    # ── Internals ─────────────────────────────────────────────────────────────

    def _all_packages(self) -> list[str]:
        pkgs = [
            self.config.cetus_package,
            self.config.turbos_package,
        ] + self.config.extra_packages
        return pkgs

    async def _fetch_events(self, package: str) -> list[tuple[dict, str]]:
        """Query events for a package and advance the cursor."""
        cursor = self._cursors.get(package)
        params = [
            {"MoveEventPackage": package},
            cursor,
            self.config.max_events_per_poll,
            False,   # descending=False → newest first? No, ascending for cursor tracking
        ]
        result = await self.rpc.call("suix_queryEvents", params)
        if not result:
            return []

        data = result.get("data", [])
        if result.get("hasNextPage") and result.get("nextCursor"):
            self._cursors[package] = result["nextCursor"]
        elif not cursor:
            # First run: set cursor to last event so we only see NEW events going forward
            if data:
                self._cursors[package] = result.get("nextCursor")
            return []   # Skip existing events on first run

        pairs = []
        for ev in data:
            tx = ev.get("id", {}).get("txDigest", "")
            pairs.append((ev, tx))
        return pairs

    def _parse_event(self, raw: dict, tx: str, package: str) -> Optional[SwapEvent]:
        event_type: str = raw.get("type", "")
        if CetusParser.matches(event_type, self.config.cetus_package):
            return CetusParser.parse(raw, tx)
        if TurbosParser.matches(event_type, self.config.turbos_package):
            return TurbosParser.parse(raw, tx)
        return None

    async def _resolve_coins(self, swap: SwapEvent) -> SwapEvent:
        if swap.coin_in_type != "__RESOLVE__" or not swap.pool_address:
            return swap
        try:
            coin_a, coin_b = await self.pool_cache.get_coins(swap.pool_address)
            # Determine direction: is_buy=True when user receives the tracked token
            if swap.dex in ("Cetus",):
                # Cetus a2b flag was stored as is_buy=not(a2b); re-map
                # is_buy currently means a2b==False i.e. B→A
                if swap.is_buy:  # B→A: coin_in=B, coin_out=A
                    swap.coin_in_type = coin_b
                    swap.coin_out_type = coin_a
                else:            # A→B: coin_in=A, coin_out=B
                    swap.coin_in_type = coin_a
                    swap.coin_out_type = coin_b
            else:
                if not swap.is_buy:  # a_to_b
                    swap.coin_in_type = coin_a
                    swap.coin_out_type = coin_b
                else:
                    swap.coin_in_type = coin_b
                    swap.coin_out_type = coin_a
        except Exception as exc:
            logger.debug("Could not resolve coins for pool %s: %s", swap.pool_address, exc)
        return swap

    def _is_tracked_buy(self, swap: SwapEvent) -> bool:
        """Returns True when the swap outputs the tracked token (= a buy)."""
        tracked = self.config.tracked_token.lower()
        return swap.coin_out_type.lower() == tracked or \
               swap.coin_out_type.lower().endswith(f"::{tracked.split('::')[-1]}")

    def _compute_ui_amounts(self, swap: SwapEvent) -> SwapEvent:
        decimals = self.config.token_decimals
        swap.amount_out_ui = swap.amount_out_raw / (10 ** decimals)
        # coin_in is typically SUI (9 decimals) or a stablecoin (6 decimals)
        in_dec = 6 if "usdc" in swap.coin_in_type.lower() or "usdt" in swap.coin_in_type.lower() else 9
        swap.amount_in_ui = swap.amount_in_raw / (10 ** in_dec)
        return swap
