"""
Indicator calculations for the futures bot.

Pure pandas — no external TA library — so results are deterministic and
identical between the backtester and the live engine.
"""
import numpy as np
import pandas as pd

from futures.config import fconfig


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def rsi(close: pd.Series, period: int) -> pd.Series:
    """Wilder's RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - 100.0 / (1.0 + rs)
    # When avg_loss is 0 (straight-up move) RSI is 100 by definition
    return out.fillna(100.0).where(avg_gain.notna() & avg_loss.notna())


def atr(df: pd.DataFrame, period: int) -> pd.Series:
    """Wilder's ATR from open/high/low/close columns."""
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def add_indicators(df: pd.DataFrame, cfg=fconfig) -> pd.DataFrame:
    """
    Return a copy of `df` (columns: open/high/low/close/volume, datetime index)
    with all strategy indicator columns added.

    Donchian channels exclude the current bar (shift(1)) so "close above
    don_high" means a genuine breakout of the *prior* N-bar range.
    """
    out = df.copy()
    out["ema_fast"] = ema(out["close"], cfg.EMA_FAST)
    out["ema_slow"] = ema(out["close"], cfg.EMA_SLOW)
    out["rsi"] = rsi(out["close"], cfg.RSI_PERIOD)
    out["atr"] = atr(out, cfg.ATR_PERIOD)
    out["don_high"] = out["high"].rolling(cfg.DONCHIAN_PERIOD).max().shift(1)
    out["don_low"] = out["low"].rolling(cfg.DONCHIAN_PERIOD).min().shift(1)
    return out
