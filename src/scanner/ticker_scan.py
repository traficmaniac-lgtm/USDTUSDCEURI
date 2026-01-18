"""Ticker scan service for scanner mode."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from statistics import median
import time
from typing import Iterable

import ccxt

from ..core.update_controller import http_slot

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
    skipped_count: int
    ok_count: int
    fail_count: int
    errors: list[str]


@dataclass(frozen=True)
class PairExchangeTicker:
    """Ticker snapshot for a single exchange in pair analysis."""

    exchange: str
    bid: float | None
    ask: float | None
    volume_24h: float | None
    status: str


EXCHANGE_MAP = {
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


class TickerScanService:
    """Service that fetches tickers and computes spreads."""

    _default_outlier_pct = 5.0
    _exchange_map = EXCHANGE_MAP
    _timeout_ms = 10_000
    _min_symbol_refresh_s = 4.0
    _symbol_batch_size = 60
    _symbol_last_fetch: dict[tuple[str, str], float] = {}
    _exchange_offsets: dict[str, int] = {}

    def scan(
        self,
        pair_exchanges: dict[str, list[str]],
        max_pairs: int,
        pairs: list[str] | None = None,
        max_intrabook_spread_pct: float | None = None,
        outlier_pct: float | None = None,
    ) -> TickerScanResult:
        """Fetch tickers for the given pairs and compute spreads."""
        now = time.monotonic()
        if pairs is None:
            pairs_to_scan = sorted(pair_exchanges.keys())[:max_pairs]
        else:
            pairs_to_scan = list(pairs)[:max_pairs]
        if outlier_pct is None:
            outlier_pct = self._default_outlier_pct
        exchanges_cache: dict[str, ccxt.Exchange] = {}
        exchange_symbols: dict[str, set[str]] = {}
        ticker_map: dict[tuple[str, str], dict] = {}
        updates: list[TickerScanUpdate] = []
        errors: list[str] = []
        ok_count = 0
        fail_count = 0
        skipped_count = 0

        for pair in pairs_to_scan:
            for exchange_label in pair_exchanges.get(pair, []):
                exchange_symbols.setdefault(exchange_label, set()).add(pair)

        for exchange_label, symbols in exchange_symbols.items():
            exchange_id = self._exchange_map.get(exchange_label, exchange_label.lower())
            if not hasattr(ccxt, exchange_id):
                continue
            exchange = exchanges_cache.get(exchange_id)
            if exchange is None:
                exchange = getattr(ccxt, exchange_id)(
                    {"enableRateLimit": True, "timeout": self._timeout_ms}
                )
                if exchange_id == "binance":
                    options = getattr(exchange, "options", None)
                    if not isinstance(options, dict):
                        exchange.options = {}
                    exchange.options["defaultType"] = "spot"
                exchanges_cache[exchange_id] = exchange
            symbol_list = sorted(symbols)
            due_symbols = [
                symbol
                for symbol in symbol_list
                if self._is_symbol_due(exchange_label, symbol, now)
            ]
            if exchange.has.get("fetchTickers"):
                if not due_symbols:
                    continue
                try:
                    with http_slot():
                        tickers = exchange.fetch_tickers(due_symbols)
                except Exception as exc:  # noqa: BLE001 - per-exchange errors are expected
                    fail_count += 1
                    message = f"Ticker error: {exchange_label} batch: {exc}"
                    errors.append(message)
                    logger.warning(message)
                    continue
                for symbol in due_symbols:
                    ticker = tickers.get(symbol)
                    if ticker is None:
                        continue
                    self._mark_symbol_fetched(exchange_label, symbol, now)
                    ticker_map[(symbol, exchange_label)] = ticker
                    ok_count += 1
                continue

            batch = self._select_symbol_batch(exchange_label, due_symbols)
            if not batch:
                continue
            for symbol in batch:
                try:
                    with http_slot():
                        ticker = exchange.fetch_ticker(symbol)
                    ok_count += 1
                except Exception as exc:  # noqa: BLE001 - per-exchange errors are expected
                    fail_count += 1
                    message = f"Ticker error: {exchange_label} {symbol}: {exc}"
                    errors.append(message)
                    logger.warning(message)
                    continue
                self._mark_symbol_fetched(exchange_label, symbol, now)
                ticker_map[(symbol, exchange_label)] = ticker

        for pair in pairs_to_scan:
            entries: list[tuple[str, float, float, float, float | None]] = []
            for exchange_label in pair_exchanges.get(pair, []):
                ticker = ticker_map.get((pair, exchange_label))
                if ticker is None:
                    continue
                bid = _as_float(ticker.get("bid"))
                ask = _as_float(ticker.get("ask"))
                if bid is None or ask is None or bid <= 0 or ask <= 0:
                    continue
                mid = (bid + ask) / 2
                if max_intrabook_spread_pct is not None:
                    intrabook = (ask - bid) / mid * 100
                    if intrabook > max_intrabook_spread_pct:
                        continue
                volume = _pick_volume(ticker)
                entries.append((exchange_label, bid, ask, mid, volume))

            if len(entries) < 2:
                skipped_count += 1
                continue

            mids = [entry[3] for entry in entries]
            median_mid = median(mids)
            valid_entries: list[tuple[str, float, float, float, float | None]] = []
            for entry in entries:
                mid = entry[3]
                if abs(mid - median_mid) / median_mid * 100 > outlier_pct:
                    continue
                valid_entries.append(entry)

            if len(valid_entries) < 2:
                skipped_count += 1
                continue

            asks: list[tuple[float, str]] = []
            bids: list[tuple[float, str]] = []
            volumes: list[float] = []
            for exchange_label, bid, ask, _mid, volume in valid_entries:
                bids.append((bid, exchange_label))
                asks.append((ask, exchange_label))
                if volume is not None:
                    volumes.append(volume)

            update = _build_update(pair, bids, asks, volumes)
            updates.append(update)

        return TickerScanResult(
            updates=updates,
            pair_count=len(pairs_to_scan),
            skipped_count=skipped_count,
            ok_count=ok_count,
            fail_count=fail_count,
            errors=errors,
        )

    def fetch_pair_tickers(
        self, pair: str, exchanges: Iterable[str]
    ) -> tuple[list[PairExchangeTicker], list[str]]:
        """Fetch tickers for a single pair across the selected exchanges."""
        entries: list[PairExchangeTicker] = []
        errors: list[str] = []
        exchanges_cache: dict[str, ccxt.Exchange] = {}
        now = time.monotonic()
        for exchange_label in exchanges:
            exchange_id = self._exchange_map.get(exchange_label, exchange_label.lower())
            if not hasattr(ccxt, exchange_id):
                errors.append(f"Exchange not found: {exchange_label}")
                entries.append(
                    PairExchangeTicker(
                        exchange=exchange_label,
                        bid=None,
                        ask=None,
                        volume_24h=None,
                        status="NO API",
                    )
                )
                continue
            exchange = exchanges_cache.get(exchange_id)
            if exchange is None:
                exchange = getattr(ccxt, exchange_id)(
                    {"enableRateLimit": True, "timeout": self._timeout_ms}
                )
                if exchange_id == "binance":
                    options = getattr(exchange, "options", None)
                    if not isinstance(options, dict):
                        exchange.options = {}
                    exchange.options["defaultType"] = "spot"
                exchanges_cache[exchange_id] = exchange
            try:
                with http_slot():
                    ticker = exchange.fetch_ticker(pair)
            except Exception as exc:  # noqa: BLE001 - per-exchange errors are expected
                message = f"Ticker error: {exchange_label} {pair}: {exc}"
                errors.append(message)
                logger.warning(message)
                entries.append(
                    PairExchangeTicker(
                        exchange=exchange_label,
                        bid=None,
                        ask=None,
                        volume_24h=None,
                        status="ERR",
                    )
                )
                continue
            self._mark_symbol_fetched(exchange_label, pair, now)
            bid = _as_float(ticker.get("bid"))
            ask = _as_float(ticker.get("ask"))
            volume = _pick_volume(ticker)
            status = "OK"
            if bid is None or ask is None or bid <= 0 or ask <= 0:
                status = "NO DATA"
            entries.append(
                PairExchangeTicker(
                    exchange=exchange_label,
                    bid=bid,
                    ask=ask,
                    volume_24h=volume,
                    status=status,
                )
            )
        return entries, errors

    def _is_symbol_due(self, exchange_label: str, symbol: str, now: float) -> bool:
        last_ts = self._symbol_last_fetch.get((exchange_label, symbol))
        if last_ts is None:
            return True
        return (now - last_ts) >= self._min_symbol_refresh_s

    def _mark_symbol_fetched(self, exchange_label: str, symbol: str, now: float) -> None:
        self._symbol_last_fetch[(exchange_label, symbol)] = now

    def _select_symbol_batch(self, exchange_label: str, symbols: list[str]) -> list[str]:
        if not symbols:
            return []
        if len(symbols) <= self._symbol_batch_size:
            return symbols
        offset = self._exchange_offsets.get(exchange_label, 0)
        batch = symbols[offset : offset + self._symbol_batch_size]
        if not batch:
            offset = 0
            batch = symbols[: self._symbol_batch_size]
        next_offset = offset + self._symbol_batch_size
        if next_offset >= len(symbols):
            next_offset = 0
        self._exchange_offsets[exchange_label] = next_offset
        return batch


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
