"""Base WebSocket provider interface and helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
import threading
from typing import Callable

from loguru import logger
import websocket

QuoteCallback = Callable[[dict[str, object]], None]
ErrorCallback = Callable[[str], None]


class WsProviderBase(threading.Thread):
    """Threaded base class for WebSocket providers."""

    LOG_INTERVAL = timedelta(seconds=30)
    ENABLED = True

    def __init__(
        self,
        exchange_name: str,
        resolved_symbol: str,
        on_quote: QuoteCallback,
        on_error: ErrorCallback | None = None,
    ) -> None:
        super().__init__(daemon=True)
        self.exchange_name = exchange_name
        self.resolved_symbol = resolved_symbol
        self._on_quote = on_quote
        self._on_error = on_error
        self._stop_event = threading.Event()
        self._ws: websocket.WebSocketApp | None = None
        self._error_logged = False
        self._connected_logged = False
        self._disconnected_logged = False
        self._updates_count = 0
        self._last_log_at = datetime.now()

    def stop(self) -> None:
        self._stop_event.set()
        if self._ws:
            self._ws.close()

    def _log_connected(self) -> None:
        if self._connected_logged:
            return
        logger.info("{} WS connected", self.exchange_name)
        self._connected_logged = True

    def _log_disconnected(self) -> None:
        if self._disconnected_logged:
            return
        logger.info("{} WS disconnected", self.exchange_name)
        self._disconnected_logged = True

    def _emit_error(self, error: object) -> None:
        if self._error_logged:
            return
        logger.warning("{} WS error (once): {}", self.exchange_name, error)
        self._error_logged = True
        if self._on_error:
            self._on_error(str(error))

    def _emit_quote(
        self,
        bid: float,
        ask: float,
        last: float,
        timestamp: str | None = None,
        status: str = "OK",
        error: str | None = None,
    ) -> None:
        if timestamp is None:
            timestamp = datetime.now().strftime("%H:%M:%S")
        spread = ask - bid if bid and ask else 0.0
        quote: dict[str, object] = {
            "exchange": self.exchange_name,
            "bid": bid,
            "ask": ask,
            "last": last,
            "spread": spread,
            "timestamp": timestamp,
            "status": status,
            "source": "WS",
        }
        if error:
            quote["error"] = error
        self._updates_count += 1
        now = datetime.now()
        if now - self._last_log_at >= self.LOG_INTERVAL:
            logger.info("{} WS updates count | {}", self.exchange_name, self._updates_count)
            self._last_log_at = now
        self._on_quote(quote)

    @staticmethod
    def _format_timestamp(ms_timestamp: str | int | None) -> str:
        if not ms_timestamp:
            return datetime.now().strftime("%H:%M:%S")
        try:
            timestamp_ms = int(ms_timestamp)
        except (TypeError, ValueError):
            return datetime.now().strftime("%H:%M:%S")
        return datetime.fromtimestamp(timestamp_ms / 1000).strftime("%H:%M:%S")
