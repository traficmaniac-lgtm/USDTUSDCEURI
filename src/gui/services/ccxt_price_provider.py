"""CCXT price provider for real exchange quotes."""

from __future__ import annotations

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
        self._last_error: dict[str, str] = {}
        self._last_error_logged_at: dict[str, datetime] = {}

    def supported_exchanges(self) -> list[str]:
        return [definition.name for definition in self._EXCHANGES]

    def fetch_quotes(self, pair: str, exchanges: list[str]) -> list[dict[str, Any]]:
        timestamp = datetime.now().strftime("%H:%M:%S")
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
                self._ensure_markets(exchange_name, exchange)
                if pair not in exchange.symbols:
                    quotes.append(
                        self._format_quote(
                            exchange_name,
                            pair,
                            timestamp,
                            status="NO_SYMBOL",
                            error=f"{pair} not listed",
                        )
                    )
                    continue

                ticker = exchange.fetch_ticker(pair)
                bid = float(ticker.get("bid") or 0.0)
                ask = float(ticker.get("ask") or 0.0)
                last = float(ticker.get("last") or 0.0)
                spread = (ask - bid) if bid and ask else 0.0
                quotes.append(
                    self._format_quote(
                        exchange_name,
                        pair,
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
                self._log_exchange_error(exchange_name, message)
                quotes.append(
                    self._format_quote(
                        exchange_name,
                        pair,
                        timestamp,
                        status="ERROR",
                        error=message,
                    )
                )
        return quotes

    def _ensure_markets(self, exchange_name: str, exchange: ccxt.Exchange) -> None:
        if exchange_name in self._markets_loaded:
            return
        exchange.load_markets()
        self._markets_loaded.add(exchange_name)

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
        }
        if error:
            payload["error"] = error
        return payload
