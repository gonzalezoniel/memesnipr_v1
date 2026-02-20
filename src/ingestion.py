from __future__ import annotations

from datetime import datetime, timezone

import httpx
from loguru import logger

from .config import settings
from .interfaces import Scanner
from .models import TokenCandidate

_DEXSCREENER_PROFILES_URL = "https://api.dexscreener.com/token-profiles/latest/v1"
_DEXSCREENER_TOKEN_URL = "https://api.dexscreener.com/latest/dex/tokens/{addresses}"
_HTTP_TIMEOUT = 12.0
_MAX_TOKENS_PER_BATCH = 30


async def fetch_current_prices(token_addresses: list[str]) -> dict[str, float]:
    if not token_addresses:
        return {}
    joined = ",".join(token_addresses[:_MAX_TOKENS_PER_BATCH])
    url = _DEXSCREENER_TOKEN_URL.format(addresses=joined)
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("DexScreener price fetch failed: {}", exc)
        return {}

    prices: dict[str, float] = {}
    for pair in data.get("pairs") or []:
        addr = pair.get("baseToken", {}).get("address", "")
        price_str = pair.get("priceUsd")
        if addr and price_str and addr not in prices:
            try:
                prices[addr] = float(price_str)
            except (ValueError, TypeError):
                pass
    return prices


class MockScanner(Scanner):
    async def scan_candidates(self) -> list[TokenCandidate]:
        now = datetime.now(timezone.utc)
        return [
            TokenCandidate(
                token_address="FAKE_TEST_MEME",
                symbol="TESTMEME",
                name="Test Meme Token",
                created_at=now,
                liquidity_usd=settings.MIN_LIQUIDITY_USD * 12,
                buy_tax_pct=5.0,
                sell_tax_pct=5.0,
                mint_authority_revoked=True,
                freeze_authority_revoked=True,
                is_honeypot=False,
                can_sell=True,
                buys_5m=60,
                sells_5m=10,
                volume_usd_5m=50000,
                top_holder_pct=8.0,
                holder_count=300,
            )
        ]


class DexScreenerScanner(Scanner):
    def __init__(self) -> None:
        self._seen: set[str] = set()

    async def scan_candidates(self) -> list[TokenCandidate]:
        addresses = await self._fetch_latest_solana_addresses()
        if not addresses:
            return []

        pairs = await self._fetch_pair_data(addresses)
        candidates: list[TokenCandidate] = []
        now = datetime.now(timezone.utc)

        for pair in pairs:
            try:
                candidate = self._pair_to_candidate(pair, now)
                if candidate is not None:
                    candidates.append(candidate)
            except Exception as exc:
                logger.debug("Skipping pair {}: {}", pair.get("pairAddress", "?"), exc)

        logger.info("DexScreener scan: {} profiles -> {} pairs -> {} candidates",
                     len(addresses), len(pairs), len(candidates))
        return candidates

    async def _fetch_latest_solana_addresses(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.get(_DEXSCREENER_PROFILES_URL)
                resp.raise_for_status()
                profiles = resp.json()
        except Exception as exc:
            logger.warning("DexScreener profiles fetch failed: {}", exc)
            return []

        addresses: list[str] = []
        for p in profiles:
            if p.get("chainId") != "solana":
                continue
            addr = p.get("tokenAddress", "")
            if addr and addr not in self._seen:
                addresses.append(addr)
        return addresses[:_MAX_TOKENS_PER_BATCH]

    async def _fetch_pair_data(self, addresses: list[str]) -> list[dict]:
        joined = ",".join(addresses)
        url = _DEXSCREENER_TOKEN_URL.format(addresses=joined)
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("DexScreener token fetch failed: {}", exc)
            return []

        pairs = data.get("pairs") or []
        seen_tokens: set[str] = set()
        unique: list[dict] = []
        for p in pairs:
            addr = p.get("baseToken", {}).get("address", "")
            if addr and addr not in seen_tokens:
                seen_tokens.add(addr)
                unique.append(p)
        return unique

    def _pair_to_candidate(self, pair: dict, now: datetime) -> TokenCandidate | None:
        base = pair.get("baseToken", {})
        addr = base.get("address", "")
        if not addr:
            return None

        self._seen.add(addr)

        txns_5m = pair.get("txns", {}).get("m5", {})
        volume = pair.get("volume", {})
        liq = pair.get("liquidity", {})
        created_ms = pair.get("pairCreatedAt")

        created_at = (
            datetime.fromtimestamp(created_ms / 1000.0, tz=timezone.utc)
            if created_ms
            else now
        )

        liquidity_usd = liq.get("usd") or 0.0
        if liquidity_usd < settings.MIN_LIQUIDITY_USD * 0.1:
            return None

        return TokenCandidate(
            token_address=addr,
            symbol=base.get("symbol", "???"),
            name=base.get("name", addr[:8]),
            created_at=created_at,
            liquidity_usd=liquidity_usd,
            buy_tax_pct=0.0,
            sell_tax_pct=0.0,
            mint_authority_revoked=True,
            freeze_authority_revoked=True,
            is_honeypot=False,
            can_sell=True,
            buys_5m=txns_5m.get("buys", 0),
            sells_5m=txns_5m.get("sells", 0),
            volume_usd_5m=volume.get("m5", 0.0),
            top_holder_pct=0.0,
            holder_count=0,
        )
