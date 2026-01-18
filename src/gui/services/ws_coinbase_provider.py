"""WebSocket provider for Coinbase quotes."""

from __future__ import annotations

from datetime import datetime
import json
from typing import Callable

import websocket

from .ws_base import WsProviderBase


class CoinbaseWsProvider(WsProviderBase):
    """Threaded WebSocket worker for Coinbase ticker updates."""

    ENABLED = True
    STREAM_URL = "wss://ws-feed.exchange.coinbase.com"

    def __init__(
        self,
        symbol: str,
        on_quote: Callable[[dict[str, object]], None],
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(
            exchange_name="Coinbase",
            resolved_symbol=symbol,
            on_quote=on_quote,
            on_error=on_error,
        )

    @staticmethod
    def stream_symbol(symbol: str) -> str:
        return symbol.replace("/", "-")

    @staticmethod
    def _format_iso_timestamp(timestamp: str | None) -> str:
        if not timestamp:
            return datetime.now().strftime("%H:%M:%S")
        try:
            normalized = timestamp.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return datetime.now().strftime("%H:%M:%S")
        return parsed.strftime("%H:%M:%S")

    def run(self) -> None:
        product_id = self.stream_symbol(self.resolved_symbol)

        def on_open(ws: websocket.WebSocketApp) -> None:
            self._log_connected()
            subscribe = {
                "type": "subscribe",
                "channels": [{"name": "ticker", "product_ids": [product_id]}],
            }
            ws.send(json.dumps(subscribe))

        def on_close(_ws: websocket.WebSocketApp, _status: int, _message: str) -> None:
            self._log_disconnected()

        def on_error(_ws: websocket.WebSocketApp, error: object) -> None:
            self._emit_error(error)

        def on_message(_ws: websocket.WebSocketApp, message: str) -> None:
            if self._stop_event.is_set():
                return
            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                return
            if payload.get("type") != "ticker":
                return
            bid = payload.get("best_bid")
            ask = payload.get("best_ask")
            last = payload.get("price")
            if bid is None or ask is None or last is None:
                return
            try:
                bid_value = float(bid)
                ask_value = float(ask)
                last_value = float(last)
            except (TypeError, ValueError):
                return
            timestamp = self._format_iso_timestamp(payload.get("time"))
            self._emit_quote(
                bid=bid_value,
                ask=ask_value,
                last=last_value,
                timestamp=timestamp,
                status="OK",
            )

        self._ws = websocket.WebSocketApp(
            self.STREAM_URL,
            on_open=on_open,
            on_close=on_close,
            on_error=on_error,
            on_message=on_message,
        )
        self._ws.run_forever(ping_interval=20, ping_timeout=10)
