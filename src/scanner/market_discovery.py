"""Market discovery helpers for scanner mode."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Iterable

import ccxt


@dataclass(frozen=True)
class MarketDiscoveryResult:
    """Container for eligible market pairs."""

    pair_exchanges: dict[str, list[str]]
    eligible_pairs: list[str]
    exchange_counts: dict[str, int]


@dataclass(frozen=True)
class MarketFilterStats:
    """Stats for market filtering stages."""

    total: int
    pass_spot: int
    pass_active: int
    pass_quote: int
    final: int


logger = logging.getLogger(__name__)


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
            if exchange_id == "binance":
                options = getattr(exchange, "options", None)
                if not isinstance(options, dict):
                    exchange.options = {}
                exchange.options["defaultType"] = "spot"
            markets = exchange.load_markets()
            filtered, stats = self._filter_markets(markets.values(), quotes_set)
            logger.info(
                "Markets stats: %s total=%d | spot=%d | active=%d | quote=%d | final=%d",
                exchange_label,
                stats.total,
                stats.pass_spot,
                stats.pass_active,
                stats.pass_quote,
                stats.final,
            )
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
    def _filter_markets(
        markets: Iterable[dict],
        quotes_set: set[str],
    ) -> tuple[set[str], MarketFilterStats]:
        market_list = list(markets)
        filtered: set[str] = set()
        pass_spot = 0
        pass_active = 0
        pass_quote = 0
        for market in market_list:
            symbol = market.get("symbol")
            if not symbol or ":" in symbol or "/" not in symbol:
                continue
            if market.get("contract") is True or market.get("future") is True:
                continue
            if market.get("swap") is True:
                continue
            if market.get("spot") is False:
                continue
            pass_spot += 1
            if market.get("active") is False:
                continue
            pass_active += 1
            quote = market.get("quote")
            if not quote:
                base, quote = MarketDiscoveryService._split_symbol(symbol)
                if not base or not quote:
                    continue
            if quote.upper() not in quotes_set:
                continue
            pass_quote += 1
            filtered.add(symbol)
        stats = MarketFilterStats(
            total=len(market_list),
            pass_spot=pass_spot,
            pass_active=pass_active,
            pass_quote=pass_quote,
            final=len(filtered),
        )
        return filtered, stats

    @staticmethod
    def _split_symbol(symbol: str) -> tuple[str | None, str | None]:
        parts = symbol.split("/", maxsplit=1)
        if len(parts) != 2:
            return None, None
        return parts[0].strip(), parts[1].strip()
