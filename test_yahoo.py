#!/usr/bin/env python
"""Quick test script to verify Yahoo IMAP credentials."""

import imaplib
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

email = os.environ.get("YAHOO_EMAIL")
password = os.environ.get("YAHOO_APP_PASSWORD")

print(f"Testing Yahoo IMAP connection...")
print(f"Email: {email}")
print(f"Password: {'*' * len(password) if password else 'NOT SET'}")
print()

try:
    # Connect to Yahoo IMAP
    print("Connecting to imap.mail.yahoo.com:993...")
    imap = imaplib.IMAP4_SSL("imap.mail.yahoo.com", 993)

    print("Logging in...")
    imap.login(email, password)

    print("✓ Login successful!")

    # List folders
    print("\nAvailable folders:")
    status, folders = imap.list()
    for folder in folders[:10]:  # Show first 10 folders
        print(f"  {folder.decode()}")

    # Check INBOX
    print("\nChecking INBOX...")
    imap.select("INBOX")
    status, messages = imap.search(None, "ALL")
    num_messages = len(messages[0].split())
    print(f"✓ Total messages in INBOX: {num_messages}")

    # Check recent messages (last 2 days)
    import datetime
    date = (datetime.datetime.now() - datetime.timedelta(days=2)).strftime("%d-%b-%Y")
    status, messages = imap.search(None, f'(SINCE "{date}")')
    num_recent = len(messages[0].split()) if messages[0] else 0
    print(f"✓ Messages in last 2 days: {num_recent}")

    imap.logout()
    print("\n✓ Test completed successfully!")

except imaplib.IMAP4.error as e:
    print(f"✗ IMAP Error: {e}")
    print("\nPossible issues:")
    print("1. Wrong email address")
    print("2. Wrong app password (must be Yahoo App Password, not account password)")
    print("3. 2-step verification not enabled on Yahoo account")
    print("4. App password not generated for 'Mail' access")

except Exception as e:
    print(f"✗ Error: {e}")
