from agents.base_agent import BaseAgent


class TrendFollowingAgent(BaseAgent):
    """
    Trend Following strategy using EMA crossovers confirmed by MACD direction.

    Rules:
    - BUY: EMA9 > EMA21 > EMA50, price above all EMAs, MACD histogram rising
    - SELL: EMA9 < EMA21 < EMA50, price below all EMAs, MACD histogram falling
    - Uses EMA200 as the macro trend filter
    """

    strategy_name = "Trend Following (EMA + MACD)"

    system_prompt = """You are an expert day trader specialising in TREND FOLLOWING strategies.

Your framework:
- Primary signal: EMA crossovers (9/21/50)
- Confirmation: MACD direction and histogram momentum
- Filter: EMA200 (only trade in direction of macro trend)
- Entry quality: how aligned are all time-frame EMAs?

Scoring:
- EMA9 > EMA21 > EMA50 with price above all = strong uptrend
- MACD histogram rising AND positive = momentum confirmation
- Price above EMA200 = macro trend bullish
- Volume above average = institutional participation

You MUST respond with a JSON block in this exact format:
```json
{
  "signal": "BUY" | "SELL" | "HOLD",
  "confidence": <float 0.0-1.0>,
  "reasoning": "<1-2 sentences>",
  "key_factors": ["<factor1>", "<factor2>", "<factor3>"],
  "stop_loss": <price or null>,
  "take_profit": <price or null>
}
```
Be decisive. HOLD is valid when conditions are mixed. Never trade against the macro trend."""

    def _build_prompt(self, symbol: str, snapshot: dict) -> str:
        return f"""Analyze {symbol} for a trend-following trade.

CURRENT PRICE: ${snapshot['price']}

EMA ALIGNMENT:
  EMA9:   ${snapshot['ema9']} ({snapshot['price_vs_ema9']:+.2f}% from price)
  EMA21:  ${snapshot['ema21']} ({snapshot['price_vs_ema21']:+.2f}% from price)
  EMA50:  ${snapshot['ema50']} ({snapshot['price_vs_ema50']:+.2f}% from price)
  EMA200: ${snapshot['ema200']}
  EMA9 vs EMA21: {snapshot['ema9_vs_ema21']:+.2f}%
  EMA21 vs EMA50: {snapshot['ema21_vs_ema50']:+.2f}%

MACD (12,26,9):
  MACD Line:      {snapshot['macd']:.6f}
  Signal Line:    {snapshot['macd_signal']:.6f}
  Histogram:      {snapshot['macd_hist']:.6f}
  Prev Histogram: {snapshot['macd_hist_prev']:.6f}
  MACD > Signal:  {snapshot['macd_above_signal']}
  Histogram Rising: {snapshot['macd_hist_rising']}

RSI(14): {snapshot['rsi']:.1f}

VOLUME:
  Current: {snapshot['volume']:,}
  Relative Volume: {snapshot['rel_volume']:.2f}x average

RECENT CLOSES (last 5 bars): {snapshot['recent_closes']}

Based on this data, provide your trend-following signal."""
