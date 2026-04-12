from agents.base_agent import BaseAgent


class MomentumAgent(BaseAgent):
    """
    Momentum strategy using MACD histogram acceleration and RSI momentum.

    Rules:
    - BUY: MACD histogram accelerating positive, RSI 40-70 (not overbought)
    - SELL: MACD histogram accelerating negative, RSI 30-60 (not oversold)
    - Avoids extremes: RSI > 80 = overbought (avoid buy), RSI < 20 = oversold (avoid sell)
    """

    strategy_name = "Momentum (MACD Histogram + RSI)"

    system_prompt = """You are an expert day trader specialising in MOMENTUM strategies.

Your framework:
- Primary signal: MACD histogram acceleration (is momentum building or fading?)
- Confirmation: RSI trend and level
- Strength: rate of change in both indicators

Key insights:
- MACD histogram growing larger (in either direction) = accelerating momentum
- MACD histogram shrinking = momentum fading (potential reversal)
- RSI 50-70 during upward momentum = healthy bull run
- RSI 30-50 during downward momentum = healthy bear run
- RSI divergence from price = warning signal

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
Focus on MOMENTUM - is the move just starting, in full swing, or exhausted?"""

    def _build_prompt(self, symbol: str, snapshot: dict) -> str:
        hist_change = snapshot['macd_hist'] - snapshot['macd_hist_prev']
        hist_accel = "ACCELERATING" if abs(snapshot['macd_hist']) > abs(snapshot['macd_hist_prev']) else "DECELERATING"
        rsi_trend = "RISING" if snapshot['rsi'] > snapshot['rsi_prev'] else "FALLING"

        return f"""Analyze {symbol} for a momentum trade.

CURRENT PRICE: ${snapshot['price']}

MACD MOMENTUM:
  Current Histogram:  {snapshot['macd_hist']:.6f}
  Previous Histogram: {snapshot['macd_hist_prev']:.6f}
  Histogram Change:   {hist_change:+.6f}
  Momentum Status:    {hist_accel}
  MACD Line:          {snapshot['macd']:.6f}
  Signal Line:        {snapshot['macd_signal']:.6f}
  MACD > Signal:      {snapshot['macd_above_signal']}

RSI MOMENTUM:
  Current RSI:  {snapshot['rsi']:.1f}
  Previous RSI: {snapshot['rsi_prev']:.1f}
  RSI Trend:    {rsi_trend}

EMA CONTEXT:
  EMA9:  ${snapshot['ema9']}
  EMA21: ${snapshot['ema21']}
  Price vs EMA9:  {snapshot['price_vs_ema9']:+.2f}%

VOLUME:
  Relative Volume: {snapshot['rel_volume']:.2f}x average
  (High relative volume = momentum confirmation)

RECENT PRICE ACTION (last 5 bars): {snapshot['recent_closes']}

Is momentum building, peak, or fading? Provide your momentum signal."""
