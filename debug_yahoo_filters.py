#!/usr/bin/env python
"""Debug script to show Yahoo emails and why they're filtered."""

import email
import imaplib
import os
from datetime import datetime, timedelta
from email.header import decode_header
from dotenv import load_dotenv

load_dotenv(override=True)

def _decode_header(value: str) -> str:
    chunks = []
    for part, encoding in decode_header(value):
        if isinstance(part, bytes):
            chunks.append(part.decode(encoding or "utf-8", errors="replace"))
        else:
            chunks.append(part)
    return " ".join(chunks).strip()

def _sender_allowed(sender: str, allowlist: list[str]) -> bool:
    if not allowlist:
        return True
    s = sender.lower()
    return any(a.lower() in s for a in allowlist)

def _subject_match(subject: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    sub = subject.lower()
    return any(k.lower() in sub for k in keywords)

# Config from feeds.yaml
from_allowlist = [
    "therobotreport.com", "wtwhmedia.com", "spectrum.ieee.org", "ieee.org",
    "robohub.org", "list-manage.com", "ros.org", "openrobotics.org",
    "discourse.openrobotics.org", "nvidia.com", "blogs.nvidia.com",
    "developer.nvidia.com", "aws.amazon.com", "research.google",
    "microsoft.com", "waymo.com", "weeklyrobotics.com",
    "robotnewsletter.curatedmail.co", "therundown.ai", "Robotics 247"
]
subject_keywords = [
    "autonomous", "autonomy", "autoware", "digital twin", "edge ai",
    "gazebo", "isaac", "jetson", "lidar", "open-scenario", "openscenario",
    "perception", "robotics", "ros 2", "ros2", "safety", "sensor fusion",
    "simulation", "sotif", "testing", "validation", "verification", "iso 26262"
]
days_back = 2

email_addr = os.environ.get("YAHOO_EMAIL")
password = os.environ.get("YAHOO_APP_PASSWORD")

print(f"Checking emails from last {days_back} days...\n")
print(f"Sender filter: {from_allowlist}")
print(f"Subject filter: {subject_keywords}")
print("=" * 80)

since = (datetime.utcnow() - timedelta(days=days_back)).strftime("%d-%b-%Y")

with imaplib.IMAP4_SSL("imap.mail.yahoo.com", 993) as imap:
    imap.login(email_addr, password)
    imap.select("INBOX")
    status, data = imap.search(None, "SINCE", since)

    if status != "OK" or not data or not data[0]:
        print(f"\nNo emails found since {since}")
        exit(0)

    message_ids = data[0].split()
    print(f"\nFound {len(message_ids)} emails since {since}\n")

    passed = 0
    failed_sender = 0
    failed_subject = 0

    for i, message_id in enumerate(reversed(message_ids[:20]), 1):  # Check last 20
        status, msg_data = imap.fetch(message_id, "(RFC822)")
        if status != "OK" or not msg_data or msg_data[0] is None:
            continue

        raw = msg_data[0][1]
        if not isinstance(raw, (bytes, bytearray)):
            continue

        msg = email.message_from_bytes(raw)
        subject = _decode_header(msg.get("Subject", "(no subject)"))
        sender = _decode_header(msg.get("From", "Unknown sender"))
        date = msg.get("Date", "Unknown date")

        sender_ok = _sender_allowed(sender, from_allowlist)
        subject_ok = _subject_match(subject, subject_keywords)

        print(f"\n[{i}] {'✓ PASS' if (sender_ok and subject_ok) else '✗ FILTERED'}")
        print(f"Date: {date}")
        print(f"From: {sender}")
        print(f"  Sender filter: {'✓ PASS' if sender_ok else '✗ FAIL'}")
        print(f"Subject: {subject}")
        print(f"  Subject filter: {'✓ PASS' if subject_ok else '✗ FAIL'}")

        if sender_ok and subject_ok:
            passed += 1
        elif not sender_ok:
            failed_sender += 1
        elif not subject_ok:
            failed_subject += 1

    print("\n" + "=" * 80)
    print(f"\nSummary:")
    print(f"  ✓ Passed both filters: {passed}")
    print(f"  ✗ Failed sender filter: {failed_sender}")
    print(f"  ✗ Failed subject filter: {failed_subject}")

    if passed == 0:
        print(f"\nℹ️  No emails matched the filters!")
        print(f"\nTo get newsletter items, you need emails where:")
        print(f"  - Sender contains one of: {', '.join(from_allowlist)}")
        print(f"  - Subject contains one of: {', '.join(subject_keywords)}")
