from __future__ import annotations

import re

# Canonical junk URL regex — shared between yahoo_imap.py and agents/filter.py.
# Matches URL path/query patterns for non-article pages (privacy, unsubscribe, etc.)
JUNK_URL_RE = re.compile(
    r"/privacy|/unsubscribe|/optout|/opt-out|/terms\b|/tos\b|/gdpr"
    r"|/manage[-_]preferences|/email[-_]preferences|/mailing[-_]list"
    r"|[?&]sid=|[?&]m=email"
    r"|list-manage\.com"
    r"|mailchimp\.com/signup",
    re.IGNORECASE,
)
