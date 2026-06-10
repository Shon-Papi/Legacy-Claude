"""
Event-driven portfolio backtester for the futures strategy.

Honesty rules baked in (the easiest way to fake a "profitable" backtest is
to break any one of these):

  - Signals are computed on the CLOSE of bar t and filled at the OPEN of
    bar t+1 — no lookahead.
  - Every fill pays taker fees and slippage on both sides.
  - Stops are evaluated against intrabar highs/lows; gaps through the stop
    fill at the open, not at the stop price.
  - Position sizing, leverage caps, daily-loss and drawdown halts are the
    exact same code the live engine uses (futures.risk).
"""
import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from futures.config import fconfig
from futures.indicators import add_indicators
from futures.risk import RiskState, position_qty
from futures.strategy import LONG, Signal, initial_stop, signal_at, update_stop

logger = logging.getLogger(__name__)


@dataclass
class Position:
    symbol: str
    side: int
    qty: float
    entry_price: float
    entry_time: pd.Timestamp
    stop: float
    init_risk: float           # per-unit distance entry -> initial stop
    extreme: float             # best price since entry (high for long, low for short)
    entry_fee: float
    bars_held: int = 0


@dataclass
class ClosedTrade:
    symbol: str
    side: str
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    qty: float
    pnl: float                 # net of all fees
    fees: float
    r_multiple: float
    bars_held: int
    reason: str


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    trades: list[ClosedTrade]
    cfg: object = fconfig

    def trades_df(self) -> pd.DataFrame:
        return pd.DataFrame([t.__dict__ for t in self.trades])

    def metrics(self) -> dict:
        curve = self.equity_curve
        start, end = float(curve.iloc[0]), float(curve.iloc[-1])
        n_days = max((curve.index[-1] - curve.index[0]).total_seconds() / 86_400, 1e-9)

        peak = curve.cummax()
        max_dd = float(((peak - curve) / peak).max())

        daily = curve.resample("1D").last().dropna().pct_change().dropna()
        sharpe = (
            float(daily.mean() / daily.std() * np.sqrt(365))
            if len(daily) > 2 and daily.std() > 0
            else float("nan")
        )

        pnls = np.array([t.pnl for t in self.trades])
        wins, losses = pnls[pnls > 0], pnls[pnls <= 0]
        gross_win, gross_loss = wins.sum(), -losses.sum()

        return {
            "start_equity": start,
            "end_equity": end,
            "total_return_pct": 100 * (end / start - 1),
            "max_drawdown_pct": 100 * max_dd,
            "sharpe_daily_ann": sharpe,
            "n_trades": len(self.trades),
            "trades_per_day": len(self.trades) / n_days,
            "win_rate_pct": 100 * len(wins) / len(pnls) if len(pnls) else float("nan"),
            "profit_factor": gross_win / gross_loss if gross_loss > 0 else float("inf"),
            "avg_trade_pnl": float(pnls.mean()) if len(pnls) else float("nan"),
            "avg_r": float(np.mean([t.r_multiple for t in self.trades])) if self.trades else float("nan"),
            "total_fees": float(sum(t.fees for t in self.trades)),
            "days": n_days,
        }

    def summary(self) -> str:
        m = self.metrics()
        return (
            f"\n{'=' * 58}\n"
            f"  BACKTEST RESULT  ({m['days']:.0f} days)\n"
            f"{'=' * 58}\n"
            f"  Equity:        ${m['start_equity']:,.0f} -> ${m['end_equity']:,.2f}"
            f"  ({m['total_return_pct']:+.2f}%)\n"
            f"  Max drawdown:  {m['max_drawdown_pct']:.2f}%\n"
            f"  Sharpe (ann.): {m['sharpe_daily_ann']:.2f}\n"
            f"  Trades:        {m['n_trades']}  ({m['trades_per_day']:.2f}/day)\n"
            f"  Win rate:      {m['win_rate_pct']:.1f}%\n"
            f"  Profit factor: {m['profit_factor']:.2f}\n"
            f"  Avg trade:     ${m['avg_trade_pnl']:+.2f}  (avg {m['avg_r']:+.2f}R)\n"
            f"  Fees paid:     ${m['total_fees']:,.2f}\n"
            f"{'=' * 58}\n"
        )


class Backtester:
    def __init__(self, data: dict[str, pd.DataFrame], cfg=fconfig):
        """`data` maps symbol -> raw OHLCV DataFrame (UTC datetime index)."""
        self.cfg = cfg
        self.data = {sym: add_indicators(df, cfg) for sym, df in data.items()}

        self.cash = cfg.STARTING_EQUITY
        self.risk = RiskState(starting_equity=cfg.STARTING_EQUITY)
        self.positions: dict[str, Position] = {}
        self.pending: dict[str, Signal] = {}
        self.trades: list[ClosedTrade] = []
        self.last_close: dict[str, float] = {}
        self.curve_times: list[pd.Timestamp] = []
        self.curve_values: list[float] = []

    # ------------------------------------------------------------------
    # Accounting helpers
    # ------------------------------------------------------------------

    def _mtm_equity(self) -> float:
        unrealized = sum(
            p.side * (self.last_close.get(s, p.entry_price) - p.entry_price) * p.qty
            for s, p in self.positions.items()
        )
        return self.cash + unrealized

    def _open_notional(self) -> float:
        return sum(
            self.last_close.get(s, p.entry_price) * p.qty
            for s, p in self.positions.items()
        )

    def _close_position(
        self, pos: Position, raw_price: float, time: pd.Timestamp, reason: str
    ) -> None:
        # Exiting a long sells (price slips down); exiting a short buys (slips up)
        exit_price = raw_price * (1 - pos.side * self.cfg.SLIPPAGE)
        exit_fee = exit_price * pos.qty * self.cfg.TAKER_FEE
        gross = pos.side * (exit_price - pos.entry_price) * pos.qty
        net = gross - pos.entry_fee - exit_fee
        self.cash += gross - exit_fee  # entry fee was deducted at entry

        risk_dollars = pos.init_risk * pos.qty
        self.trades.append(
            ClosedTrade(
                symbol=pos.symbol,
                side="LONG" if pos.side == LONG else "SHORT",
                entry_time=pos.entry_time,
                exit_time=time,
                entry_price=pos.entry_price,
                exit_price=exit_price,
                qty=pos.qty,
                pnl=net,
                fees=pos.entry_fee + exit_fee,
                r_multiple=net / risk_dollars if risk_dollars > 0 else 0.0,
                bars_held=pos.bars_held,
                reason=reason,
            )
        )
        del self.positions[pos.symbol]
        self.risk.record_realized(net)

    def _open_position(self, sig: Signal, raw_price: float, time: pd.Timestamp) -> None:
        entry_price = raw_price * (1 + sig.side * self.cfg.SLIPPAGE)
        qty = position_qty(
            self.cash, entry_price, sig.atr, self._open_notional(), self.cfg
        )
        if qty <= 0:
            return
        entry_fee = entry_price * qty * self.cfg.TAKER_FEE
        self.cash -= entry_fee
        stop = initial_stop(sig.side, entry_price, sig.atr, self.cfg)
        self.positions[sig.symbol] = Position(
            symbol=sig.symbol,
            side=sig.side,
            qty=qty,
            entry_price=entry_price,
            entry_time=time,
            stop=stop,
            init_risk=abs(entry_price - stop),
            extreme=entry_price,
            entry_fee=entry_fee,
        )

    # ------------------------------------------------------------------
    # Bar processing
    # ------------------------------------------------------------------

    def _fill_pending(self, symbol: str, bar: pd.Series, time: pd.Timestamp) -> None:
        sig = self.pending.pop(symbol, None)
        if sig is None:
            return
        open_price = float(bar["open"])

        pos = self.positions.get(symbol)
        if pos is not None:
            if pos.side == sig.side:
                return  # already positioned this way
            self._close_position(pos, open_price, time, "signal_flip")

        if self.risk.entries_allowed(len(self.positions), self.cfg):
            self._open_position(sig, open_price, time)

    def _manage_position(self, symbol: str, bar: pd.Series, time: pd.Timestamp) -> None:
        pos = self.positions.get(symbol)
        if pos is None:
            return
        o, h, l, c = (float(bar[k]) for k in ("open", "high", "low", "close"))

        # Stop hit? Gaps through the stop fill at the open.
        if pos.side == LONG and (o <= pos.stop or l <= pos.stop):
            self._close_position(pos, min(o, pos.stop), time, "stop")
            return
        if pos.side != LONG and (o >= pos.stop or h >= pos.stop):
            self._close_position(pos, max(o, pos.stop), time, "stop")
            return

        pos.bars_held += 1
        pos.extreme = max(pos.extreme, h) if pos.side == LONG else min(pos.extreme, l)
        cur_atr = float(bar["atr"])
        if np.isfinite(cur_atr) and cur_atr > 0:
            pos.stop = update_stop(
                pos.side, pos.stop, pos.entry_price, pos.init_risk,
                pos.extreme, cur_atr, c, self.cfg,
            )

        if pos.bars_held >= self.cfg.MAX_HOLD_BARS:
            self._close_position(pos, c, time, "time_stop")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> BacktestResult:
        merged = sorted(set().union(*(df.index for df in self.data.values())))
        pointers = {sym: 0 for sym in self.data}

        for t in merged:
            self.risk.roll_day(t.date(), self._mtm_equity())

            for sym, df in self.data.items():
                i = pointers[sym]
                if i >= len(df) or df.index[i] != t:
                    continue
                pointers[sym] = i + 1
                bar = df.iloc[i]

                self._fill_pending(sym, bar, t)
                self._manage_position(sym, bar, t)
                self.last_close[sym] = float(bar["close"])

                sig = signal_at(df, i, sym, self.cfg)
                if sig is not None:
                    pos = self.positions.get(sym)
                    if pos is None or pos.side != sig.side:
                        self.pending[sym] = sig

            equity = self._mtm_equity()
            self.risk.update_equity(equity, self.cfg)
            self.curve_times.append(t)
            self.curve_values.append(equity)

        # Close anything still open at the final price
        for sym in list(self.positions):
            pos = self.positions[sym]
            self._close_position(pos, self.last_close[sym], merged[-1], "end_of_data")
        if self.curve_values:
            self.curve_values[-1] = self._mtm_equity()

        curve = pd.Series(self.curve_values, index=pd.DatetimeIndex(self.curve_times))
        return BacktestResult(equity_curve=curve, trades=self.trades, cfg=self.cfg)
