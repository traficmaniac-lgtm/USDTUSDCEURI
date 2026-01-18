"""WebSocket provider for KuCoin quotes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import threading
import time
from typing import Callable

import httpx
import websocket

from .ws_base import WsProviderBase


@dataclass(frozen=True)
class KuCoinWsConfig:
    """Resolved KuCoin WS connection data."""

    endpoint: str
    token: str
    ping_interval: float


class KuCoinWsProvider(WsProviderBase):
    """Threaded WebSocket worker for KuCoin ticker updates."""

    ENABLED = True
    REST_ENDPOINT = "https://api.kucoin.com/api/v1/bullet-public"
    DEFAULT_PING_INTERVAL = 20.0
    COOLDOWN = timedelta(seconds=60)
    _cooldown_until: datetime | None = None
    _cooldown_logged_at: datetime | None = None

    def __init__(
        self,
        symbol: str,
        on_quote: Callable[[dict[str, object]], None],
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(
            exchange_name="KuCoin",
            resolved_symbol=symbol,
            on_quote=on_quote,
            on_error=on_error,
        )
        self._ping_thread: threading.Thread | None = None

    @staticmethod
    def stream_symbol(symbol: str) -> str:
        return symbol.replace("/", "-")

    def _fetch_ws_config(self) -> KuCoinWsConfig | None:
        try:
            response = httpx.post(
                self.REST_ENDPOINT,
                json={},
                headers={"accept": "application/json"},
                timeout=10,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            self._emit_error(exc)
            self._enter_cooldown(str(exc))
            return None
        data = response.json().get("data", {})
        token = data.get("token")
        servers = data.get("instanceServers") or []
        if not token or not servers:
            self._emit_error("KuCoin WS bootstrap missing token or server list")
            self._enter_cooldown("KuCoin WS bootstrap missing token or server list")
            return None
        server = servers[0]
        endpoint = server.get("endpoint")
        ping_interval = server.get("pingInterval")
        if not endpoint:
            self._emit_error("KuCoin WS bootstrap missing endpoint")
            self._enter_cooldown("KuCoin WS bootstrap missing endpoint")
            return None
        try:
            ping_seconds = float(ping_interval) / 1000 if ping_interval else self.DEFAULT_PING_INTERVAL
        except (TypeError, ValueError):
            ping_seconds = self.DEFAULT_PING_INTERVAL
        return KuCoinWsConfig(endpoint=endpoint, token=token, ping_interval=ping_seconds)

    def _enter_cooldown(self, reason: str) -> None:
        now = datetime.now()
        self.__class__._cooldown_until = now + self.COOLDOWN
        self._emit_quote(
            bid=0.0,
            ask=0.0,
            last=0.0,
            status="HTTP_ONLY",
            error=reason,
        )

    def _cooldown_active(self) -> bool:
        cooldown_until = self.__class__._cooldown_until
        if cooldown_until and datetime.now() < cooldown_until:
            return True
        return False

    def _start_ping_loop(self, ws: websocket.WebSocketApp, interval: float) -> None:
        def _ping_loop() -> None:
            while not self._stop_event.wait(interval):
                try:
                    ws.send(json.dumps({"id": str(int(time.time() * 1000)), "type": "ping"}))
                except websocket.WebSocketException:
                    break

        self._ping_thread = threading.Thread(target=_ping_loop, daemon=True)
        self._ping_thread.start()

    def run(self) -> None:
        if self._cooldown_active():
            remaining = int((self.__class__._cooldown_until - datetime.now()).total_seconds())
            message = f"KuCoin WS cooldown active ({remaining}s)"
            last_logged = self.__class__._cooldown_logged_at
            if not last_logged or (datetime.now() - last_logged) > timedelta(seconds=30):
                self.__class__._cooldown_logged_at = datetime.now()
                self._emit_error(message)
            self._emit_quote(
                bid=0.0,
                ask=0.0,
                last=0.0,
                status="HTTP_ONLY",
                error=message,
            )
            return
        config = self._fetch_ws_config()
        if not config:
            return
        stream_name = self.stream_symbol(self.resolved_symbol)
        url = f"{config.endpoint}?token={config.token}"

        def on_open(ws: websocket.WebSocketApp) -> None:
            self._log_connected()
            subscribe = {
                "id": str(int(time.time() * 1000)),
                "type": "subscribe",
                "topic": f"/market/ticker:{stream_name}",
                "privateChannel": False,
                "response": True,
            }
            ws.send(json.dumps(subscribe))
            self._start_ping_loop(ws, config.ping_interval)

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
            if payload.get("type") != "message":
                return
            data = payload.get("data") or {}
            bid = data.get("bestBid")
            ask = data.get("bestAsk")
            last = data.get("price")
            if bid is None or ask is None or last is None:
                return
            try:
                bid_value = float(bid)
                ask_value = float(ask)
                last_value = float(last)
            except (TypeError, ValueError):
                return
            timestamp = self._format_timestamp(data.get("time") or payload.get("ts"))
            self._emit_quote(
                bid=bid_value,
                ask=ask_value,
                last=last_value,
                timestamp=timestamp,
                status="OK",
            )

        self._ws = websocket.WebSocketApp(
            url,
            on_open=on_open,
            on_close=on_close,
            on_error=on_error,
            on_message=on_message,
        )
        self._ws.run_forever(ping_interval=20, ping_timeout=10)
