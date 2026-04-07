from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class RSSFeed(BaseModel):
    name: str
    url: str


class NewsletterConfig(BaseModel):
    enabled: bool = True
    imap_host: str = "imap.mail.yahoo.com"
    imap_port: int = 993
    folder: str = "INBOX"
    days_back: int = 2
    from_allowlist: list[str] = Field(default_factory=list)
    subject_keywords: list[str] = Field(default_factory=list)


class RSSConfig(BaseModel):
    days_back: int = 7


class SelectionConfig(BaseModel):
    max_items: int = 8
    max_posts: int = 3


class OutputConfig(BaseModel):
    dir: str = "output"


class AppConfig(BaseModel):
    rss_feeds: list[RSSFeed] = Field(default_factory=list)
    rss: RSSConfig = Field(default_factory=RSSConfig)
    newsletter: NewsletterConfig = Field(default_factory=NewsletterConfig)
    selection: SelectionConfig = Field(default_factory=SelectionConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)


def load_config(path: str | Path = "config/feeds.yaml") -> AppConfig:
    config_path = Path(path)
    data: dict[str, Any] = {}
    if config_path.exists():
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return AppConfig(**data)
