"""
One-off diagnostic: attempts the exact same Gmail SMTP login + send that
alerts.py does, but standalone (no cooldown, no ServiceUnavailable needed)
so it gives a direct yes/no answer on whether ALERT_EMAIL_APP_PASSWORD is
actually valid, with Gmail's real error message if not.

Run from backend/: uv run python scripts/test_alert_email.py
"""

import os
import smtplib
from email.mime.text import MIMEText

from dotenv import load_dotenv

load_dotenv()

smtp_user = os.environ.get("ALERT_EMAIL_FROM")
smtp_password = os.environ.get("ALERT_EMAIL_APP_PASSWORD")
to_addr = os.environ.get("ALERT_EMAIL_TO")

print(f"ALERT_EMAIL_FROM: {smtp_user!r}")
print(f"ALERT_EMAIL_APP_PASSWORD: {'set (' + str(len(smtp_password)) + ' chars)' if smtp_password else 'MISSING'}")
print(f"ALERT_EMAIL_TO: {to_addr!r}")

if not (smtp_user and smtp_password and to_addr):
    print("\nOne or more ALERT_EMAIL_* vars missing from backend/.env -- fix that first.")
    raise SystemExit(1)

message = MIMEText("This is a one-off test from test_alert_email.py -- if you got this, SMTP works.")
message["Subject"] = "Cafe Hopper Guide: test alert email"
message["From"] = smtp_user
message["To"] = to_addr

print("\nConnecting to smtp.gmail.com:587...")
try:
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=10) as smtp:
        smtp.starttls()
        print("Logging in...")
        smtp.login(smtp_user, smtp_password)
        print("Login OK. Sending...")
        smtp.send_message(message)
    print("\nSUCCESS -- check the inbox.")
except Exception as e:
    print(f"\nFAILED: {type(e).__name__}: {e}")