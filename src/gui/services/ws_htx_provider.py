"""WebSocket provider for HTX quotes."""

from __future__ import annotations

from datetime import timedelta
import gzip
import json
from typing import Callable

import websocket

from .ws_base import WsProviderBase


class HtxWsProvider(WsProviderBase):
    """Threaded WebSocket worker for HTX ticker updates."""

    ENABLED = True
    LOG_INTERVAL = timedelta(seconds=10)
    STREAM_URL = "wss://api.htx.com/ws"

    def __init__(
        self,
        symbol: str,
        on_quote: Callable[[dict[str, object]], None],
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(
            exchange_name="HTX",
            resolved_symbol=symbol,
            on_quote=on_quote,
            on_error=on_error,
        )

    @staticmethod
    def stream_symbol(symbol: str) -> str:
        return symbol.replace("/", "").lower()

    def run(self) -> None:
        stream_symbol = self.stream_symbol(self.resolved_symbol)
        topic = f"market.{stream_symbol}.ticker"

        def on_open(ws: websocket.WebSocketApp) -> None:
            self._log_connected()
            subscribe = {"sub": topic, "id": stream_symbol}
            ws.send(json.dumps(subscribe))

        def on_close(_ws: websocket.WebSocketApp, _status: int, _message: str) -> None:
            self._log_disconnected()

        def on_error(_ws: websocket.WebSocketApp, error: object) -> None:
            self._emit_error(error)

        def on_message(ws: websocket.WebSocketApp, message: str | bytes) -> None:
            if self._stop_event.is_set():
                return
            if isinstance(message, bytes):
                try:
                    message = gzip.decompress(message).decode("utf-8")
                except (OSError, UnicodeDecodeError):
                    return
            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                return
            if "ping" in payload:
                ws.send(json.dumps({"pong": payload["ping"]}))
                return
            if payload.get("status") == "error":
                self._emit_error(payload.get("err-msg") or payload)
                return
            tick = payload.get("tick")
            if not tick:
                return
            bid = tick.get("bid")
            ask = tick.get("ask")
            last = tick.get("close") or tick.get("last")
            if isinstance(bid, (list, tuple)):
                bid = bid[0] if bid else None
            if isinstance(ask, (list, tuple)):
                ask = ask[0] if ask else None
            if bid is None or ask is None or last is None:
                return
            try:
                bid_value = float(bid)
                ask_value = float(ask)
                last_value = float(last)
            except (TypeError, ValueError):
                return
            timestamp = self._format_timestamp(payload.get("ts") or tick.get("ts"))
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
