"""WebSocket provider for Kraken quotes."""

from __future__ import annotations

import json
from typing import Callable

import websocket

from .ws_base import WsProviderBase


class KrakenWsProvider(WsProviderBase):
    """Threaded WebSocket worker for Kraken ticker updates."""

    ENABLED = True
    STREAM_URL = "wss://ws.kraken.com"

    def __init__(
        self,
        symbol: str,
        on_quote: Callable[[dict[str, object]], None],
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(
            exchange_name="Kraken",
            resolved_symbol=symbol,
            on_quote=on_quote,
            on_error=on_error,
        )

    @staticmethod
    def stream_symbol(symbol: str) -> str:
        if "/" in symbol:
            base, quote = symbol.split("/", maxsplit=1)
        else:
            base, quote = symbol[:3], symbol[3:]
        if base.upper() == "BTC":
            base = "XBT"
        return f"{base.upper()}/{quote.upper()}"

    def run(self) -> None:
        stream_name = self.stream_symbol(self.resolved_symbol)

        def on_open(ws: websocket.WebSocketApp) -> None:
            self._log_connected()
            subscribe = {
                "event": "subscribe",
                "pair": [stream_name],
                "subscription": {"name": "ticker"},
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
            if isinstance(payload, dict):
                if payload.get("event") == "error":
                    self._emit_error(payload.get("errorMessage", "Kraken WS error"))
                return
            if not isinstance(payload, list) or len(payload) < 2:
                return
            data = payload[1]
            if not isinstance(data, dict):
                return
            ask = (data.get("a") or [None])[0]
            bid = (data.get("b") or [None])[0]
            last = (data.get("c") or [None])[0]
            if bid is None or ask is None or last is None:
                return
            try:
                bid_value = float(bid)
                ask_value = float(ask)
                last_value = float(last)
            except (TypeError, ValueError):
                return
            timestamp = self._format_timestamp(None)
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
