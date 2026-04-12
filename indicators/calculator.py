import pandas as pd
import numpy as np
from config import config


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def compute_macd(df: pd.DataFrame) -> pd.DataFrame:
    """Compute MACD line, signal line, and histogram."""
    close = df["close"]
    macd_line = ema(close, config.MACD_FAST) - ema(close, config.MACD_SLOW)
    signal_line = ema(macd_line, config.MACD_SIGNAL)
    histogram = macd_line - signal_line

    df = df.copy()
    df["macd"] = macd_line
    df["macd_signal"] = signal_line
    df["macd_hist"] = histogram
    return df


def compute_ema(df: pd.DataFrame) -> pd.DataFrame:
    """Compute EMA at multiple timeframes."""
    df = df.copy()
    df["ema9"] = ema(df["close"], config.EMA_FAST)
    df["ema21"] = ema(df["close"], config.EMA_SLOW)
    df["ema50"] = ema(df["close"], config.EMA_MID)
    df["ema200"] = ema(df["close"], config.EMA_LONG)
    return df


def compute_rsi(df: pd.DataFrame) -> pd.DataFrame:
    """Compute RSI."""
    close = df["close"]
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=config.RSI_PERIOD - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=config.RSI_PERIOD - 1, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df = df.copy()
    df["rsi"] = 100 - (100 / (1 + rs))
    return df


def compute_bollinger_bands(df: pd.DataFrame) -> pd.DataFrame:
    """Compute Bollinger Bands."""
    df = df.copy()
    rolling_mean = df["close"].rolling(window=config.BB_PERIOD).mean()
    rolling_std = df["close"].rolling(window=config.BB_PERIOD).std()
    df["bb_mid"] = rolling_mean
    df["bb_upper"] = rolling_mean + config.BB_STD * rolling_std
    df["bb_lower"] = rolling_mean - config.BB_STD * rolling_std
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"]
    df["bb_pct"] = (df["close"] - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"])
    return df


def compute_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """Compute intraday VWAP."""
    df = df.copy()
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    cumulative_tp_vol = (typical_price * df["volume"]).cumsum()
    cumulative_vol = df["volume"].cumsum()
    df["vwap"] = cumulative_tp_vol / cumulative_vol.replace(0, np.nan)
    return df


def compute_volume_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Compute volume metrics: relative volume and OBV."""
    df = df.copy()
    avg_vol = df["volume"].rolling(window=20).mean()
    df["rel_volume"] = df["volume"] / avg_vol.replace(0, np.nan)

    # On-Balance Volume
    obv = [0]
    for i in range(1, len(df)):
        if df["close"].iloc[i] > df["close"].iloc[i - 1]:
            obv.append(obv[-1] + df["volume"].iloc[i])
        elif df["close"].iloc[i] < df["close"].iloc[i - 1]:
            obv.append(obv[-1] - df["volume"].iloc[i])
        else:
            obv.append(obv[-1])
    df["obv"] = obv
    return df


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all indicators and return enriched dataframe."""
    df = compute_macd(df)
    df = compute_ema(df)
    df = compute_rsi(df)
    df = compute_bollinger_bands(df)
    df = compute_vwap(df)
    df = compute_volume_metrics(df)
    return df.dropna(subset=["macd", "rsi", "ema9", "bb_mid", "vwap"])


def get_snapshot(df: pd.DataFrame) -> dict:
    """Return a dict of the latest indicator values for agent consumption."""
    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else last
    return {
        "price": round(float(last["close"]), 4),
        "open": round(float(last["open"]), 4),
        "high": round(float(last["high"]), 4),
        "low": round(float(last["low"]), 4),
        "volume": int(last["volume"]),
        "rel_volume": round(float(last["rel_volume"]), 2),
        # EMA
        "ema9": round(float(last["ema9"]), 4),
        "ema21": round(float(last["ema21"]), 4),
        "ema50": round(float(last["ema50"]), 4),
        "ema200": round(float(last["ema200"]), 4),
        "price_vs_ema9": round((last["close"] - last["ema9"]) / last["ema9"] * 100, 3),
        "price_vs_ema21": round((last["close"] - last["ema21"]) / last["ema21"] * 100, 3),
        "price_vs_ema50": round((last["close"] - last["ema50"]) / last["ema50"] * 100, 3),
        "ema9_vs_ema21": round((last["ema9"] - last["ema21"]) / last["ema21"] * 100, 3),
        "ema21_vs_ema50": round((last["ema21"] - last["ema50"]) / last["ema50"] * 100, 3),
        # MACD
        "macd": round(float(last["macd"]), 6),
        "macd_signal": round(float(last["macd_signal"]), 6),
        "macd_hist": round(float(last["macd_hist"]), 6),
        "macd_hist_prev": round(float(prev["macd_hist"]), 6),
        "macd_above_signal": bool(last["macd"] > last["macd_signal"]),
        "macd_hist_rising": bool(last["macd_hist"] > prev["macd_hist"]),
        # RSI
        "rsi": round(float(last["rsi"]), 2),
        "rsi_prev": round(float(prev["rsi"]), 2),
        # Bollinger Bands
        "bb_upper": round(float(last["bb_upper"]), 4),
        "bb_mid": round(float(last["bb_mid"]), 4),
        "bb_lower": round(float(last["bb_lower"]), 4),
        "bb_pct": round(float(last["bb_pct"]), 4),
        "bb_width": round(float(last["bb_width"]), 4),
        # VWAP
        "vwap": round(float(last["vwap"]), 4),
        "price_vs_vwap": round((last["close"] - last["vwap"]) / last["vwap"] * 100, 3),
        # Recent candles (last 5) for pattern recognition
        "recent_closes": [round(float(x), 4) for x in df["close"].tail(5).tolist()],
        "recent_highs": [round(float(x), 4) for x in df["high"].tail(5).tolist()],
        "recent_lows": [round(float(x), 4) for x in df["low"].tail(5).tolist()],
        "recent_volumes": [int(x) for x in df["volume"].tail(5).tolist()],
    }
