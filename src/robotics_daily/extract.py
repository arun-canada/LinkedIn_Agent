from __future__ import annotations

import logging
import time

import requests
import trafilatura
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


USER_AGENT = "robotics-daily/1.0 (+local-cli)"


def fetch_with_backoff(url: str, timeout_s: int = 12, max_retries: int = 3) -> str:
    delay = 1.0
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(url, timeout=timeout_s, headers={"User-Agent": USER_AGENT})
            if response.status_code == 200:
                return response.text
            if response.status_code in {429, 500, 502, 503, 504} and attempt < max_retries:
                time.sleep(delay)
                delay *= 2
                continue
            return ""
        except requests.RequestException:
            if attempt < max_retries:
                time.sleep(delay)
                delay *= 2
                continue
            return ""
    return ""


def extract_article_text(html: str) -> str:
    if not html.strip():
        return ""
    extracted = trafilatura.extract(html, include_links=False, include_images=False)
    if extracted:
        return extracted.strip()
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    return text.strip()


def enrich_source_excerpt(url: str, fallback_excerpt: str, max_chars: int = 2000) -> str:
    html = fetch_with_backoff(url)
    if not html:
        return fallback_excerpt[:max_chars]
    text = extract_article_text(html)
    if not text:
        return fallback_excerpt[:max_chars]
    return text[:max_chars]
