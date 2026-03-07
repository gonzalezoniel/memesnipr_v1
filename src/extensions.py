"""
Modular Architecture Stubs (Section 16).

These are placeholder modules for future extension.
Each stub defines a clear interface that can be implemented later.
"""
from __future__ import annotations

from typing import Any, Protocol


# --- Sentiment AI ---
class SentimentAnalyzer(Protocol):
    """Analyze token sentiment from text/social data."""
    def analyze(self, text: str, token_symbol: str) -> dict[str, Any]:
        ...


class SentimentAIStub:
    """Placeholder for AI-powered sentiment analysis."""
    def analyze(self, text: str, token_symbol: str) -> dict[str, Any]:
        return {"sentiment": 0.0, "confidence": 0.0, "source": "stub"}


# --- Influencer Wallet Tracking ---
class InfluencerTracker(Protocol):
    """Track known influencer wallets for early signals."""
    def get_influencer_trades(self, token_address: str) -> list[dict[str, Any]]:
        ...


class InfluencerTrackerStub:
    """Placeholder for influencer wallet tracking."""
    def get_influencer_trades(self, token_address: str) -> list[dict[str, Any]]:
        return []


# --- Telegram Alpha Scraper ---
class TelegramScraper(Protocol):
    """Scrape alpha from Telegram channels."""
    def get_recent_mentions(self, token_symbol: str) -> list[dict[str, Any]]:
        ...


class TelegramScraperStub:
    """Placeholder for Telegram alpha scraping."""
    def get_recent_mentions(self, token_symbol: str) -> list[dict[str, Any]]:
        return []


# --- DEX Trending Monitor ---
class DexTrendingMonitor(Protocol):
    """Monitor DEX trending lists for early signals."""
    def get_trending_tokens(self) -> list[dict[str, Any]]:
        ...


class DexTrendingMonitorStub:
    """Placeholder for DEX trending monitoring."""
    def get_trending_tokens(self) -> list[dict[str, Any]]:
        return []


# --- Wallet Network Graph ---
class WalletNetworkGraph(Protocol):
    """Analyze wallet relationships and clusters."""
    def find_clusters(self, wallet_addresses: list[str]) -> list[dict[str, Any]]:
        ...


class WalletNetworkGraphStub:
    """Placeholder for wallet network graph analysis."""
    def find_clusters(self, wallet_addresses: list[str]) -> list[dict[str, Any]]:
        return []


# --- Multi-Chain Support ---
class ChainAdapter(Protocol):
    """Adapter for supporting multiple blockchains."""
    def get_chain_name(self) -> str:
        ...

    def fetch_token_data(self, token_address: str) -> dict[str, Any]:
        ...


class SolanaAdapter:
    """Current Solana implementation."""
    def get_chain_name(self) -> str:
        return "solana"

    def fetch_token_data(self, token_address: str) -> dict[str, Any]:
        return {"chain": "solana", "address": token_address}


# --- Extension Registry ---
EXTENSIONS: dict[str, type] = {
    "sentiment_ai": SentimentAIStub,
    "influencer_tracker": InfluencerTrackerStub,
    "telegram_scraper": TelegramScraperStub,
    "dex_trending_monitor": DexTrendingMonitorStub,
    "wallet_network_graph": WalletNetworkGraphStub,
    "chain_adapter": SolanaAdapter,
}


def get_extension(name: str) -> Any:
    """Get an extension instance by name."""
    cls = EXTENSIONS.get(name)
    if cls is None:
        raise ValueError(f"Unknown extension: {name}")
    return cls()


def list_extensions() -> list[str]:
    """List all available extensions."""
    return list(EXTENSIONS.keys())
