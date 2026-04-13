"""
EventGuardAgent — real-time monitor for high-impact events that should
pause trading.

Runs every EVENT_GUARD_INTERVAL seconds (default: 60s) between the main
scan cycles. Uses Claude's server-side web_search tool to check:

  HIGH-IMPACT ECONOMIC EVENTS
  - CPI / Core CPI print
  - PPI / Core PPI print
  - FOMC rate decisions and minutes
  - NFP (Non-Farm Payrolls)
  - GDP advance/revised print
  - ISM Manufacturing / Services PMI
  - Retail Sales
  - Jobless Claims

  POLITICAL / SOCIAL MEDIA
  - POTUS tweets / Truth Social posts about tariffs, trade, economy, Fed
  - Treasury Secretary statements
  - Fed Chair / FOMC member speeches (especially if off-schedule)
  - Regulatory announcements (SEC, CFTC) affecting markets

  SYSTEMIC / GEOPOLITICAL
  - Flash crashes or circuit breakers
  - Major bank/broker outages
  - Geopolitical escalation (military action, sanctions)
  - Black-swan macro events

When a halt-worthy event is detected, it calls trading_state.halt_trading()
with an appropriate duration so the bot avoids trading into the volatility spike.

HALT DURATIONS (configurable via EVENT_HALT_DURATIONS in config):
  CPI / PPI / NFP    → 15 minutes (data released, markets absorbing)
  FOMC decision      → 30 minutes (high uncertainty, large moves)
  POTUS tweet/post   → 10 minutes (sharp knee-jerk then partial reversal)
  Fed speech         → 10 minutes
  Geopolitical       → 20 minutes
"""
import logging
from datetime import datetime

from agents._websearch import call_with_websearch
from agents.base_agent import extract_json_block
from core.trading_state import trading_state

logger = logging.getLogger(__name__)

_SYSTEM = """You are a real-time market risk monitor for a day-trading system.

Your ONLY job is to detect whether any event has occurred in the LAST 30 MINUTES
that would make it dangerous to actively day-trade right now.

TRIGGER CONDITIONS (halt trading if ANY of these are true):

CATEGORY A — SCHEDULED DATA JUST RELEASED (halt 15 min):
- CPI or Core CPI print released within the last 30 minutes
- PPI or Core PPI print released within the last 30 minutes
- Non-Farm Payrolls (NFP) released within the last 30 minutes
- GDP advance or revised estimate released within the last 30 minutes
- ISM PMI (Manufacturing or Services) released within the last 30 minutes
- Retail Sales print released within the last 30 minutes
- Initial or Continuing Jobless Claims released in the last 30 minutes

CATEGORY B — FOMC / FED (halt 30 min):
- FOMC rate decision just announced
- Fed Chair Powell (or acting chair) making unscheduled remarks about rates
- FOMC minutes just released
- Emergency Fed meeting announced

CATEGORY C — POLITICAL / SOCIAL MEDIA (halt 10 min):
- POTUS (President of the United States) posted on Truth Social or X/Twitter
  in the last 30 minutes about: tariffs, trade war, China, Fed, interest rates,
  the economy, stock market, specific companies
- Treasury Secretary making major announcement
- New tariff announcement or executive order with market impact

CATEGORY D — SYSTEMIC RISK (halt 20 min):
- Flash crash: major index down >2% in the last 15 minutes
- Market circuit breaker triggered
- Major geopolitical escalation (military action, new sanctions)
- Large bank or broker system outage

NON-TRIGGER (do NOT halt for these):
- Normal intraday price movements
- Analyst upgrades/downgrades
- Routine company earnings (unless mega-cap >10% move)
- Old news from more than 1 hour ago

You MUST use web_search to check RIGHT NOW. Search for the most recent news.

After checking, respond ONLY with this JSON block:
```json
{
  "should_halt": true | false,
  "events_detected": ["<event description>"],
  "halt_reason": "<concise reason or empty string>",
  "halt_source": "CPI" | "PPI" | "NFP" | "FOMC" | "FED_SPEECH" | "POTUS_TWEET" | "GEOPOLITICAL" | "FLASH_CRASH" | "OTHER" | "",
  "halt_duration_minutes": <integer or 0>,
  "severity": "HIGH" | "EXTREME" | "",
  "market_summary": "<1 sentence on current conditions>"
}
```
If nothing halt-worthy has happened in the last 30 minutes, set should_halt=false."""



def _parse_guard_response(text: str) -> dict:
    data = extract_json_block(text, fallback_key="should_halt")
    if data:
        return data
    logger.warning("Could not parse guard JSON; assuming safe to trade")
    return {
        "should_halt": False,
        "events_detected": [],
        "halt_reason": "",
        "halt_source": "",
        "halt_duration_minutes": 0,
        "severity": "",
        "market_summary": "Guard check parse failed — proceeding with caution.",
    }


def run_event_guard_check() -> bool:
    """
    Scan for high-impact events. Updates TradingState if a halt is warranted.

    Returns True if trading should continue, False if halted.
    """
    # Skip the API call if already halted — no need to re-check
    if trading_state.is_halted:
        return False

    now = datetime.now()
    print(f"\n🛡️  [EventGuardAgent] Checking for high-impact events at {now.strftime('%H:%M:%S')}...")

    user_message = (
        f"Current date and time: {now.strftime('%A, %B %d, %Y %H:%M')} ET.\n\n"
        "Search for ANY of the following that may have happened in the LAST 30 MINUTES:\n"
        "1. Search: 'CPI PPI GDP NFP economic data released today'\n"
        "2. Search: 'FOMC Fed rate decision today'\n"
        "3. Search: 'Trump tariff tweet Truth Social today' OR "
        "'Trump stock market tweet today'\n"
        "4. Search: 'stock market crash circuit breaker today'\n"
        "5. Search: 'geopolitical crisis markets today'\n\n"
        "Has any halt-worthy event occurred in the last 30 minutes? Be specific."
    )

    try:
        raw = call_with_websearch(user_message, _SYSTEM)
        data = _parse_guard_response(raw)

        # Log any events found, regardless of halt decision
        for event in data.get("events_detected", []):
            trading_state.log_event(event)

        summary = data.get("market_summary", "")
        if summary:
            print(f"   Market:  {summary}")

        if data.get("should_halt", False):
            halt_reason = data.get("halt_reason", "High-impact event detected")
            halt_source = data.get("halt_source", "UNKNOWN")
            halt_minutes = int(data.get("halt_duration_minutes", 15))
            severity = data.get("severity", "HIGH")

            # Enforce minimum and maximum halt durations
            halt_minutes = max(5, min(halt_minutes, 60))

            trading_state.halt_trading(
                reason=halt_reason,
                duration_minutes=halt_minutes,
                source=halt_source,
                severity=severity,
            )

            for event in data.get("events_detected", []):
                print(f"   Event:   {event}")

            return False

        print(f"   Status:  No halt-worthy events detected — trading active")
        return True

    except Exception as e:
        logger.error(f"EventGuardAgent error: {e}", exc_info=True)
        # On error, be conservative: don't halt, but log it
        trading_state.log_event(f"Guard check ERROR: {e}")
        return True
