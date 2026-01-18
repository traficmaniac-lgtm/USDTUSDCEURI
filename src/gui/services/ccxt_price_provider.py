"""CCXT price provider for real exchange quotes."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import ccxt
from loguru import logger


@dataclass(frozen=True)
class ExchangeDefinition:
    """Mapping between display name and ccxt exchange id."""

    name: str
    ccxt_id: str


class CcxtPriceProvider:
    """Fetch quotes from top exchanges via ccxt."""

    DEFAULT_PAIR = "USDT/USDC"
    REVERSE_PAIR = "USDC/USDT"
    NO_SYMBOL_COOLDOWN = timedelta(seconds=60)
    ERROR_COOLDOWN = timedelta(seconds=12)
    MARKET_WARMUP_WORKERS = 2
    _EXCHANGES = [
        ExchangeDefinition("Binance", "binance"),
        ExchangeDefinition("Coinbase", "coinbase"),
        ExchangeDefinition("Kraken", "kraken"),
        ExchangeDefinition("Bybit", "bybit"),
        ExchangeDefinition("OKX", "okx"),
        ExchangeDefinition("KuCoin", "kucoin"),
        ExchangeDefinition("Bitfinex", "bitfinex"),
        ExchangeDefinition("Gate.io", "gate"),
        ExchangeDefinition("Bitget", "bitget"),
        ExchangeDefinition("HTX", "htx"),
    ]

    def __init__(self) -> None:
        self._exchanges: dict[str, ccxt.Exchange] = {}
        for definition in self._EXCHANGES:
            exchange_class = getattr(ccxt, definition.ccxt_id)
            self._exchanges[definition.name] = exchange_class({"enableRateLimit": True})
        self._markets_loaded: set[str] = set()
        self._market_futures: dict[str, Future[None]] = {}
        self._market_loading_since: dict[str, datetime] = {}
        self._market_retry_after: dict[str, datetime] = {}
        self._market_last_error: dict[str, str] = {}
        self._symbol_cache: dict[str, str] = {}
        self._no_symbol_until: dict[str, datetime] = {}
        self._error_cooldown_until: dict[str, datetime] = {}
        self._last_error: dict[str, str] = {}
        self._last_error_logged_at: dict[str, datetime] = {}
        self._executor = ThreadPoolExecutor(max_workers=self.MARKET_WARMUP_WORKERS)

    def supported_exchanges(self) -> list[str]:
        return [definition.name for definition in self._EXCHANGES]

    def resolve_symbol(self, exchange_name: str, pair: str) -> tuple[str | None, str | None]:
        """Resolve the exchange-specific symbol for a given pair."""
        exchange = self._exchanges.get(exchange_name)
        if exchange is None:
            return None, "Unsupported exchange"
        now = datetime.now()
        if exchange_name not in self._markets_loaded:
            try:
                exchange.load_markets()
            except ccxt.BaseError as exc:
                message = str(exc)
                self._error_cooldown_until[exchange_name] = now + self.ERROR_COOLDOWN
                self._log_exchange_error(exchange_name, message)
                return None, message
            self._markets_loaded.add(exchange_name)
        symbol, status, error = self._resolve_symbol(exchange_name, exchange, pair, now)
        if status in {"ERROR", "NO_SYMBOL"} or not symbol:
            return None, error or "Symbol resolution error"
        return symbol, None

    def resolve_symbol_for_exchange(
        self,
        exchange_name: str,
        pair: str,
    ) -> tuple[str | None, bool, str | None]:
        """Resolve the symbol and whether the stable pair is reversed."""
        exchange = self._exchanges.get(exchange_name)
        if exchange is None:
            return None, False, "Unsupported exchange"
        now = datetime.now()
        if exchange_name not in self._markets_loaded:
            try:
                exchange.load_markets()
            except ccxt.BaseError as exc:
                message = str(exc)
                self._error_cooldown_until[exchange_name] = now + self.ERROR_COOLDOWN
                self._log_exchange_error(exchange_name, message)
                return None, False, message
            self._markets_loaded.add(exchange_name)
        symbol, status, error = self._resolve_symbol(exchange_name, exchange, pair, now)
        if status in {"ERROR", "NO_SYMBOL"} or not symbol:
            return None, False, error or "Symbol resolution error"
        return symbol, symbol == self.REVERSE_PAIR, None

    def fetch_quotes(self, pair: str, exchanges: list[str]) -> list[dict[str, Any]]:
        self._poll_market_futures()
        now = datetime.now()
        timestamp = now.strftime("%H:%M:%S")
        quotes: list[dict[str, Any]] = []
        for exchange_name in exchanges:
            exchange = self._exchanges.get(exchange_name)
            if exchange is None:
                quotes.append(
                    self._format_quote(
                        exchange_name,
                        pair,
                        timestamp,
                        status="ERROR",
                        error="Unsupported exchange",
                    )
                )
                continue

            try:
                if exchange_name not in self._markets_loaded:
                    status, error = self._ensure_markets_async(exchange_name, exchange, now)
                    quotes.append(
                        self._format_quote(
                            exchange_name,
                            pair,
                            timestamp,
                            status=status,
                            error=error,
                        )
                    )
                    continue

                cooldown_message = self._cooldown_message(exchange_name, now)
                if cooldown_message:
                    quotes.append(
                        self._format_quote(
                            exchange_name,
                            pair,
                            timestamp,
                            status="ERROR",
                            error=cooldown_message,
                        )
                    )
                    continue

                symbol, status, error = self._resolve_symbol(exchange_name, exchange, pair, now)
                if status == "NO_SYMBOL":
                    quotes.append(
                        self._format_quote(
                            exchange_name,
                            pair,
                            timestamp,
                            status="NO_SYMBOL",
                            error=error or f"{pair} not listed",
                        )
                    )
                    continue
                if status == "ERROR" or not symbol:
                    quotes.append(
                        self._format_quote(
                            exchange_name,
                            pair,
                            timestamp,
                            status="ERROR",
                            error=error or "Symbol resolution error",
                        )
                    )
                    continue

                ticker = exchange.fetch_ticker(symbol)
                bid = float(ticker.get("bid") or 0.0)
                ask = float(ticker.get("ask") or 0.0)
                last = float(ticker.get("last") or 0.0)
                spread = (ask - bid) if bid and ask else 0.0
                quotes.append(
                    self._format_quote(
                        exchange_name,
                        symbol,
                        timestamp,
                        bid=bid,
                        ask=ask,
                        last=last,
                        spread=spread,
                        status="OK",
                    )
                )
            except ccxt.BaseError as exc:
                message = str(exc)
                self._error_cooldown_until[exchange_name] = now + self.ERROR_COOLDOWN
                self._log_exchange_error(exchange_name, message)
                status = "TIMEOUT" if isinstance(exc, ccxt.RequestTimeout) else "ERROR"
                quotes.append(
                    self._format_quote(
                        exchange_name,
                        pair,
                        timestamp,
                        status=status,
                        error=message,
                    )
                )
        return quotes

    def _poll_market_futures(self) -> None:
        for exchange_name, future in list(self._market_futures.items()):
            if not future.done():
                continue
            self._market_futures.pop(exchange_name, None)
            self._market_loading_since.pop(exchange_name, None)
            exc = future.exception()
            if exc:
                message = str(exc)
                self._market_last_error[exchange_name] = message
                self._market_retry_after[exchange_name] = datetime.now() + self.ERROR_COOLDOWN
                self._error_cooldown_until[exchange_name] = datetime.now() + self.ERROR_COOLDOWN
                self._log_exchange_error(exchange_name, message)
                continue
            self._markets_loaded.add(exchange_name)
            self._market_last_error.pop(exchange_name, None)
            self._market_retry_after.pop(exchange_name, None)

    def _ensure_markets_async(
        self,
        exchange_name: str,
        exchange: ccxt.Exchange,
        now: datetime,
    ) -> tuple[str, str | None]:
        retry_after = self._market_retry_after.get(exchange_name)
        if retry_after and now < retry_after:
            error = self._market_last_error.get(exchange_name, "Market warmup cooldown")
            return "ERROR", error

        future = self._market_futures.get(exchange_name)
        if future and not future.done():
            return "WARMING_UP", "Loading markets"

        if exchange_name not in self._market_futures:
            self._market_loading_since[exchange_name] = now
            self._market_futures[exchange_name] = self._executor.submit(exchange.load_markets)
        return "LOADING", "Loading markets"

    def _resolve_symbol(
        self,
        exchange_name: str,
        exchange: ccxt.Exchange,
        pair: str,
        now: datetime,
    ) -> tuple[str | None, str | None, str | None]:
        if pair not in {self.DEFAULT_PAIR, self.REVERSE_PAIR}:
            if pair in exchange.symbols:
                return pair, None, None
            return None, "NO_SYMBOL", f"{pair} not listed"

        cached = self._symbol_cache.get(exchange_name)
        if cached:
            return cached, None, None

        next_check = self._no_symbol_until.get(exchange_name)
        if next_check and now < next_check:
            return None, "NO_SYMBOL", "Symbol cooldown active"

        for candidate in (self.DEFAULT_PAIR, self.REVERSE_PAIR):
            if candidate in exchange.symbols:
                self._symbol_cache[exchange_name] = candidate
                return candidate, None, None

        self._no_symbol_until[exchange_name] = now + self.NO_SYMBOL_COOLDOWN
        return None, "NO_SYMBOL", f"{self.DEFAULT_PAIR} not listed"

    def _cooldown_message(self, exchange_name: str, now: datetime) -> str | None:
        cooldown_until = self._error_cooldown_until.get(exchange_name)
        if cooldown_until and now < cooldown_until:
            remaining = int((cooldown_until - now).total_seconds())
            last_error = self._last_error.get(exchange_name, "Cooldown")
            return f"{last_error} (cooldown {remaining}s)"
        return None

    def _log_exchange_error(self, exchange_name: str, message: str) -> None:
        last_message = self._last_error.get(exchange_name)
        last_logged_at = self._last_error_logged_at.get(exchange_name)
        now = datetime.now()
        if message != last_message or not last_logged_at or now - last_logged_at > timedelta(seconds=60):
            logger.warning("CCXT error for {}: {}", exchange_name, message)
            self._last_error[exchange_name] = message
            self._last_error_logged_at[exchange_name] = now

    @staticmethod
    def _format_quote(
        exchange_name: str,
        pair: str,
        timestamp: str,
        bid: float = 0.0,
        ask: float = 0.0,
        last: float = 0.0,
        spread: float = 0.0,
        status: str = "ERROR",
        error: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "exchange": exchange_name,
            "bid": bid,
            "ask": ask,
            "last": last,
            "spread": spread,
            "timestamp": timestamp,
            "status": status,
            "pair": pair,
            "source": "HTTP",
        }
        if error:
            payload["error"] = error
        return payload
