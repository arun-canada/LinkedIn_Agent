from __future__ import annotations

import email
import hashlib
import imaplib
import logging
import re
from datetime import datetime, timedelta, timezone
from email.header import decode_header
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .config import NewsletterConfig
from .models import SourceItem
from .utils import JUNK_URL_RE as _JUNK_URL_RE

logger = logging.getLogger(__name__)

# Anchor text that indicates navigation/admin links, not article links
_JUNK_ANCHOR_RE = re.compile(
    r"^(privacy(\s+policy)?|unsubscribe|opt\s*out|terms(\s+of\s+(service|use))?|"
    r"view\s+(in\s+browser|online|email|this\s+email)|email\s+preferences|"
    r"manage\s+preferences|update\s+preferences|forward\s+to\s+a\s+friend|"
    r"contact\s+us|click\s+here\s+to\s+unsubscribe|advertise)$",
    re.IGNORECASE,
)

# Inline URL pattern — used to strip raw URLs from plain-text excerpts
_URL_IN_TEXT_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def _decode_header(value: str) -> str:
    chunks = []
    for part, encoding in decode_header(value):
        if isinstance(part, bytes):
            chunks.append(part.decode(encoding or "utf-8", errors="replace"))
        else:
            chunks.append(part)
    return " ".join(chunks).strip()


def _parse_date(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        return datetime.now(timezone.utc)


def _extract_html_and_text(msg: email.message.Message) -> tuple[str, str]:
    text_body = ""
    html_body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if "attachment" in (part.get("Content-Disposition") or "").lower():
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            charset = part.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace")
            if ctype == "text/plain" and not text_body:
                text_body = decoded
            elif ctype == "text/html" and not html_body:
                html_body = decoded
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                html_body = decoded
            else:
                text_body = decoded
    return text_body, html_body


def _strip_html(html: str) -> str:
    clean = re.sub(r"<script.*?>.*?</script>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    clean = re.sub(r"<style.*?>.*?</style>", " ", clean, flags=re.IGNORECASE | re.DOTALL)
    clean = re.sub(r"<[^>]+>", " ", clean)
    return re.sub(r"\s+", " ", unescape(clean)).strip()


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


def _is_junk_url(url: str) -> bool:
    return bool(_JUNK_URL_RE.search(url))


def _extract_links(html: str) -> list[tuple[str, str]]:
    """Return (url, anchor_text) pairs from newsletter HTML. Junk links excluded."""
    if not html.strip():
        return []
    soup = BeautifulSoup(html, "html.parser")
    links: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        anchor_text = a.get_text(strip=True)
        if _JUNK_ANCHOR_RE.match(anchor_text):
            logger.debug("Skipping junk anchor '%s': %s", anchor_text, href)
            continue
        if href.startswith("http://") or href.startswith("https://"):
            if _is_junk_url(href):
                logger.debug("Skipping junk URL: %s", href)
                continue
            links.append((href, anchor_text))
        elif href.startswith("/"):
            full = urljoin("https://", href)
            if not _is_junk_url(full):
                links.append((full, anchor_text))
    seen: set[str] = set()
    deduped: list[tuple[str, str]] = []
    for url, text in links:
        if url not in seen:
            deduped.append((url, text))
            seen.add(url)
    return deduped


def _clean_excerpt(text: str) -> str:
    """Strip inline URLs and collapse whitespace in a plain-text excerpt."""
    cleaned = _URL_IN_TEXT_RE.sub("", text)
    return re.sub(r"\s+", " ", cleaned).strip()


def fetch_newsletter_links(config: NewsletterConfig, email_addr: str, app_password: str) -> list[SourceItem]:
    items: list[SourceItem] = []
    since = (datetime.now(timezone.utc) - timedelta(days=config.days_back)).strftime("%d-%b-%Y")

    with imaplib.IMAP4_SSL(config.imap_host, config.imap_port) as imap:
        imap.login(email_addr, app_password)
        imap.select(config.folder)
        status, data = imap.search(None, "SINCE", since)
        if status != "OK" or not data or not data[0]:
            return []
        for message_id in reversed(data[0].split()):
            status, msg_data = imap.fetch(message_id, "(RFC822)")
            if status != "OK" or not msg_data or msg_data[0] is None:
                continue
            raw = msg_data[0][1]
            if not isinstance(raw, (bytes, bytearray)):
                continue
            msg = email.message_from_bytes(raw)
            subject = _decode_header(msg.get("Subject", "(no subject)"))
            sender = _decode_header(msg.get("From", "Unknown sender"))
            sender_ok = _sender_allowed(sender, config.from_allowlist)
            subject_ok = _subject_match(subject, config.subject_keywords)
            # Trusted senders (explicitly allowlisted) bypass the subject filter
            # Unknown senders must match subject keywords to be included
            if not sender_ok and not subject_ok:
                continue
            if not sender_ok:
                continue
            published = _parse_date(msg.get("Date"))
            text, html = _extract_html_and_text(msg)
            raw_excerpt = (text or _strip_html(html))[:800]
            excerpt = _clean_excerpt(raw_excerpt)
            links = _extract_links(html)
            for link, anchor_text in links[:10]:
                # Use the anchor text (article headline) when present; fall back to email subject
                title = anchor_text if len(anchor_text) > 10 else subject
                item_id = hashlib.sha256(f"mail:{message_id.decode()}:{link}".encode("utf-8")).hexdigest()
                items.append(
                    SourceItem(
                        id=item_id,
                        title=title,
                        url=link,
                        published_at=published,
                        source_type="newsletter_link",
                        raw_text_excerpt=excerpt,
                        origin=sender,
                    )
                )
    return items


def safe_fetch_newsletter_links(config: NewsletterConfig, email_addr: str | None, app_password: str | None) -> list[SourceItem]:
    if not config.enabled:
        return []
    if not email_addr or not app_password:
        logger.warning("Newsletter enabled but Yahoo credentials are missing; skipping email ingestion.")
        return []
    try:
        return fetch_newsletter_links(config, email_addr, app_password)
    except Exception as exc:
        logger.exception("Yahoo IMAP ingestion failed; continuing with RSS only: %s", exc)
        return []
