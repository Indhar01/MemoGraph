"""
SwarmOrchestrator — schedules and runs all swarm agents for MemoGraph.

The orchestrator is the single entry point for running a swarm cycle.
It manages agent registration, pheromone evaporation scheduling,
cycle reporting, and optional background scheduling.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from memograph.swarm.agent_base import SwarmAgent, SwarmCycleReport
from memograph.swarm.config import SwarmConfig
from memograph.swarm.pheromone import PheromoneMap

if TYPE_CHECKING:
    from memograph.core.kernel import MemoryKernel

logger = logging.getLogger("memograph.swarm.orchestrator")


class SwarmOrchestrator:
    """
    Coordinates all swarm agents for autonomous knowledge curation.

    The orchestrator:
    * Holds a registry of :class:`~memograph.swarm.agent_base.SwarmAgent`
      instances sorted by priority.
    * Runs a single cycle on demand via :py:meth:`run_cycle`.
    * Schedules recurring background cycles via :py:meth:`start` /
      :py:meth:`stop`.
    * Triggers pheromone evaporation on its own schedule.
    * Persists cycle reports and pheromones to disk (optional).

    Example:
        >>> from memograph.swarm import SwarmOrchestrator, SwarmConfig
        >>> config = SwarmConfig(dry_run=True)
        >>> orchestrator = SwarmOrchestrator(kernel=kernel, config=config)
        >>> report = await orchestrator.run_cycle()
        >>> print(f"Cycle {report.cycle_id}: {report.nodes_processed} nodes processed")
    """

    def __init__(
        self,
        kernel: "MemoryKernel",
        config: SwarmConfig | None = None,
        pheromone_map: PheromoneMap | None = None,
    ) -> None:
        """
        Initialise the orchestrator.

        Args:
            kernel:        Live MemoryKernel instance.
            config:        SwarmConfig; a default instance is created if None.
            pheromone_map: Existing PheromoneMap to reuse; a new one is
                           created (and loaded from disk if configured) if None.
        """
        self.kernel = kernel
        self.config = config or SwarmConfig()

        # Resolve persist path for pheromones
        pheromone_path: Path | None = None
        if self.config.pheromone_persist_path:
            pheromone_path = Path(self.config.pheromone_persist_path)
        elif hasattr(kernel, "vault_path"):
            pheromone_path = Path(kernel.vault_path) / ".swarm" / "pheromones.json"

        self.pheromone = pheromone_map or PheromoneMap(persist_path=pheromone_path)

        # Ordered list of registered agents (sorted by priority desc)
        self._agents: list[SwarmAgent] = []

        # Cycle counter
        self._cycle_count: int = 0

        # Last evaporation timestamp
        self._last_evaporation: datetime = datetime.now(timezone.utc)

        # Last cycle timestamp (for trigger policy)
        self._last_cycle_time: datetime = datetime.now(timezone.utc)

        # Event-driven trigger state
        self._pending_new_notes: int = 0
        self._dirty_node_ids: set[str] = set()

        # Background task handle
        self._background_task: asyncio.Task | None = None

        # Report history (last N cycles kept in memory)
        self._report_history: list[SwarmCycleReport] = []
        self._max_report_history: int = 50

        logger.info(
            "SwarmOrchestrator initialised (dry_run=%s, trigger=%s)",
            self.config.dry_run,
            self.config.trigger.mode,
        )

    # ------------------------------------------------------------------
    # Agent registration
    # ------------------------------------------------------------------

    def register(self, agent: SwarmAgent) -> None:
        """Register a swarm agent with the orchestrator.

        Agents are kept sorted by ``agent_config.priority`` (descending)
        so higher-priority agents run first within a cycle.

        Args:
            agent: A concrete SwarmAgent instance to register.

        Example:
            >>> orchestrator.register(TaggerAgent(kernel, pheromone, config, config.tagger))
        """
        self._agents.append(agent)
        self._agents.sort(key=lambda a: a.agent_config.priority, reverse=True)
        logger.info(
            "Registered agent: %s (priority=%.2f)",
            agent.agent_type,
            agent.agent_config.priority,
        )

    def unregister(self, agent_type: str) -> int:
        """Unregister all agents of a given type.

        Args:
            agent_type: Agent type string to remove.

        Returns:
            Number of agents removed.
        """
        before = len(self._agents)
        self._agents = [a for a in self._agents if a.agent_type != agent_type]
        removed = before - len(self._agents)
        if removed:
            logger.info("Unregistered %d agent(s) of type '%s'", removed, agent_type)
        return removed

    def get_agents(self) -> list[SwarmAgent]:
        """Return a copy of the current agent list (ordered by priority)."""
        return list(self._agents)

    # ------------------------------------------------------------------
    # Event-driven trigger API
    # ------------------------------------------------------------------

    def notify_new_content(self, node_id: str) -> bool:
        """Notify the orchestrator that a new note was created or modified.

        Called by the kernel on ``remember()`` or ``update_many()``. The
        orchestrator tracks dirty nodes and pending note count. If the
        trigger policy conditions are met, returns True (caller should
        schedule a cycle).

        Args:
            node_id: ID of the new/modified memory node.

        Returns:
            True if a swarm cycle should be triggered now.
        """
        self._pending_new_notes += 1
        self._dirty_node_ids.add(node_id)

        trigger = self.config.trigger
        if trigger.mode != "event":
            return False

        now = datetime.now(timezone.utc)
        elapsed = (now - self._last_cycle_time).total_seconds()

        # Check: enough notes AND past cooldown?
        if (
            self._pending_new_notes >= trigger.min_new_notes
            and elapsed >= trigger.min_interval_seconds
        ):
            logger.info(
                "Trigger policy met: %d new notes, %.0fs elapsed",
                self._pending_new_notes,
                elapsed,
            )
            return True

        return False

    def should_force_cycle(self) -> bool:
        """Check if max_interval has elapsed (fallback sweep).

        Returns:
            True if max_interval_seconds has passed since last cycle.
        """
        trigger = self.config.trigger
        if trigger.mode != "event":
            return False
        now = datetime.now(timezone.utc)
        elapsed = (now - self._last_cycle_time).total_seconds()
        return elapsed >= trigger.max_interval_seconds

    @property
    def dirty_node_ids(self) -> set[str]:
        """Node IDs modified since the last cycle. Agents can prioritize these."""
        return set(self._dirty_node_ids)

    # ------------------------------------------------------------------
    # Single cycle execution
    # ------------------------------------------------------------------

    async def run_cycle(self) -> SwarmCycleReport:
        """Execute one full swarm cycle across all enabled agents.

        Steps:
        1. Build a fresh SwarmCycleReport.
        2. Optionally trigger pheromone evaporation.
        3. Run each enabled agent sequentially (respects max_concurrent_agents).
        4. Finalise and persist the report.
        5. Save pheromones.

        Returns:
            The completed SwarmCycleReport.
        """
        self._cycle_count += 1
        report = SwarmCycleReport(
            cycle_id=self._cycle_count,
            dry_run=self.config.dry_run,
        )
        logger.info("=== Swarm cycle %d started ===", self._cycle_count)

        # Maybe evaporate pheromones
        self._maybe_evaporate()

        # Run agents in phases to respect data dependencies:
        # Phase 1: Tagger (tags must exist before linking)
        # Phase 2: Linker (links must exist before gap detection)
        # Phase 3: Gap, Salience, Summarizer (independent, parallel)
        enabled_agents = [a for a in self._agents if a._is_enabled()]
        if not enabled_agents:
            logger.warning("No enabled agents registered; cycle will be empty.")

        phase_order = ["tagger", "linker"]
        phases: list[list[SwarmAgent]] = []

        # Build ordered phases
        for agent_type in phase_order:
            phase_agents = [a for a in enabled_agents if a.agent_type == agent_type]
            if phase_agents:
                phases.append(phase_agents)

        # Remaining agents run together in the final phase
        phase_types = set(phase_order)
        remaining = [a for a in enabled_agents if a.agent_type not in phase_types]
        if remaining:
            phases.append(remaining)

        semaphore = asyncio.Semaphore(max(1, self.config.max_concurrent_agents))

        async def _run_agent(agent: SwarmAgent) -> None:
            async with semaphore:
                try:
                    logger.info("Running agent: %s", agent.agent_type)
                    await agent.run_cycle(report)
                    if agent.agent_type not in report.agents_run:
                        report.agents_run.append(agent.agent_type)
                except Exception as exc:
                    msg = str(exc)
                    report.add_error(agent.agent_type, "", msg)
                    logger.error(
                        "Agent %s raised an error: %s",
                        agent.agent_type,
                        msg,
                        exc_info=True,
                    )

        # Execute phases sequentially; agents within a phase run in parallel
        for phase in phases:
            await asyncio.gather(*[_run_agent(a) for a in phase])

        # Compute nodes_modified from applied actions
        modified_ids = {a.node_id for a in report.actions if a.applied}
        report.nodes_modified = len(modified_ids)

        # Finalise report
        report.finish()
        report.pheromone_summary = self.pheromone.summary()

        # Persist
        self._save_report(report)
        self.pheromone.save()

        logger.info(
            "=== Swarm cycle %d finished in %.1fs: %d nodes processed, %d modified, %d errors ===",
            self._cycle_count,
            report.duration_seconds or 0.0,
            report.nodes_processed,
            report.nodes_modified,
            len(report.errors),
        )

        # Reset trigger state
        self._last_cycle_time = datetime.now(timezone.utc)
        self._pending_new_notes = 0
        self._dirty_node_ids.clear()

        # Keep in-memory history
        self._report_history.append(report)
        if len(self._report_history) > self._max_report_history:
            self._report_history.pop(0)

        return report

    # ------------------------------------------------------------------
    # Pheromone evaporation
    # ------------------------------------------------------------------

    def _maybe_evaporate(self) -> None:
        """Evaporate pheromones if the evaporation interval has elapsed."""
        now = datetime.now(timezone.utc)
        elapsed = (now - self._last_evaporation).total_seconds()
        if elapsed >= self.config.pheromone_evaporation_interval_seconds:
            pruned = self.pheromone.evaporate(
                rate=self.config.pheromone_evaporation_rate
            )
            self._last_evaporation = now
            logger.info(
                "Pheromone evaporation: rate=%.3f, pruned=%d deposits",
                self.config.pheromone_evaporation_rate,
                pruned,
            )

    # ------------------------------------------------------------------
    # Report persistence
    # ------------------------------------------------------------------

    def _save_report(self, report: SwarmCycleReport) -> None:
        """Persist a cycle report to disk if report_persist_path is configured."""
        if not self.config.report_persist_path:
            return
        base = Path(self.config.report_persist_path)
        base.mkdir(parents=True, exist_ok=True)
        filename = base / f"cycle_{report.cycle_id:06d}.json"
        try:
            with open(filename, "w", encoding="utf-8") as fh:
                json.dump(report.to_dict(), fh, indent=2)
            logger.debug("Cycle report saved to %s", filename)
        except Exception as exc:
            logger.warning("Failed to save cycle report: %s", exc)

    # ------------------------------------------------------------------
    # Background scheduler
    # ------------------------------------------------------------------

    async def _scheduler_loop(self) -> None:
        """Async background loop that triggers cycles based on policy.

        In "event" mode: polls every 30s to check if trigger conditions
        are met (note count threshold or max interval elapsed).
        In "timer" mode: sleeps for cycle_interval_seconds between cycles.
        """
        trigger = self.config.trigger

        if trigger.mode == "timer":
            logger.info(
                "Swarm scheduler started (timer mode, interval=%.0fs)",
                self.config.cycle_interval_seconds,
            )
            while True:
                await asyncio.sleep(self.config.cycle_interval_seconds)
                try:
                    await self.run_cycle()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.error("Scheduled cycle failed: %s", exc, exc_info=True)
        else:
            # Event-driven mode: check conditions every 30s
            logger.info(
                "Swarm scheduler started (event mode, "
                "min_notes=%d, min_interval=%.0fs, max_interval=%.0fs)",
                trigger.min_new_notes,
                trigger.min_interval_seconds,
                trigger.max_interval_seconds,
            )
            while True:
                await asyncio.sleep(30)
                try:
                    if self.should_force_cycle() or (
                        self._pending_new_notes >= trigger.min_new_notes
                        and (
                            datetime.now(timezone.utc) - self._last_cycle_time
                        ).total_seconds()
                        >= trigger.min_interval_seconds
                    ):
                        await self.run_cycle()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.error("Event-triggered cycle failed: %s", exc, exc_info=True)

    def start(self) -> None:
        """Start the background scheduler (non-blocking).

        Must be called from within a running async event loop (e.g., inside
        an ``async def`` or after ``asyncio.run()`` has started).

        Schedules :py:meth:`run_cycle` to execute every
        ``config.cycle_interval_seconds`` seconds.

        Raises:
            RuntimeError: If the scheduler is already running or no event loop
                is active.
        """
        if self._background_task is not None and not self._background_task.done():
            raise RuntimeError("SwarmOrchestrator scheduler is already running.")
        loop = asyncio.get_running_loop()
        self._background_task = loop.create_task(self._scheduler_loop())
        logger.info("SwarmOrchestrator background scheduler started.")

    async def stop(self) -> None:
        """Stop the background scheduler gracefully.

        Cancels the scheduler task and waits for it to finish.
        """
        if self._background_task is None or self._background_task.done():
            logger.debug("stop() called but scheduler is not running.")
            return
        self._background_task.cancel()
        try:
            await self._background_task
        except asyncio.CancelledError:
            pass
        finally:
            self._background_task = None
        logger.info("SwarmOrchestrator background scheduler stopped.")

    @property
    def is_running(self) -> bool:
        """True if the background scheduler is active."""
        return self._background_task is not None and not self._background_task.done()

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------

    def get_last_report(self) -> SwarmCycleReport | None:
        """Return the most recent SwarmCycleReport, or None if no cycle has run."""
        return self._report_history[-1] if self._report_history else None

    def get_report_history(self) -> list[SwarmCycleReport]:
        """Return all in-memory cycle reports (oldest first)."""
        return list(self._report_history)

    def status(self) -> dict[str, Any]:
        """Return a human-readable status dict for monitoring / health checks."""
        last = self.get_last_report()
        return {
            "cycles_run": self._cycle_count,
            "scheduler_running": self.is_running,
            "agents": [
                {
                    "type": a.agent_type,
                    "enabled": a.agent_config.enabled,
                    "priority": a.agent_config.priority,
                    "dry_run": a._effective_dry_run(),
                }
                for a in self._agents
            ],
            "pheromone_summary": self.pheromone.summary(),
            "last_cycle": last.to_dict() if last else None,
            "config": {
                "cycle_interval_seconds": self.config.cycle_interval_seconds,
                "dry_run": self.config.dry_run,
                "max_concurrent_agents": self.config.max_concurrent_agents,
                "pheromone_evaporation_rate": self.config.pheromone_evaporation_rate,
            },
        }

    def __repr__(self) -> str:
        return (
            f"<SwarmOrchestrator agents={len(self._agents)} "
            f"cycles={self._cycle_count} running={self.is_running}>"
        )
