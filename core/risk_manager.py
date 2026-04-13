"""
RiskManager — pre-trade guardrails for the trading bot.

Checks three independent limits before allowing any trade:

  1. Daily loss limit  — stop trading if today's realized P&L falls below
                         MAX_DAILY_LOSS_PCT × starting capital.

  2. Max drawdown      — stop trading if the portfolio has dropped
                         MAX_DRAWDOWN_PCT from its all-time peak.

  3. Daily trade cap   — stop trading once DAILY_TRADE_LIMIT trades have
                         been executed today (prevents overtrading on a
                         hyperactive signal day).

Usage:
    from core.risk_manager import risk_manager

    if risk_manager.is_trade_allowed(portfolio_value, peak_value):
        execute_trade(...)
"""
import logging
from config import config
from core.journal import journal

logger = logging.getLogger(__name__)


class RiskManager:
    """Pre-trade risk checks. All methods return True if trading is allowed."""

    # ------------------------------------------------------------------
    # Individual limit checks
    # ------------------------------------------------------------------

    def check_daily_loss(self, portfolio_value: float) -> bool:
        """
        Reject trades if today's realized P&L has fallen below the daily
        loss threshold.  Returns True when trading is still allowed.
        """
        today_pnl = journal.today_pnl()
        limit = -abs(config.MAX_DAILY_LOSS_PCT * config.PAPER_STARTING_CAPITAL)

        if today_pnl <= limit:
            logger.warning(
                f"RISK: Daily loss limit hit — today P&L ${today_pnl:+.2f} "
                f"vs limit ${limit:.2f}"
            )
            print(
                f"  🚫 RISK BLOCK — Daily loss limit reached. "
                f"Today P&L: ${today_pnl:+.2f} | Limit: ${limit:.2f}"
            )
            return False
        return True

    def check_drawdown(self, portfolio_value: float, peak_value: float) -> bool:
        """
        Reject trades if the portfolio has drawn down more than
        MAX_DRAWDOWN_PCT from its historical peak.
        """
        if peak_value <= 0:
            return True

        drawdown = (peak_value - portfolio_value) / peak_value

        if drawdown >= config.MAX_DRAWDOWN_PCT:
            logger.warning(
                f"RISK: Max drawdown hit — current drawdown {drawdown:.1%} "
                f"vs limit {config.MAX_DRAWDOWN_PCT:.1%}"
            )
            print(
                f"  🚫 RISK BLOCK — Max drawdown reached. "
                f"Drawdown: {drawdown:.1%} | Limit: {config.MAX_DRAWDOWN_PCT:.1%}"
            )
            return False
        return True

    def check_trade_count(self) -> bool:
        """Reject trades once the daily trade cap is reached."""
        count = journal.today_trade_count()
        if count >= config.DAILY_TRADE_LIMIT:
            print(
                f"  🚫 RISK BLOCK — Daily trade limit reached "
                f"({count}/{config.DAILY_TRADE_LIMIT})"
            )
            return False
        return True

    # ------------------------------------------------------------------
    # Master check
    # ------------------------------------------------------------------

    def is_trade_allowed(
        self,
        portfolio_value: float,
        peak_value: float,
    ) -> bool:
        """
        Returns True only when ALL risk limits pass.
        Short-circuits on the first failure so each block message is
        printed exactly once.
        """
        if not self.check_daily_loss(portfolio_value):
            return False
        if not self.check_drawdown(portfolio_value, peak_value):
            return False
        if not self.check_trade_count():
            return False
        return True

    # ------------------------------------------------------------------
    # Informational
    # ------------------------------------------------------------------

    def status_line(self, portfolio_value: float, peak_value: float) -> str:
        """One-line summary of current risk state for display in headers."""
        today_pnl = journal.today_pnl()
        trades_today = journal.today_trade_count()
        drawdown = (
            (peak_value - portfolio_value) / peak_value
            if peak_value > 0 else 0.0
        )
        return (
            f"P&L today: ${today_pnl:+.2f} | "
            f"Drawdown: {drawdown:.1%} | "
            f"Trades today: {trades_today}/{config.DAILY_TRADE_LIMIT}"
        )


# Module-level singleton
risk_manager = RiskManager()
