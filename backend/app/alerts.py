"""
Owner email alerts -- currently just "the Neo4j Aura instance looks paused,
go resume it." Gmail SMTP (needs an App Password, not the regular account
password -- https://myaccount.google.com/apppasswords) since it's free and
needs no new service signup for a project this size.

Cooldown is in-memory (module-level timestamp), not persisted -- resets on
every backend restart/redeploy. Fine for a single-instance deployment; would
need a shared store (Redis, DB row) if this ever ran as multiple replicas,
since each replica would otherwise track its own cooldown independently.
"""

import os
import smtplib
import time
from email.mime.text import MIMEText

ALERT_COOLDOWN_SECONDS = 30 * 60  # don't re-alert more than once per 30 min

_last_alert_sent_at: float = 0.0


def send_neo4j_down_alert() -> None:
    global _last_alert_sent_at

    now = time.time()
    if now - _last_alert_sent_at < ALERT_COOLDOWN_SECONDS:
        return  # already alerted recently, don't spam
    _last_alert_sent_at = now

    smtp_user = os.environ.get("ALERT_EMAIL_FROM")
    smtp_password = os.environ.get("ALERT_EMAIL_APP_PASSWORD")
    to_addr = os.environ.get("ALERT_EMAIL_TO")

    if not (smtp_user and smtp_password and to_addr):
        # Alerting is optional -- don't let a missing config crash the
        # actual chat request that triggered this.
        print("Neo4j appears down, but ALERT_EMAIL_* env vars aren't fully set -- skipping email alert.")
        return

    message = MIMEText(
        "The Neo4j Aura instance for Cafe Hopper Guide is unreachable -- "
        "likely auto-paused from inactivity (free tier). Resume it at "
        "https://console.neo4j.io to restore the chat backend."
    )
    message["Subject"] = "Cafe Hopper Guide: Neo4j instance is down"
    message["From"] = smtp_user
    message["To"] = to_addr

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=10) as smtp:
            smtp.starttls()
            smtp.login(smtp_user, smtp_password)
            smtp.send_message(message)
    except Exception as e:
        # Alerting failing shouldn't break the user-facing error response --
        # log it and move on.
        print(f"Failed to send Neo4j-down alert email: {e}")


def send_keep_alive_notification() -> None:
    """Fired on every successful keep-alive ping (see main.py's background
    task) so these show up in the inbox clearly labeled as autonomous --
    distinguishable at a glance from send_usage_notification, which only
    fires when an actual visitor asks a question."""
    smtp_user = os.environ.get("ALERT_EMAIL_FROM")
    smtp_password = os.environ.get("ALERT_EMAIL_APP_PASSWORD")
    to_addr = os.environ.get("ALERT_EMAIL_TO")

    if not (smtp_user and smtp_password and to_addr):
        return  # optional feature, same as the down-alert

    message = MIMEText(
        "[AUTONOMOUS RUN -- not triggered by a user]\n\n"
        "This is a scheduled keep-alive ping (RETURN 1) sent automatically by "
        "the backend's background task, to stop the Neo4j Aura free-tier "
        "instance from auto-pausing due to inactivity. No one visited the "
        "site to trigger this."
    )
    message["Subject"] = "Cafe Hopper Guide: autonomous keep-alive ping (no user involved)"
    message["From"] = smtp_user
    message["To"] = to_addr

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=10) as smtp:
            smtp.starttls()
            smtp.login(smtp_user, smtp_password)
            smtp.send_message(message)
    except Exception as e:
        print(f"Failed to send keep-alive notification email: {e}")


def send_usage_notification(question: str, answer: str) -> None:
    """Fired on every real chat request (not rate-limited ones) -- lets the
    owner know in real time when someone tries the deployed demo, and what
    they asked. Deliberately no cooldown here (unlike send_neo4j_down_alert):
    the point is per-question visibility, not incident alerting. Called from
    a background thread in main.py so a slow/failed send never adds latency
    to the actual chat response."""
    smtp_user = os.environ.get("ALERT_EMAIL_FROM")
    smtp_password = os.environ.get("ALERT_EMAIL_APP_PASSWORD")
    to_addr = os.environ.get("ALERT_EMAIL_TO")

    if not (smtp_user and smtp_password and to_addr):
        return  # optional feature, same as the down-alert

    message = MIMEText(f"[USER REQUEST]\n\nQuestion: {question}\n\nAnswer:\n{answer}")
    message["Subject"] = "Cafe Hopper Guide: new question asked"
    message["From"] = smtp_user
    message["To"] = to_addr

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=10) as smtp:
            smtp.starttls()
            smtp.login(smtp_user, smtp_password)
            smtp.send_message(message)
    except Exception as e:
        print(f"Failed to send usage notification email: {e}")