"""WebSocket provider for Gate.io quotes."""

from __future__ import annotations

import json
import time
from typing import Callable

import websocket

from .ws_base import WsProviderBase


class GateWsProvider(WsProviderBase):
    """Threaded WebSocket worker for Gate.io ticker updates."""

    ENABLED = True
    STREAM_URL = "wss://api.gateio.ws/ws/v4/"

    def __init__(
        self,
        symbol: str,
        on_quote: Callable[[dict[str, object]], None],
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(
            exchange_name="Gate.io",
            resolved_symbol=symbol,
            on_quote=on_quote,
            on_error=on_error,
        )

    @staticmethod
    def stream_symbol(symbol: str) -> str:
        return symbol.replace("/", "_")

    def _format_gate_timestamp(self, timestamp: int | str | None) -> str:
        if not timestamp:
            return self._format_timestamp(None)
        try:
            ts_value = int(timestamp)
        except (TypeError, ValueError):
            return self._format_timestamp(None)
        if ts_value < 1_000_000_000_000:
            ts_value *= 1000
        return self._format_timestamp(ts_value)

    def run(self) -> None:
        pair = self.stream_symbol(self.resolved_symbol)

        def on_open(ws: websocket.WebSocketApp) -> None:
            self._log_connected()
            subscribe = {
                "time": int(time.time()),
                "channel": "spot.tickers",
                "event": "subscribe",
                "payload": [pair],
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
            if payload.get("event") != "update" or payload.get("channel") != "spot.tickers":
                return
            data = payload.get("result") or payload.get("data") or {}
            bid = data.get("highest_bid") or data.get("bid")
            ask = data.get("lowest_ask") or data.get("ask")
            last = data.get("last")
            if bid is None or ask is None or last is None:
                return
            try:
                bid_value = float(bid)
                ask_value = float(ask)
                last_value = float(last)
            except (TypeError, ValueError):
                return
            timestamp = self._format_gate_timestamp(payload.get("time") or data.get("time"))
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
