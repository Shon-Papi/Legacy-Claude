"""
Trend-filtered Donchian breakout strategy.

Why this strategy class:
  - Breakout/trend-following is one of the few approaches with decades of
    documented out-of-sample persistence across futures markets.
  - It is deterministic and cheap to compute, so the backtest and the live
    engine run *exactly* the same rules.
  - Crypto perpetuals trend hard intraday, and the 24/7 market across
    several symbols yields multiple signals per day.

Rules (long; short is the mirror image):
  ENTRY  - EMA(fast) > EMA(slow) and close > EMA(slow)   [trend filter]
         - close breaks above the prior N-bar Donchian high [breakout]
         - RSI < RSI_LONG_MAX                             [don't chase blow-offs]
  EXIT   - initial stop:  entry - STOP_ATR_MULT * ATR
         - breakeven:     stop moves to entry after +BREAKEVEN_R * risk
         - trailing:      chandelier stop, highest-high - TRAIL_ATR_MULT * ATR
         - time stop:     close after MAX_HOLD_BARS bars
         - flip:          opposite signal closes the position
"""
import math
from dataclasses import dataclass

import pandas as pd

from futures.config import fconfig

LONG = 1
SHORT = -1

# Indicator columns the strategy needs to see non-NaN before it will act
_REQUIRED = ("ema_fast", "ema_slow", "rsi", "atr", "don_high", "don_low")


@dataclass
class Signal:
    symbol: str
    side: int            # LONG (+1) or SHORT (-1)
    price: float         # close of the signal bar
    atr: float           # ATR at the signal bar (sizing + stop distance)
    time: pd.Timestamp
    reason: str

    @property
    def direction(self) -> str:
        return "LONG" if self.side == LONG else "SHORT"


def signal_at(df: pd.DataFrame, i: int, symbol: str, cfg=fconfig) -> Signal | None:
    """
    Evaluate the strategy on bar `i` of an indicator-enriched DataFrame
    (see indicators.add_indicators). Returns a Signal or None.

    Only ever reads bar `i` and earlier — no lookahead.
    """
    row = df.iloc[i]
    if any(not math.isfinite(float(row[c])) for c in _REQUIRED):
        return None
    if row["atr"] <= 0:
        return None

    close = float(row["close"])

    uptrend = row["ema_fast"] > row["ema_slow"] and close > row["ema_slow"]
    downtrend = row["ema_fast"] < row["ema_slow"] and close < row["ema_slow"]

    if uptrend and close > row["don_high"] and row["rsi"] < cfg.RSI_LONG_MAX:
        return Signal(
            symbol=symbol,
            side=LONG,
            price=close,
            atr=float(row["atr"]),
            time=df.index[i],
            reason=f"breakout > {cfg.DONCHIAN_PERIOD}-bar high in uptrend",
        )

    if downtrend and close < row["don_low"] and row["rsi"] > cfg.RSI_SHORT_MIN:
        return Signal(
            symbol=symbol,
            side=SHORT,
            price=close,
            atr=float(row["atr"]),
            time=df.index[i],
            reason=f"breakdown < {cfg.DONCHIAN_PERIOD}-bar low in downtrend",
        )

    return None


def initial_stop(side: int, entry_price: float, sig_atr: float, cfg=fconfig) -> float:
    return entry_price - side * cfg.STOP_ATR_MULT * sig_atr


def update_stop(
    side: int,
    stop: float,
    entry_price: float,
    init_risk: float,
    extreme_since_entry: float,
    current_atr: float,
    close: float,
    cfg=fconfig,
) -> float:
    """
    Ratchet the stop for an open position. Stops only ever tighten.

      side                 +1 long / -1 short
      init_risk            initial per-unit risk (entry -> initial stop distance)
      extreme_since_entry  highest high since entry (long) / lowest low (short)
    """
    new_stop = stop

    # Chandelier trail off the favourable extreme
    trail = extreme_since_entry - side * cfg.TRAIL_ATR_MULT * current_atr
    if side == LONG:
        new_stop = max(new_stop, trail)
    else:
        new_stop = min(new_stop, trail)

    # Breakeven once the trade is BREAKEVEN_R in profit (marked at close)
    if init_risk > 0:
        profit_r = side * (close - entry_price) / init_risk
        if profit_r >= cfg.BREAKEVEN_R:
            new_stop = max(new_stop, entry_price) if side == LONG else min(new_stop, entry_price)

    return new_stop
