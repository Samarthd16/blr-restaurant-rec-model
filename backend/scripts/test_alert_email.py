"""
One-off diagnostic: sends a real test email via Resend using the exact same
path as alerts.py's _send_email, so it gives a direct yes/no answer on
whether RESEND_API_KEY/ALERT_EMAIL_FROM/ALERT_EMAIL_TO are set up correctly,
with Resend's real error message if not.

Run from backend/: uv run python scripts/test_alert_email.py
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

from alerts import RESEND_API_URL  # noqa: E402

import requests  # noqa: E402

api_key = os.environ.get("RESEND_API_KEY")
from_addr = os.environ.get("ALERT_EMAIL_FROM")
to_addr = os.environ.get("ALERT_EMAIL_TO")

print(f"RESEND_API_KEY: {'set (' + str(len(api_key)) + ' chars)' if api_key else 'MISSING'}")
print(f"ALERT_EMAIL_FROM: {from_addr!r}")
print(f"ALERT_EMAIL_TO: {to_addr!r}")

if not (api_key and from_addr and to_addr):
    print("\nOne or more of RESEND_API_KEY/ALERT_EMAIL_* missing from backend/.env -- fix that first.")
    raise SystemExit(1)

print(f"\nPOSTing to {RESEND_API_URL}...")
try:
    resp = requests.post(
        RESEND_API_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "from": from_addr,
            "to": [to_addr],
            "subject": "Cafe Hopper Guide: test alert email",
            "text": "This is a one-off test from test_alert_email.py -- if you got this, Resend works.",
        },
        timeout=10,
    )
    resp.raise_for_status()
    print(f"\nSUCCESS ({resp.status_code}) -- check the inbox. Response: {resp.json()}")
except Exception as e:
    print(f"\nFAILED: {type(e).__name__}: {e}")
    if hasattr(e, "response") and e.response is not None:
        print(f"Response body: {e.response.text}")
