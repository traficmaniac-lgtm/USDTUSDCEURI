"""WebSocket stub provider for Bitget."""

from __future__ import annotations

from typing import Callable

from loguru import logger

from .ws_base import WsProviderBase


class BitgetWsProvider(WsProviderBase):
    """Stub WebSocket provider for Bitget (not implemented)."""

    ENABLED = False

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

    def run(self) -> None:
        logger.info("{} WS not implemented yet", self.exchange_name)
        self._emit_quote(
            bid=0.0,
            ask=0.0,
            last=0.0,
            status="HTTP_ONLY",
            error="WS not implemented yet",
        )
