"""
Shared mutable state for the trading bot.

TradingState is a thread-safe singleton that every component reads/writes.
The EventGuardAgent writes halt decisions; the NewsBiasAgent writes the
daily directional bias. The orchestrator reads both before running any
strategy agents.
"""
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class HaltEvent:
    reason: str
    triggered_at: datetime
    halt_until: datetime
    source: str          # "CPI", "POTUS_TWEET", "FED", "GEOPOLITICAL", etc.
    severity: str        # "HIGH", "EXTREME"


class TradingState:
    """Thread-safe singleton holding halt status and market bias."""

    _instance: Optional["TradingState"] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> "TradingState":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialise()
        return cls._instance

    def _initialise(self) -> None:
        self._rw_lock = threading.RLock()

        # Halt state
        self._is_halted: bool = False
        self._halt_reason: str = ""
        self._halt_until: Optional[datetime] = None
        self._halt_source: str = ""
        self._halt_history: list[HaltEvent] = []

        # Bias state
        self._market_bias: str = "NEUTRAL"    # BULLISH | BEARISH | NEUTRAL
        self._bias_confidence: float = 0.5
        self._bias_reasoning: str = "Not yet assessed."
        self._bias_key_factors: list[str] = []
        self._last_bias_check: Optional[datetime] = None

        # Event guard state
        self._last_guard_check: Optional[datetime] = None
        self._recent_events: list[str] = []    # rolling list of detected events

    # ------------------------------------------------------------------
    # Halt interface
    # ------------------------------------------------------------------

    @property
    def is_halted(self) -> bool:
        with self._rw_lock:
            if self._is_halted and self._halt_until and datetime.now() >= self._halt_until:
                self._auto_resume()
            return self._is_halted

    def halt_trading(
        self,
        reason: str,
        duration_minutes: int,
        source: str = "UNKNOWN",
        severity: str = "HIGH",
    ) -> None:
        from datetime import timedelta
        with self._rw_lock:
            now = datetime.now()
            halt_until = now + timedelta(minutes=duration_minutes)
            self._is_halted = True
            self._halt_reason = reason
            self._halt_until = halt_until
            self._halt_source = source
            event = HaltEvent(
                reason=reason,
                triggered_at=now,
                halt_until=halt_until,
                source=source,
                severity=severity,
            )
            self._halt_history.append(event)
            print(
                f"\n🚨 TRADING HALTED — {source}\n"
                f"   Reason:    {reason}\n"
                f"   Resumes:   {halt_until.strftime('%H:%M:%S')}\n"
                f"   Duration:  {duration_minutes} minutes"
            )
            # Fire email notification (import here to avoid circular import)
            try:
                from core.notifier import send_halt_notification
                send_halt_notification(source, reason, halt_until)
            except Exception:
                pass  # Never let notification failure block halt logic

    def resume_trading(self, reason: str = "Manual resume") -> None:
        with self._rw_lock:
            self._is_halted = False
            self._halt_reason = ""
            self._halt_until = None
            print(f"\n✅ TRADING RESUMED — {reason}")

    def _auto_resume(self) -> None:
        """Called internally when halt_until has passed."""
        self._is_halted = False
        prev_source = self._halt_source
        self._halt_reason = ""
        self._halt_until = None
        self._halt_source = ""
        print(f"\n✅ TRADING RESUMED — halt window expired (was: {prev_source})")

    @property
    def halt_status_line(self) -> str:
        with self._rw_lock:
            if not self._is_halted:
                return "ACTIVE"
            remaining = ""
            if self._halt_until:
                secs = int((self._halt_until - datetime.now()).total_seconds())
                remaining = f" | {max(secs, 0)}s remaining"
            return f"HALTED — {self._halt_source}{remaining}"

    # ------------------------------------------------------------------
    # Bias interface
    # ------------------------------------------------------------------

    def update_bias(
        self,
        bias: str,
        confidence: float,
        reasoning: str,
        key_factors: list[str],
    ) -> None:
        with self._rw_lock:
            self._market_bias = bias.upper()
            self._bias_confidence = confidence
            self._bias_reasoning = reasoning
            self._bias_key_factors = key_factors
            self._last_bias_check = datetime.now()

    @property
    def market_bias(self) -> str:
        with self._rw_lock:
            return self._market_bias

    @property
    def bias_confidence(self) -> float:
        with self._rw_lock:
            return self._bias_confidence

    @property
    def bias_reasoning(self) -> str:
        with self._rw_lock:
            return self._bias_reasoning

    @property
    def bias_key_factors(self) -> list[str]:
        with self._rw_lock:
            return list(self._bias_key_factors)

    @property
    def last_bias_check(self) -> Optional[datetime]:
        with self._rw_lock:
            return self._last_bias_check

    # ------------------------------------------------------------------
    # Event log
    # ------------------------------------------------------------------

    def log_event(self, event: str) -> None:
        with self._rw_lock:
            self._recent_events.append(f"[{datetime.now().strftime('%H:%M')}] {event}")
            if len(self._recent_events) > 50:
                self._recent_events.pop(0)
            self._last_guard_check = datetime.now()

    @property
    def recent_events(self) -> list[str]:
        with self._rw_lock:
            return list(self._recent_events[-10:])

    @property
    def last_guard_check(self) -> Optional[datetime]:
        with self._rw_lock:
            return self._last_guard_check

    def print_status(self) -> None:
        print(
            f"\n📰 NEWS STATE\n"
            f"   Trading:    {self.halt_status_line}\n"
            f"   Bias:       {self._market_bias} ({self._bias_confidence:.0%} confidence)\n"
            f"   Reasoning:  {self._bias_reasoning[:100]}\n"
            f"   Last bias:  {self._last_bias_check.strftime('%H:%M:%S') if self._last_bias_check else 'Never'}\n"
            f"   Last guard: {self._last_guard_check.strftime('%H:%M:%S') if self._last_guard_check else 'Never'}"
        )


# Module-level singleton — import this everywhere
trading_state = TradingState()
