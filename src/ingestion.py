from __future__ import annotations

from datetime import datetime, timezone

from .config import settings
from .interfaces import Scanner
from .models import TokenCandidate


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
