"""WebSocket manager to orchestrate exchange providers."""

from __future__ import annotations

from typing import Callable

from loguru import logger

from .ccxt_price_provider import CcxtPriceProvider
from .ws_base import WsProviderBase
from .ws_binance_provider import BinanceWsProvider
from .ws_bitfinex_provider import BitfinexWsProvider
from .ws_bitget_provider import BitgetWsProvider
from .ws_bybit_provider import BybitWsProvider
from .ws_coinbase_provider import CoinbaseWsProvider
from .ws_gate_provider import GateWsProvider
from .ws_htx_provider import HtxWsProvider
from .ws_kraken_provider import KrakenWsProvider
from .ws_kucoin_provider import KuCoinWsProvider
from .ws_okx_provider import OkxWsProvider


class WsManager:
    """Starts and stops WebSocket providers per exchange selection."""

    _PROVIDERS: dict[str, type[WsProviderBase]] = {
        "Binance": BinanceWsProvider,
        "Bybit": BybitWsProvider,
        "OKX": OkxWsProvider,
        "Coinbase": CoinbaseWsProvider,
        "Kraken": KrakenWsProvider,
        "KuCoin": KuCoinWsProvider,
        "Gate.io": GateWsProvider,
        "Bitget": BitgetWsProvider,
        "HTX": HtxWsProvider,
        "Bitfinex": BitfinexWsProvider,
    }

    def __init__(
        self,
        price_provider: CcxtPriceProvider,
        on_quote: Callable[[dict[str, object]], None],
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self._price_provider = price_provider
        self._on_quote = on_quote
        self._on_error = on_error
        self._providers: dict[str, WsProviderBase] = {}

    def supports_exchange(self, exchange_name: str) -> bool:
        provider = self._PROVIDERS.get(exchange_name)
        return bool(provider and provider.ENABLED)

    def start_for_selected_exchanges(self, pair: str, exchanges: list[str]) -> None:
        self.stop_all()
        for exchange_name in exchanges:
            provider_cls = self._PROVIDERS.get(exchange_name)
            if not provider_cls or not provider_cls.ENABLED:
                continue
            symbol, _is_reverse, error = self._price_provider.resolve_symbol_for_exchange(exchange_name, pair)
            if not symbol:
                if error:
                    logger.warning("{} WS disabled | {}", exchange_name, error)
                continue
            provider = provider_cls(
                symbol=symbol,
                on_quote=self._on_quote,
                on_error=self._wrap_error(exchange_name),
            )
            self._providers[exchange_name] = provider
            provider.start()

    def stop_all(self) -> None:
        for provider in list(self._providers.values()):
            provider.stop()
            if hasattr(provider, "join"):
                provider.join(timeout=1)
        self._providers.clear()

    def _wrap_error(self, exchange_name: str):
        def _handler(message: str) -> None:
            provider = self._providers.pop(exchange_name, None)
            if provider:
                provider.stop()
            if self._on_error:
                self._on_error(f"{exchange_name}: {message}")

        return _handler
