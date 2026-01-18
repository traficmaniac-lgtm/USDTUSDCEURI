"""WebSocket provider for Bybit quotes."""

from __future__ import annotations

import json
from typing import Callable

import websocket

from .ws_base import WsProviderBase


class BybitWsProvider(WsProviderBase):
    """Threaded WebSocket worker for Bybit ticker updates."""

    STREAM_URL = "wss://stream.bybit.com/v5/public/spot"

    def __init__(
        self,
        symbol: str,
        on_quote: Callable[[dict[str, object]], None],
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(
            exchange_name="Bybit",
            resolved_symbol=symbol,
            on_quote=on_quote,
            on_error=on_error,
        )

    @staticmethod
    def stream_symbol(symbol: str) -> str:
        return symbol.replace("/", "")

    def run(self) -> None:
        topic = f"tickers.{self.stream_symbol(self.resolved_symbol)}"

        def on_open(ws: websocket.WebSocketApp) -> None:
            self._log_connected()
            subscribe = {"op": "subscribe", "args": [topic]}
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
            data = payload.get("data")
            if not data:
                return
            bid = data.get("bid1Price")
            ask = data.get("ask1Price")
            last = data.get("lastPrice")
            if bid is None or ask is None or last is None:
                return
            try:
                bid_value = float(bid)
                ask_value = float(ask)
                last_value = float(last)
            except (TypeError, ValueError):
                return
            timestamp = self._format_timestamp(data.get("ts") or payload.get("ts"))
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
