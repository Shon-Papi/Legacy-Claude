import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Anthropic
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

    # Symbols
    WATCH_SYMBOLS: list[str] = [
        s.strip() for s in os.getenv("WATCH_SYMBOLS", "AAPL,TSLA,NVDA,SPY,QQQ").split(",")
    ]

    # Trading
    TRADING_MODE: str = os.getenv("TRADING_MODE", "paper")
    CONFLUENCE_THRESHOLD: int = int(os.getenv("CONFLUENCE_THRESHOLD", "3"))
    SCAN_INTERVAL: int = int(os.getenv("SCAN_INTERVAL", "300"))

    # Indicator settings
    EMA_FAST: int = 9
    EMA_SLOW: int = 21
    EMA_MID: int = 50
    EMA_LONG: int = 200
    MACD_FAST: int = 12
    MACD_SLOW: int = 26
    MACD_SIGNAL: int = 9
    RSI_PERIOD: int = 14
    BB_PERIOD: int = 20
    BB_STD: float = 2.0
    VWAP_PERIOD: str = "1d"

    # Data
    DATA_PERIOD: str = "5d"
    DATA_INTERVAL: str = "5m"

    # Notifications
    NOTIFY_EMAIL: str = os.getenv("NOTIFY_EMAIL", "")
    SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASS: str = os.getenv("SMTP_PASS", "")

    # Alpaca
    ALPACA_API_KEY: str = os.getenv("ALPACA_API_KEY", "")
    ALPACA_SECRET_KEY: str = os.getenv("ALPACA_SECRET_KEY", "")
    ALPACA_BASE_URL: str = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    # Paper trading defaults
    PAPER_STARTING_CAPITAL: float = 100_000.0
    PAPER_POSITION_SIZE: float = 0.05  # 5% of portfolio per trade


config = Config()
