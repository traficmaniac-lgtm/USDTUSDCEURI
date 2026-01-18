"""Fake quote generator for demo updates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import random


@dataclass(frozen=True)
class QuoteConfig:
    """Configuration for generated quote values."""

    base_price: float = 1.0
    jitter: float = 0.002
    spread_min: float = 0.00005
    spread_max: float = 0.0004


class FakeQuoteService:
    """Generate synthetic quote data for the UI."""

    def __init__(self, config: QuoteConfig | None = None) -> None:
        self._config = config or QuoteConfig()

    def generate(self, pair: str, exchanges: list[str]) -> list[dict[str, object]]:
        """Return fake quotes for the given pair and exchange list."""
        quotes: list[dict[str, object]] = []
        timestamp = datetime.now().strftime("%H:%M:%S")
        for exchange in exchanges:
            base = self._config.base_price + random.uniform(-self._config.jitter, self._config.jitter)
            spread = random.uniform(self._config.spread_min, self._config.spread_max)
            bid = base - spread / 2
            ask = base + spread / 2
            last = base + random.uniform(-spread / 2, spread / 2)
            status = self._pick_status(spread)
            quotes.append(
                {
                    "exchange": exchange,
                    "bid": bid,
                    "ask": ask,
                    "last": last,
                    "spread": spread,
                    "timestamp": timestamp,
                    "status": status,
                    "pair": pair,
                    "source": "HTTP",
                }
            )
        return quotes

    @staticmethod
    def _pick_status(spread: float) -> str:
        if spread > 0.00038:
            return "Error"
        if spread > 0.0003:
            return "Warning"
        return "OK"
