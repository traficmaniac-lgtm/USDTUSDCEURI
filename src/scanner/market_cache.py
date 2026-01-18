"""Local cache for market metadata used by scanner."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import Iterable


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarketCacheEntry:
    """Cached markets payload."""

    saved_at: str
    markets: list[dict]


class MarketCache:
    """Persist markets locally so scanner can reuse them between runs."""

    def __init__(self, base_dir: Path | None = None) -> None:
        if base_dir is None:
            base_dir = Path.home() / ".usdtusdceuri" / "market_cache"
        self._base_dir = base_dir
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def load(self, exchange_id: str) -> list[dict] | None:
        path = self._path_for(exchange_id)
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            markets = payload.get("markets")
            if isinstance(markets, list):
                return markets
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to load cached markets for %s: %s", exchange_id, exc)
        return None

    def save(self, exchange_id: str, markets: Iterable[dict], saved_at: str) -> None:
        path = self._path_for(exchange_id)
        payload = MarketCacheEntry(saved_at=saved_at, markets=list(markets))
        tmp_path = path.with_suffix(".tmp")
        try:
            with tmp_path.open("w", encoding="utf-8") as handle:
                json.dump(payload.__dict__, handle, ensure_ascii=False)
            tmp_path.replace(path)
        except OSError as exc:
            logger.warning("Failed to save cached markets for %s: %s", exchange_id, exc)

    def _path_for(self, exchange_id: str) -> Path:
        safe_name = "".join(
            char if (char.isalnum() or char in {"-", "_"}) else "_"
            for char in exchange_id.lower()
        )
        return self._base_dir / f"{safe_name}.json"
