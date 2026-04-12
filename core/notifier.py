import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from config import config
from core.confluence import ConfluenceResult
from agents.base_agent import Signal

logger = logging.getLogger(__name__)


def send_halt_notification(source: str, reason: str, halt_until: datetime) -> None:
    """Send an urgent notification when trading is halted by the event guard."""
    msg = (
        f"\n🚨 TRADING HALTED — {source}\n"
        f"   {reason}\n"
        f"   Resumes: {halt_until.strftime('%H:%M:%S')}"
    )
    print(msg)
    if config.NOTIFY_EMAIL and config.SMTP_USER and config.SMTP_PASS:
        try:
            email_msg = MIMEMultipart("alternative")
            email_msg["Subject"] = f"[TradingBot] HALT — {source}"
            email_msg["From"] = config.SMTP_USER
            email_msg["To"] = config.NOTIFY_EMAIL
            email_msg.attach(MIMEText(
                f"Trading Halt Alert\n\n"
                f"Source:  {source}\n"
                f"Reason:  {reason}\n"
                f"Resumes: {halt_until.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                "This is an automated alert from your trading bot.",
                "plain",
            ))
            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
                server.starttls()
                server.login(config.SMTP_USER, config.SMTP_PASS)
                server.sendmail(config.SMTP_USER, config.NOTIFY_EMAIL, email_msg.as_string())
        except Exception as e:
            logger.error(f"Failed to send halt email: {e}")


def send_notification(result: ConfluenceResult) -> None:
    """Route notification to all configured channels."""
    _log_to_console(result)
    if config.NOTIFY_EMAIL and config.SMTP_USER and config.SMTP_PASS:
        _send_email(result)


def _log_to_console(result: ConfluenceResult) -> None:
    """Print formatted trade signal to console."""
    emoji = "🟢" if result.final_signal == Signal.BUY else "🔴" if result.final_signal == Signal.SELL else "⚪"
    print(f"\n{emoji} TRADE SIGNAL — {datetime.now().strftime('%H:%M:%S')}")
    print(result.summary)

    if result.top_signals:
        print("\nTOP AGENT DETAILS:")
        for s in result.top_signals[:3]:
            print(f"  Strategy: {s.strategy_name}")
            print(f"  Signal:   {s.signal.value} | Confidence: {s.confidence:.0%}")
            print(f"  Reason:   {s.reasoning}")
            if s.key_factors:
                print(f"  Factors:  {', '.join(s.key_factors[:3])}")
            if s.stop_loss:
                print(f"  Stop:     ${s.stop_loss:.2f}")
            if s.take_profit:
                print(f"  Target:   ${s.take_profit:.2f}")
            print()


def _send_email(result: ConfluenceResult) -> None:
    """Send email notification for trade signal."""
    try:
        subject = (
            f"[TradingBot] {result.final_signal.value} Signal — {result.symbol} "
            f"({result.confluence_score:.0%} confluence)"
        )

        body_lines = [
            f"Trading Bot Signal Alert",
            f"{'='*50}",
            f"Time:        {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Symbol:      {result.symbol}",
            f"Signal:      {result.final_signal.value}",
            f"Confluence:  {result.confluence_score:.0%}",
            f"Votes:       BUY={result.vote_breakdown['BUY']} | SELL={result.vote_breakdown['SELL']} | HOLD={result.vote_breakdown['HOLD']}",
            f"{'='*50}",
            "",
            "STRATEGY SIGNALS:",
        ]

        for s in result.all_signals:
            body_lines.append(f"  {s.strategy_name}: {s.signal.value} ({s.confidence:.0%})")
            body_lines.append(f"    {s.reasoning}")

        if result.top_signals:
            best = result.top_signals[0]
            body_lines.extend([
                "",
                f"BEST SETUP ({best.strategy_name}):",
                f"  Stop Loss:   {f'${best.stop_loss:.2f}' if best.stop_loss else 'N/A'}",
                f"  Take Profit: {f'${best.take_profit:.2f}' if best.take_profit else 'N/A'}",
            ])

        body_lines.extend([
            "",
            "This is an automated alert. Always apply your own risk management.",
        ])

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = config.SMTP_USER
        msg["To"] = config.NOTIFY_EMAIL
        msg.attach(MIMEText("\n".join(body_lines), "plain"))

        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
            server.starttls()
            server.login(config.SMTP_USER, config.SMTP_PASS)
            server.sendmail(config.SMTP_USER, config.NOTIFY_EMAIL, msg.as_string())

        logger.info(f"Email notification sent for {result.symbol} {result.final_signal.value}")

    except Exception as e:
        logger.error(f"Failed to send email notification: {e}")
