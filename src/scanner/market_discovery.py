"""Market discovery helpers for scanner mode."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

import ccxt


@dataclass(frozen=True)
class MarketDiscoveryResult:
    """Container for eligible market pairs."""

    pair_exchanges: dict[str, list[str]]
    eligible_pairs: list[str]
    exchange_counts: dict[str, int]


class MarketDiscoveryService:
    """Service to load markets and build eligible pairs."""

    _exchange_map = {
        "Binance": "binance",
        "OKX": "okx",
        "Bybit": "bybit",
        "Gate.io": "gateio",
        "KuCoin": "kucoin",
        "Kraken": "kraken",
        "Coinbase": "coinbase",
        "Bitfinex": "bitfinex",
        "Bitget": "bitget",
        "HTX": "htx",
    }

    def discover(
        self,
        exchanges: Iterable[str],
        quotes: Iterable[str],
        min_exchanges: int,
        should_cancel: Callable[[], bool] | None = None,
    ) -> MarketDiscoveryResult:
        """Load markets and return eligible pairs."""
        quotes_set = {quote.upper() for quote in quotes}
        pair_exchanges: dict[str, set[str]] = {}
        exchange_counts: dict[str, int] = {}

        for exchange_label in exchanges:
            if should_cancel and should_cancel():
                break
            exchange_id = self._exchange_map.get(exchange_label, exchange_label.lower())
            if not hasattr(ccxt, exchange_id):
                continue
            exchange = getattr(ccxt, exchange_id)()
            markets = exchange.load_markets()
            filtered = self._filter_markets(markets.values(), quotes_set)
            exchange_counts[exchange_label] = len(filtered)
            for symbol in filtered:
                pair_exchanges.setdefault(symbol, set()).add(exchange_label)

        eligible_pairs = [
            pair
            for pair, exchanges in pair_exchanges.items()
            if len(exchanges) >= min_exchanges
        ]
        eligible_pairs.sort()
        normalized_pairs = {pair: sorted(exchanges) for pair, exchanges in pair_exchanges.items()}
        return MarketDiscoveryResult(normalized_pairs, eligible_pairs, exchange_counts)

    @staticmethod
    def _filter_markets(markets: Iterable[dict], quotes_set: set[str]) -> set[str]:
        filtered: set[str] = set()
        for market in markets:
            symbol = market.get("symbol")
            if not symbol or ":" in symbol or "/" not in symbol:
                continue
            if market.get("spot") is False:
                continue
            if market.get("contract") or market.get("future"):
                continue
            if market.get("margin"):
                continue
            if market.get("active") is False:
                continue
            quote = market.get("quote")
            if not quote:
                base, quote = MarketDiscoveryService._split_symbol(symbol)
                if not base or not quote:
                    continue
            if quote.upper() not in quotes_set:
                continue
            filtered.add(symbol)
        return filtered

    @staticmethod
    def _split_symbol(symbol: str) -> tuple[str | None, str | None]:
        parts = symbol.split("/", maxsplit=1)
        if len(parts) != 2:
            return None, None
        return parts[0].strip(), parts[1].strip()
