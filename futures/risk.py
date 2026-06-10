"""
Risk management for the futures bot — shared by the backtester and the
live/paper engine so the rules you test are the rules you trade.

Sizing: fixed-fractional. Each trade risks RISK_PER_TRADE of equity to its
initial stop, with hard caps on per-position and total notional leverage.
"""
import logging
from dataclasses import dataclass, field
from datetime import date

from futures.config import fconfig

logger = logging.getLogger(__name__)


def position_qty(
    equity: float,
    price: float,
    sig_atr: float,
    open_notional: float,
    cfg=fconfig,
) -> float:
    """
    Quantity (contracts in base units) so the initial ATR stop loses
    RISK_PER_TRADE of equity, capped by leverage limits.
    Returns 0.0 when no acceptable size exists.
    """
    if equity <= 0 or price <= 0 or sig_atr <= 0:
        return 0.0

    stop_dist = cfg.STOP_ATR_MULT * sig_atr
    qty = (equity * cfg.RISK_PER_TRADE) / stop_dist

    max_pos_notional = equity * cfg.MAX_POSITION_LEVERAGE
    max_total_headroom = equity * cfg.MAX_TOTAL_LEVERAGE - open_notional
    notional = min(qty * price, max_pos_notional, max_total_headroom)
    if notional <= 0:
        return 0.0
    return notional / price


@dataclass
class RiskState:
    """
    Account-level circuit breakers.

      - Daily loss limit: realized losses beyond DAILY_LOSS_LIMIT_PCT of the
        equity at the start of the (UTC) day halt new entries until tomorrow.
      - Drawdown halt: equity falling HALT_DRAWDOWN_PCT below its all-time
        peak halts new entries permanently (manual reset required).

    Open positions are always still managed to their exits.
    """
    starting_equity: float
    peak_equity: float = 0.0
    day: date | None = None
    day_start_equity: float = 0.0
    day_realized: float = 0.0
    halted_for_day: bool = False
    drawdown_halted: bool = False

    def __post_init__(self):
        if self.peak_equity <= 0:
            self.peak_equity = self.starting_equity

    def roll_day(self, today: date, equity: float) -> None:
        if self.day != today:
            self.day = today
            self.day_start_equity = equity
            self.day_realized = 0.0
            self.halted_for_day = False

    def record_realized(self, pnl: float, cfg=fconfig) -> None:
        self.day_realized += pnl
        if (
            not self.halted_for_day
            and self.day_start_equity > 0
            and self.day_realized <= -cfg.DAILY_LOSS_LIMIT_PCT * self.day_start_equity
        ):
            self.halted_for_day = True
            logger.warning(
                "RISK: daily loss limit hit (%.2f) — no new entries until tomorrow",
                self.day_realized,
            )

    def update_equity(self, equity: float, cfg=fconfig) -> None:
        self.peak_equity = max(self.peak_equity, equity)
        if (
            not self.drawdown_halted
            and self.peak_equity > 0
            and (self.peak_equity - equity) / self.peak_equity >= cfg.HALT_DRAWDOWN_PCT
        ):
            self.drawdown_halted = True
            logger.warning(
                "RISK: max drawdown halt — equity %.2f is %.1f%% below peak %.2f",
                equity,
                100 * (self.peak_equity - equity) / self.peak_equity,
                self.peak_equity,
            )

    def entries_allowed(self, n_open_positions: int, cfg=fconfig) -> bool:
        if self.drawdown_halted or self.halted_for_day:
            return False
        return n_open_positions < cfg.MAX_POSITIONS
