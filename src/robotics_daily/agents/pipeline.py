from __future__ import annotations

import time
from dataclasses import dataclass, field

from .base import AgentContext, BaseAgent


@dataclass
class StepConfig:
    """Wraps an agent with pipeline-level options."""
    agent: BaseAgent
    critical: bool = False  # if True and the agent raises, the pipeline aborts immediately


class Pipeline:
    """Runs a list of agents in sequence, logging timing and handling per-step failures.

    Extensibility: adding a new agent is a single-line change in the caller:
        pipeline = Pipeline([..., NewAgent(), ...])
    No existing agent or pipeline code changes.
    """

    def __init__(self, steps: list[StepConfig | BaseAgent]) -> None:
        self.steps: list[StepConfig] = [
            s if isinstance(s, StepConfig) else StepConfig(agent=s)
            for s in steps
        ]

    def run(self, ctx: AgentContext) -> AgentContext:
        for step in self.steps:
            agent = step.agent
            ctx.logger.info("=== %s: starting ===", agent.name)
            start = time.monotonic()
            try:
                ctx = agent.run(ctx)
            except Exception as exc:
                err = f"{agent.name} raised unexpectedly: {exc}"
                ctx.logger.exception("[Pipeline] %s", err)
                ctx.errors.append(err)
                if step.critical:
                    ctx.logger.error("[Pipeline] Critical agent failed — aborting pipeline")
                    break
            else:
                elapsed = time.monotonic() - start
                ctx.logger.info("=== %s: done (%.1fs) ===", agent.name, elapsed)

            if not ctx.should_continue:
                ctx.logger.info("[Pipeline] Stopped early after %s", agent.name)
                break

        return ctx
