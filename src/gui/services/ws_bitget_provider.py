"""WebSocket provider for Bitget quotes."""

from __future__ import annotations

from datetime import timedelta
import json
from typing import Callable

import websocket

from .ws_base import WsProviderBase


class BitgetWsProvider(WsProviderBase):
    """Threaded WebSocket worker for Bitget ticker updates."""

    ENABLED = True
    LOG_INTERVAL = timedelta(seconds=10)
    STREAM_URL = "wss://ws.bitget.com/spot/v1/stream"

    def __init__(
        self,
        symbol: str,
        on_quote: Callable[[dict[str, object]], None],
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(
            exchange_name="Bitget",
            resolved_symbol=symbol,
            on_quote=on_quote,
            on_error=on_error,
        )

    @staticmethod
    def stream_symbol(symbol: str) -> str:
        return symbol.replace("/", "")

    def run(self) -> None:
        inst_id = self.stream_symbol(self.resolved_symbol)

        def on_open(ws: websocket.WebSocketApp) -> None:
            self._log_connected()
            subscribe = {
                "op": "subscribe",
                "args": [{"instType": "SPOT", "channel": "ticker", "instId": inst_id}],
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
            if payload.get("event") == "error":
                self._emit_error(payload.get("message") or payload)
                return
            data = payload.get("data")
            if not data:
                return
            item = data[0] if isinstance(data, list) else data
            bid = item.get("bidPr") or item.get("bid")
            ask = item.get("askPr") or item.get("ask")
            last = item.get("lastPr") or item.get("last")
            if bid is None or ask is None or last is None:
                return
            try:
                bid_value = float(bid)
                ask_value = float(ask)
                last_value = float(last)
            except (TypeError, ValueError):
                return
            timestamp = self._format_timestamp(item.get("ts") or payload.get("ts"))
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
