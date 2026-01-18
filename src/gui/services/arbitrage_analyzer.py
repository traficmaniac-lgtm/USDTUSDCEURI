"""Arbitrage analyzer utilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class QuoteSnapshot:
    """Normalized quote snapshot used for arbitrage analysis."""

    exchange: str
    bid: float
    ask: float
    last: float
    status: str
    timestamp: str
    source: str


@dataclass(frozen=True)
class Opportunity:
    """Arbitrage opportunity between two exchanges."""

    buy_exchange: str
    buy_ask: float
    sell_exchange: str
    sell_bid: float
    spread_abs: float
    spread_pct: float


@dataclass(frozen=True)
class ArbitrageResult:
    """Aggregated arbitrage analysis output."""

    best_buy: QuoteSnapshot | None
    best_sell: QuoteSnapshot | None
    spread_abs: float
    spread_pct: float
    opportunities: list[Opportunity]


def analyze(
    quotes: Iterable[dict[str, object]],
    min_spread_pct: float = 0.0,
    only_ws: bool = False,
    top_n: int = 10,
) -> ArbitrageResult:
    """Analyze quotes and compute arbitrage opportunities."""
    valid_quotes = _filter_valid(quotes, only_ws=only_ws)
    if not valid_quotes:
        return ArbitrageResult(None, None, 0.0, 0.0, [])

    best_buy = min(valid_quotes, key=lambda quote: quote.ask)
    best_sell = max(valid_quotes, key=lambda quote: quote.bid)
    spread_abs = best_sell.bid - best_buy.ask
    spread_pct = (spread_abs / best_buy.ask * 100.0) if best_buy.ask else 0.0
    opportunities = _build_opportunities(valid_quotes, min_spread_pct=min_spread_pct, top_n=top_n)
    return ArbitrageResult(best_buy, best_sell, spread_abs, spread_pct, opportunities)


def _filter_valid(quotes: Iterable[dict[str, object]], only_ws: bool) -> list[QuoteSnapshot]:
    valid: list[QuoteSnapshot] = []
    for quote in quotes:
        status = str(quote.get("status", "")).upper()
        if status != "OK":
            continue
        bid = float(quote.get("bid", 0.0) or 0.0)
        ask = float(quote.get("ask", 0.0) or 0.0)
        if bid <= 0.0 or ask <= 0.0:
            continue
        source = str(quote.get("source", "HTTP") or "HTTP").upper()
        if only_ws and source != "WS":
            continue
        valid.append(
            QuoteSnapshot(
                exchange=str(quote.get("exchange", "")),
                bid=bid,
                ask=ask,
                last=float(quote.get("last", 0.0) or 0.0),
                status=status,
                timestamp=str(quote.get("timestamp", "")),
                source=source,
            )
        )
    return valid


def _build_opportunities(
    quotes: list[QuoteSnapshot],
    min_spread_pct: float,
    top_n: int,
) -> list[Opportunity]:
    opportunities: list[Opportunity] = []
    for buy in quotes:
        for sell in quotes:
            if buy.exchange == sell.exchange:
                continue
            spread_abs = sell.bid - buy.ask
            spread_pct = (spread_abs / buy.ask * 100.0) if buy.ask else 0.0
            if spread_pct < min_spread_pct:
                continue
            opportunities.append(
                Opportunity(
                    buy_exchange=buy.exchange,
                    buy_ask=buy.ask,
                    sell_exchange=sell.exchange,
                    sell_bid=sell.bid,
                    spread_abs=spread_abs,
                    spread_pct=spread_pct,
                )
            )
    opportunities.sort(key=lambda item: item.spread_pct, reverse=True)
    return opportunities[:top_n]
