"""
Owner email alerts -- Neo4j-down alerts, keep-alive pings, and per-question
usage notifications. Sent via Resend's HTTP API (https://resend.com), not
raw SMTP: Railway's network silently drops outbound connections on both the
IPv6 and IPv4 paths to smtp.gmail.com:587 (confirmed via "[Errno 101]
Network is unreachable" then a hard timeout once IPv4 was forced), which is
a known limitation on their shared/hobby network tier. HTTPS egress isn't
blocked, so an HTTP-based email API sidesteps the problem entirely.

RESEND_API_KEY and ALERT_EMAIL_TO are required. ALERT_EMAIL_FROM should be
Resend's sandbox sender ("onboarding@resend.dev") unless a custom domain has
been verified in the Resend dashboard -- the sandbox sender can only deliver
to the email address the Resend account was created with, which is fine
here since ALERT_EMAIL_TO is the owner's own inbox.

Cooldown is in-memory (module-level timestamp), not persisted -- resets on
every backend restart/redeploy. Fine for a single-instance deployment; would
need a shared store (Redis, DB row) if this ever ran as multiple replicas,
since each replica would otherwise track its own cooldown independently.
"""

import os
import time

import requests

RESEND_API_URL = "https://api.resend.com/emails"
ALERT_COOLDOWN_SECONDS = 30 * 60  # don't re-alert more than once per 30 min

_last_alert_sent_at: float = 0.0


def _send_email(subject: str, body: str) -> None:
    api_key = os.environ.get("RESEND_API_KEY")
    from_addr = os.environ.get("ALERT_EMAIL_FROM")
    to_addr = os.environ.get("ALERT_EMAIL_TO")

    if not (api_key and from_addr and to_addr):
        # Alerting is optional -- don't let missing config crash the actual
        # chat request that triggered this.
        print(f"Email alert skipped ('{subject}'): RESEND_API_KEY/ALERT_EMAIL_* not fully set.")
        return

    try:
        resp = requests.post(
            RESEND_API_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"from": from_addr, "to": [to_addr], "subject": subject, "text": body},
            timeout=10,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"Failed to send email '{subject}': {e}")


def send_neo4j_down_alert() -> None:
    global _last_alert_sent_at

    now = time.time()
    if now - _last_alert_sent_at < ALERT_COOLDOWN_SECONDS:
        return  # already alerted recently, don't spam
    _last_alert_sent_at = now

    _send_email(
        "Cafe Hopper Guide: Neo4j instance is down",
        "The Neo4j Aura instance for Cafe Hopper Guide is unreachable -- "
        "likely auto-paused from inactivity (free tier). Resume it at "
        "https://console.neo4j.io to restore the chat backend.",
    )


def send_keep_alive_notification() -> None:
    """Fired on every successful keep-alive ping (see main.py's background
    task) so these show up in the inbox clearly labeled as autonomous --
    distinguishable at a glance from send_usage_notification, which only
    fires when an actual visitor asks a question."""
    _send_email(
        "Cafe Hopper Guide: autonomous keep-alive ping (no user involved)",
        "[AUTONOMOUS RUN -- not triggered by a user]\n\n"
        "This is a scheduled keep-alive ping (RETURN 1) sent automatically by "
        "the backend's background task, to stop the Neo4j Aura free-tier "
        "instance from auto-pausing due to inactivity. No one visited the "
        "site to trigger this.",
    )


def send_usage_notification(question: str, answer: str) -> None:
    """Fired on every real chat request (not rate-limited ones) -- lets the
    owner know in real time when someone tries the deployed demo, and what
    they asked. Deliberately no cooldown here (unlike send_neo4j_down_alert):
    the point is per-question visibility, not incident alerting. Called from
    a background thread in main.py so a slow/failed send never adds latency
    to the actual chat response."""
    _send_email(
        "Cafe Hopper Guide: new question asked",
        f"[USER REQUEST]\n\nQuestion: {question}\n\nAnswer:\n{answer}",
    )
