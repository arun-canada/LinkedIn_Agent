from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from ..config import AppConfig
from ..dedupe import CacheDB
from ..models import PostRecommendation, SourceItem


@dataclass
class AgentContext:
    """Shared envelope passed through the pipeline. Each agent reads from it and writes results back."""

    # ---- Run configuration ----
    config: AppConfig
    cache: CacheDB
    output_dir: str = "output"
    yahoo_email: str | None = None
    yahoo_password: str | None = None

    # ---- Written by IngestionAgent ----
    raw_items: list[SourceItem] = field(default_factory=list)

    # ---- Written by FilterAgent ----
    validated_items: list[SourceItem] = field(default_factory=list)
    url_to_hash: dict[str, str] = field(default_factory=dict)  # canonical_url → content_hash

    # ---- Written by ScoringAgent ----
    ranked_items: list[SourceItem] = field(default_factory=list)

    # ---- Written by ContentAgent ----
    summarized_items: list[SourceItem] = field(default_factory=list)
    posts_markdown: str = ""
    used_fallback: bool = False

    # ---- Written by ReviewAgent ----
    recommendations: list[PostRecommendation] = field(default_factory=list)

    # ---- Pipeline control ----
    should_continue: bool = True   # set to False by any agent to stop the pipeline early
    debug_mode: bool = False       # when True, agents emit per-item detail at DEBUG level
    errors: list[str] = field(default_factory=list)

    # ---- Diagnostics ----
    run_started_at: datetime = field(default_factory=datetime.now)
    logger: logging.Logger = field(
        default_factory=lambda: logging.getLogger("robotics_daily"),
        repr=False,
        compare=False,
    )


class BaseAgent(ABC):
    """Abstract base for all pipeline agents.

    Contract:
    - Receive `ctx`, mutate it in place, return it.
    - Do NOT raise on recoverable errors — append to `ctx.errors` instead.
    - Set `ctx.should_continue = False` to signal early pipeline stop.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable agent name shown in logs."""
        ...

    @abstractmethod
    def run(self, ctx: AgentContext) -> AgentContext:
        """Execute this agent's step."""
        ...

    def _log(self, ctx: AgentContext, level: str, msg: str, *args: object) -> None:
        """Log with agent-name prefix."""
        getattr(ctx.logger, level)(f"[{self.name}] {msg}", *args)
