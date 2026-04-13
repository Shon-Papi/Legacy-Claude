"""
Trade journal — append-only JSONL log of every signal, trade, and halt.

Each line is a self-contained JSON object with a 'type' field:
  SIGNAL  — a confluence result (whether or not a trade was taken)
  TRADE   — an executed trade (paper or live)
  HALT    — a trading halt event

The file is stored next to the bot as  trades_journal.jsonl
(configurable via JOURNAL_FILE env var or by passing a path).

Usage:
    from core.journal import journal          # module-level singleton
    journal.log_signal(...)
    journal.log_trade(...)
    pnl = journal.today_pnl()
"""
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path(os.getenv("JOURNAL_FILE", "trades_journal.jsonl"))


class TradeJournal:
    """Append-only JSONL journal for signals and executed trades."""

    def __init__(self, path: Path = _DEFAULT_PATH) -> None:
        self._path = path
        self._cache: list[dict] | None = None
        self._cache_date: str = ""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _append(self, entry: dict) -> None:
        try:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
            self._cache = None  # invalidate so next read picks up the new entry
        except Exception as e:
            logger.error(f"Journal write error: {e}")

    def _read_today(self) -> list[dict]:
        today = datetime.now().date().isoformat()
        if self._cache is not None and self._cache_date == today:
            return self._cache
        entries: list[dict] = []
        if not self._path.exists():
            self._cache, self._cache_date = entries, today
            return entries
        try:
            with open(self._path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if entry.get("ts", "").startswith(today):
                            entries.append(entry)
                    except json.JSONDecodeError:
                        pass
        except Exception as e:
            logger.error(f"Journal read error: {e}")
        self._cache, self._cache_date = entries, today
        return entries

    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------

    def log_signal(
        self,
        symbol: str,
        signal: str,
        confluence_score: float,
        vote_breakdown: dict,
        market_bias: str,
        bias_confidence: float,
        snapshot: dict,
        top_strategies: list[str],
        threshold_met: bool,
        action_taken: bool,
    ) -> None:
        """Record a confluence analysis result (whether or not traded)."""
        self._append({
            "type": "SIGNAL",
            "ts": datetime.now().isoformat(),
            "symbol": symbol,
            "signal": signal,
            "confluence_score": round(confluence_score, 4),
            "votes": vote_breakdown,
            "market_bias": market_bias,
            "bias_confidence": round(bias_confidence, 4),
            "price": snapshot.get("price"),
            "rsi": snapshot.get("rsi"),
            "macd_hist": snapshot.get("macd_hist"),
            "rel_volume": snapshot.get("rel_volume"),
            "top_strategies": top_strategies,
            "threshold_met": threshold_met,
            "action_taken": action_taken,
        })

    def log_trade(
        self,
        symbol: str,
        action: str,           # "BUY" or "SELL"
        shares: float,
        price: float,
        strategy: str,
        reason: str,
        pnl: Optional[float] = None,
        mode: str = "paper",   # "paper" or "live"
        order_id: Optional[str] = None,
    ) -> None:
        """Record an executed trade."""
        entry: dict = {
            "type": "TRADE",
            "ts": datetime.now().isoformat(),
            "mode": mode,
            "symbol": symbol,
            "action": action,
            "shares": round(shares, 4),
            "price": round(price, 4),
            "notional": round(shares * price, 2),
            "strategy": strategy,
            "reason": reason[:200],
        }
        if pnl is not None:
            entry["pnl"] = round(pnl, 4)
        if order_id:
            entry["order_id"] = order_id
        self._append(entry)

    def log_halt(self, source: str, reason: str, duration_minutes: int) -> None:
        """Record a trading halt."""
        self._append({
            "type": "HALT",
            "ts": datetime.now().isoformat(),
            "source": source,
            "reason": reason[:200],
            "duration_minutes": duration_minutes,
        })

    # ------------------------------------------------------------------
    # Read helpers (today only)
    # ------------------------------------------------------------------

    def today_trade_count(self) -> int:
        """Number of trades executed today."""
        return sum(1 for e in self._read_today() if e.get("type") == "TRADE")

    def today_pnl(self) -> float:
        """Sum of realized P&L from closed trades today."""
        return sum(
            e.get("pnl", 0.0)
            for e in self._read_today()
            if e.get("type") == "TRADE" and "pnl" in e
        )

    def today_signals(self) -> list[dict]:
        return [e for e in self._read_today() if e.get("type") == "SIGNAL"]

    def today_trades(self) -> list[dict]:
        return [e for e in self._read_today() if e.get("type") == "TRADE"]

    def print_daily_summary(self) -> None:
        trades = self.today_trades()
        signals = self.today_signals()
        pnl = self.today_pnl()
        closed = [t for t in trades if "pnl" in t]
        wins = sum(1 for t in closed if t["pnl"] > 0)
        win_rate = wins / len(closed) if closed else 0.0

        print(f"\n{'='*50}")
        print("JOURNAL SUMMARY — TODAY")
        print(f"{'='*50}")
        print(f"Signals analysed: {len(signals)}")
        print(f"Trades executed:  {len(trades)}")
        print(f"Realized P&L:     ${pnl:+.2f}")
        if closed:
            print(f"Win rate:         {win_rate:.0%} ({wins}/{len(closed)})")
        print(f"Journal file:     {self._path}")
        print(f"{'='*50}\n")


# Module-level singleton
journal = TradeJournal()
