"""Ticker scan service for scanner mode."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from statistics import median
from typing import Iterable

import ccxt

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TickerScanUpdate:
    """Ticker scan result for a single pair."""

    pair: str
    best_buy_exchange: str | None
    buy_ask: float | None
    best_sell_exchange: str | None
    sell_bid: float | None
    spread_abs: float | None
    spread_pct: float | None
    volume_24h: float | None


@dataclass(frozen=True)
class TickerScanResult:
    """Container for a scan cycle."""

    updates: list[TickerScanUpdate]
    pair_count: int
    ok_count: int
    fail_count: int
    errors: list[str]


class TickerScanService:
    """Service that fetches tickers and computes spreads."""

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

    def scan(
        self,
        pair_exchanges: dict[str, list[str]],
        max_pairs: int,
        pairs: list[str] | None = None,
    ) -> TickerScanResult:
        """Fetch tickers for the given pairs and compute spreads."""
        if pairs is None:
            pairs_to_scan = sorted(pair_exchanges.keys())[:max_pairs]
        else:
            pairs_to_scan = list(pairs)[:max_pairs]
        exchanges_cache: dict[str, ccxt.Exchange] = {}
        updates: list[TickerScanUpdate] = []
        errors: list[str] = []
        ok_count = 0
        fail_count = 0

        for pair in pairs_to_scan:
            asks: list[tuple[float, str]] = []
            bids: list[tuple[float, str]] = []
            volumes: list[float] = []

            for exchange_label in pair_exchanges.get(pair, []):
                exchange_id = self._exchange_map.get(exchange_label, exchange_label.lower())
                if not hasattr(ccxt, exchange_id):
                    continue
                exchange = exchanges_cache.get(exchange_id)
                if exchange is None:
                    exchange = getattr(ccxt, exchange_id)()
                    if exchange_id == "binance":
                        options = getattr(exchange, "options", None)
                        if not isinstance(options, dict):
                            exchange.options = {}
                        exchange.options["defaultType"] = "spot"
                    exchanges_cache[exchange_id] = exchange
                try:
                    ticker = exchange.fetch_ticker(pair)
                    ok_count += 1
                except Exception as exc:  # noqa: BLE001 - per-exchange errors are expected
                    fail_count += 1
                    message = f"Ticker error: {exchange_label} {pair}: {exc}"
                    errors.append(message)
                    logger.warning(message)
                    continue

                bid = _as_float(ticker.get("bid"))
                ask = _as_float(ticker.get("ask"))
                if bid is not None and ask is not None:
                    bids.append((bid, exchange_label))
                    asks.append((ask, exchange_label))

                volume = _pick_volume(ticker)
                if volume is not None:
                    volumes.append(volume)

            update = _build_update(pair, bids, asks, volumes)
            updates.append(update)

        return TickerScanResult(
            updates=updates,
            pair_count=len(pairs_to_scan),
            ok_count=ok_count,
            fail_count=fail_count,
            errors=errors,
        )


def _pick_volume(ticker: dict) -> float | None:
    quote_volume = _as_float(ticker.get("quoteVolume"))
    if quote_volume is not None:
        return quote_volume
    return _as_float(ticker.get("baseVolume"))


def _build_update(
    pair: str,
    bids: Iterable[tuple[float, str]],
    asks: Iterable[tuple[float, str]],
    volumes: Iterable[float],
) -> TickerScanUpdate:
    bids_list = list(bids)
    asks_list = list(asks)
    volumes_list = list(volumes)
    best_buy_exchange = None
    buy_ask = None
    best_sell_exchange = None
    sell_bid = None
    spread_abs = None
    spread_pct = None

    if asks_list:
        buy_ask, best_buy_exchange = min(asks_list, key=lambda item: item[0])
    if bids_list:
        sell_bid, best_sell_exchange = max(bids_list, key=lambda item: item[0])

    if buy_ask is not None and sell_bid is not None:
        spread_abs = sell_bid - buy_ask
        mid = (sell_bid + buy_ask) / 2
        if mid > 0:
            spread_pct = spread_abs / mid * 100

    volume_24h = median(volumes_list) if volumes_list else None
    return TickerScanUpdate(
        pair=pair,
        best_buy_exchange=best_buy_exchange,
        buy_ask=buy_ask,
        best_sell_exchange=best_sell_exchange,
        sell_bid=sell_bid,
        spread_abs=spread_abs,
        spread_pct=spread_pct,
        volume_24h=volume_24h,
    )


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
