from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from config import config
from agents.base_agent import Signal


@dataclass
class Position:
    symbol: str
    entry_price: float
    shares: float
    entry_time: datetime
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    strategy: str = ""

    @property
    def cost_basis(self) -> float:
        return self.entry_price * self.shares

    def pnl(self, current_price: float) -> float:
        return (current_price - self.entry_price) * self.shares

    def pnl_pct(self, current_price: float) -> float:
        return (current_price - self.entry_price) / self.entry_price

    def should_stop_out(self, current_price: float) -> bool:
        return self.stop_loss is not None and current_price <= self.stop_loss

    def should_take_profit(self, current_price: float) -> bool:
        return self.take_profit is not None and current_price >= self.take_profit


@dataclass
class Trade:
    symbol: str
    action: str             # BUY or SELL
    shares: float
    price: float
    timestamp: datetime
    pnl: Optional[float] = None
    strategy: str = ""
    reason: str = ""


class PaperPortfolio:
    """Paper trading portfolio tracker."""

    def __init__(self) -> None:
        self.cash: float = config.PAPER_STARTING_CAPITAL
        self.positions: dict[str, Position] = {}
        self.trade_history: list[Trade] = []
        self.starting_capital: float = config.PAPER_STARTING_CAPITAL

    @property
    def portfolio_value(self) -> float:
        """Cash + market value of all positions (uses last known entry prices as proxy)."""
        position_value = sum(p.cost_basis for p in self.positions.values())
        return self.cash + position_value

    @property
    def total_return(self) -> float:
        return (self.portfolio_value - self.starting_capital) / self.starting_capital

    def _position_size(self, price: float) -> float:
        """Calculate number of shares to buy based on position size config."""
        allocated = self.portfolio_value * config.PAPER_POSITION_SIZE
        return allocated / price

    def execute_signal(
        self,
        symbol: str,
        signal: Signal,
        price: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        strategy: str = "",
        reason: str = "",
    ) -> Optional[Trade]:
        """Execute a trade signal on the paper portfolio."""
        if signal == Signal.BUY and symbol not in self.positions:
            return self._open_long(symbol, price, stop_loss, take_profit, strategy, reason)
        elif signal == Signal.SELL and symbol in self.positions:
            return self._close_long(symbol, price, reason)
        return None

    def _open_long(
        self,
        symbol: str,
        price: float,
        stop_loss: Optional[float],
        take_profit: Optional[float],
        strategy: str,
        reason: str,
    ) -> Trade:
        shares = self._position_size(price)
        cost = shares * price

        if cost > self.cash:
            shares = self.cash / price
            cost = self.cash

        self.cash -= cost
        self.positions[symbol] = Position(
            symbol=symbol,
            entry_price=price,
            shares=shares,
            entry_time=datetime.now(),
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy=strategy,
        )

        trade = Trade(
            symbol=symbol, action="BUY", shares=shares,
            price=price, timestamp=datetime.now(),
            strategy=strategy, reason=reason,
        )
        self.trade_history.append(trade)
        print(f"  📈 PAPER BUY  {symbol}: {shares:.2f} shares @ ${price:.2f} | Cost: ${cost:.2f}")
        return trade

    def _close_long(self, symbol: str, price: float, reason: str = "") -> Trade:
        position = self.positions.pop(symbol)
        proceeds = position.shares * price
        self.cash += proceeds
        pnl = position.pnl(price)

        trade = Trade(
            symbol=symbol, action="SELL", shares=position.shares,
            price=price, timestamp=datetime.now(),
            pnl=pnl, strategy=position.strategy, reason=reason,
        )
        self.trade_history.append(trade)
        pnl_emoji = "✅" if pnl >= 0 else "❌"
        print(f"  📉 PAPER SELL {symbol}: {position.shares:.2f} shares @ ${price:.2f} | P&L: ${pnl:+.2f} {pnl_emoji}")
        return trade

    def check_exits(self, symbol: str, current_price: float) -> Optional[Trade]:
        """Check if any stop-loss or take-profit levels are hit."""
        if symbol not in self.positions:
            return None
        position = self.positions[symbol]
        if position.should_stop_out(current_price):
            print(f"  🛑 STOP LOSS triggered for {symbol} @ ${current_price:.2f}")
            return self._close_long(symbol, current_price, reason="Stop loss hit")
        if position.should_take_profit(current_price):
            print(f"  🎯 TAKE PROFIT triggered for {symbol} @ ${current_price:.2f}")
            return self._close_long(symbol, current_price, reason="Take profit hit")
        return None

    def print_summary(self) -> None:
        print(f"\n{'='*50}")
        print("PAPER PORTFOLIO SUMMARY")
        print(f"{'='*50}")
        print(f"Starting Capital: ${self.starting_capital:,.2f}")
        print(f"Current Value:    ${self.portfolio_value:,.2f}")
        print(f"Cash:             ${self.cash:,.2f}")
        print(f"Total Return:     {self.total_return:+.2%}")
        print(f"Open Positions:   {len(self.positions)}")
        print(f"Total Trades:     {len(self.trade_history)}")

        if self.positions:
            print("\nOPEN POSITIONS:")
            for sym, pos in self.positions.items():
                print(f"  {sym}: {pos.shares:.2f} shares @ ${pos.entry_price:.2f} | Entry: {pos.entry_time.strftime('%H:%M')}")

        closed_trades = [t for t in self.trade_history if t.pnl is not None]
        if closed_trades:
            total_pnl = sum(t.pnl for t in closed_trades)
            wins = sum(1 for t in closed_trades if t.pnl and t.pnl > 0)
            win_rate = wins / len(closed_trades) if closed_trades else 0
            print(f"\nCLOSED TRADES P&L: ${total_pnl:+.2f} | Win Rate: {win_rate:.0%} ({wins}/{len(closed_trades)})")
        print(f"{'='*50}\n")
