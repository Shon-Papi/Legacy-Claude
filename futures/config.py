"""
Configuration for the futures trading bot.

All values can be overridden via environment variables (or a .env file).
The defaults are deliberately conservative — loosen them only after you
have backtested AND paper traded with the new values.
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _env_f(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _env_i(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _env_b(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes")


class FuturesConfig:
    # ------------------------------------------------------------------
    # Market
    # ------------------------------------------------------------------
    # Binance USDT-M perpetual futures symbols (ccxt unified format)
    SYMBOLS: list[str] = [
        s.strip()
        for s in os.getenv(
            "FUTURES_SYMBOLS", "BTC/USDT:USDT,ETH/USDT:USDT,SOL/USDT:USDT"
        ).split(",")
        if s.strip()
    ]
    TIMEFRAME: str = os.getenv("FUTURES_TIMEFRAME", "15m")

    # ------------------------------------------------------------------
    # Strategy — trend-filtered Donchian breakout
    # ------------------------------------------------------------------
    EMA_FAST: int = _env_i("FUTURES_EMA_FAST", 50)
    EMA_SLOW: int = _env_i("FUTURES_EMA_SLOW", 200)
    DONCHIAN_PERIOD: int = _env_i("FUTURES_DONCHIAN_PERIOD", 20)
    RSI_PERIOD: int = _env_i("FUTURES_RSI_PERIOD", 14)
    RSI_LONG_MAX: float = _env_f("FUTURES_RSI_LONG_MAX", 75.0)   # don't chase blow-offs
    RSI_SHORT_MIN: float = _env_f("FUTURES_RSI_SHORT_MIN", 25.0)
    ATR_PERIOD: int = _env_i("FUTURES_ATR_PERIOD", 14)

    # Exits
    STOP_ATR_MULT: float = _env_f("FUTURES_STOP_ATR_MULT", 2.0)    # initial stop
    TRAIL_ATR_MULT: float = _env_f("FUTURES_TRAIL_ATR_MULT", 2.5)  # chandelier trail
    BREAKEVEN_R: float = _env_f("FUTURES_BREAKEVEN_R", 1.0)        # move stop to entry at +1R
    MAX_HOLD_BARS: int = _env_i("FUTURES_MAX_HOLD_BARS", 96)       # time stop (96 x 15m = 1 day)

    # ------------------------------------------------------------------
    # Risk management
    # ------------------------------------------------------------------
    STARTING_EQUITY: float = _env_f("FUTURES_STARTING_EQUITY", 10_000.0)
    RISK_PER_TRADE: float = _env_f("FUTURES_RISK_PER_TRADE", 0.0075)      # 0.75% of equity
    MAX_POSITION_LEVERAGE: float = _env_f("FUTURES_MAX_POSITION_LEVERAGE", 2.0)
    MAX_TOTAL_LEVERAGE: float = _env_f("FUTURES_MAX_TOTAL_LEVERAGE", 3.0)
    MAX_POSITIONS: int = _env_i("FUTURES_MAX_POSITIONS", 3)
    DAILY_LOSS_LIMIT_PCT: float = _env_f("FUTURES_DAILY_LOSS_LIMIT_PCT", 0.03)  # halt day at -3%
    HALT_DRAWDOWN_PCT: float = _env_f("FUTURES_HALT_DRAWDOWN_PCT", 0.15)        # halt bot at -15% from peak

    # ------------------------------------------------------------------
    # Execution costs (used by backtester AND paper engine)
    # ------------------------------------------------------------------
    TAKER_FEE: float = _env_f("FUTURES_TAKER_FEE", 0.0005)   # 0.05% per side
    SLIPPAGE: float = _env_f("FUTURES_SLIPPAGE", 0.0002)     # 0.02% per fill

    # ------------------------------------------------------------------
    # Exchange / live trading
    # ------------------------------------------------------------------
    EXCHANGE_ID: str = os.getenv("FUTURES_EXCHANGE", "binanceusdm")
    API_KEY: str = os.getenv("FUTURES_API_KEY", "")
    API_SECRET: str = os.getenv("FUTURES_API_SECRET", "")
    TESTNET: bool = _env_b("FUTURES_TESTNET", True)
    # Hard safety latch: real-money trading refuses to start unless this is
    # literally "YES" in the environment.
    LIVE_CONFIRM: str = os.getenv("FUTURES_LIVE_CONFIRM", "")

    POLL_SECONDS: int = _env_i("FUTURES_POLL_SECONDS", 20)

    # ------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------
    DATA_CACHE_DIR: str = os.getenv("FUTURES_DATA_CACHE_DIR", "data_cache")
    PAPER_STATE_FILE: str = os.getenv("FUTURES_PAPER_STATE_FILE", "futures_paper_state.json")
    JOURNAL_FILE: str = os.getenv("FUTURES_JOURNAL_FILE", "futures_trades.csv")


fconfig = FuturesConfig()
