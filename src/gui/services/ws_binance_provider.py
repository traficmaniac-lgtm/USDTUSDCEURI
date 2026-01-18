"""WebSocket provider for Binance quotes."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import threading
from typing import Callable

from loguru import logger
import websocket


class BinanceWsProvider(threading.Thread):
    """Threaded WebSocket worker for Binance ticker updates."""

    STREAM_URL = "wss://stream.binance.com:9443/ws/{}@ticker"
    LOG_INTERVAL = timedelta(seconds=5)

    def __init__(
        self,
        symbol: str,
        on_quote: Callable[[dict[str, object]], None],
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(daemon=True)
        self._symbol = symbol
        self._on_quote = on_quote
        self._on_error = on_error
        self._stop_event = threading.Event()
        self._ws: websocket.WebSocketApp | None = None
        self._error_logged = False
        self._updates_count = 0
        self._last_log_at = datetime.now()

    @staticmethod
    def stream_symbol(symbol: str) -> str:
        return symbol.replace("/", "").lower()

    def stop(self) -> None:
        self._stop_event.set()
        if self._ws:
            self._ws.close()

    def run(self) -> None:
        stream_name = self.stream_symbol(self._symbol)
        url = self.STREAM_URL.format(stream_name)

        def on_open(_ws: websocket.WebSocketApp) -> None:
            logger.info("WS connected")

        def on_close(_ws: websocket.WebSocketApp, _status: int, _message: str) -> None:
            logger.info("WS disconnected")

        def on_error(_ws: websocket.WebSocketApp, error: object) -> None:
            if not self._error_logged:
                logger.warning("WS error (once): {}", error)
                self._error_logged = True
                if self._on_error:
                    self._on_error(str(error))

        def on_message(_ws: websocket.WebSocketApp, message: str) -> None:
            if self._stop_event.is_set():
                return
            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                return
            bid = payload.get("b")
            ask = payload.get("a")
            last = payload.get("c")
            event_time = payload.get("E")
            if bid is None or ask is None or last is None:
                return
            try:
                bid_value = float(bid)
                ask_value = float(ask)
                last_value = float(last)
            except (TypeError, ValueError):
                return
            spread = ask_value - bid_value if bid_value and ask_value else 0.0
            if event_time:
                timestamp = datetime.fromtimestamp(event_time / 1000).strftime("%H:%M:%S")
            else:
                timestamp = datetime.now().strftime("%H:%M:%S")
            quote = {
                "exchange": "Binance",
                "bid": bid_value,
                "ask": ask_value,
                "last": last_value,
                "spread": spread,
                "timestamp": timestamp,
                "status": "OK",
            }
            self._updates_count += 1
            now = datetime.now()
            if now - self._last_log_at >= self.LOG_INTERVAL:
                logger.info("WS updates count | {}", self._updates_count)
                self._last_log_at = now
            self._on_quote(quote)

        self._ws = websocket.WebSocketApp(
            url,
            on_open=on_open,
            on_close=on_close,
            on_error=on_error,
            on_message=on_message,
        )
        self._ws.run_forever(ping_interval=20, ping_timeout=10)
