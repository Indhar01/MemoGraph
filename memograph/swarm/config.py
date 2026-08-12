"""Configuration for the MemoGraph swarm intelligence system."""

from dataclasses import dataclass, field


@dataclass
class AgentConfig:
    """Per-agent configuration."""

    enabled: bool = True
    priority: float = 0.5  # 0.0-1.0, affects scheduling order
    max_nodes_per_cycle: int = 20  # max nodes to process per run
    confidence_threshold: float = 0.6  # min confidence to apply changes
    dry_run: bool = False  # if True, log actions but don't write
    cooldown_seconds: float = 3600.0  # min seconds before revisiting a node


@dataclass
class TriggerPolicy:
    """Controls when the swarm auto-triggers a cycle.

    The swarm runs when EITHER condition is met:
    * ``min_new_notes`` notes have arrived since the last cycle AND
      at least ``min_interval_seconds`` has elapsed (burst mode).
    * ``max_interval_seconds`` has elapsed regardless of new content
      (background sweep fallback).

    Set ``mode = "timer"`` to fall back to simple periodic scheduling
    using ``cycle_interval_seconds`` from SwarmConfig.
    """

    mode: str = "event"  # "event" | "timer"
    min_new_notes: int = 3  # notes needed to trigger
    min_interval_seconds: float = 300.0  # cooldown between cycles (5 min)
    max_interval_seconds: float = 14400.0  # force cycle after this (4 hours)


@dataclass
class SwarmConfig:
    """
    Global configuration for the MemoGraph swarm system.

    Controls agent scheduling, pheromone dynamics, and safety limits.

    Example:
        >>> config = SwarmConfig(
        ...     cycle_interval_seconds=3600,
        ...     pheromone_evaporation_rate=0.1,
        ...     max_concurrent_agents=2,
        ... )
    """

    # Scheduling
    cycle_interval_seconds: float = 3600.0  # fallback for timer mode
    pheromone_evaporation_rate: float = (
        0.05  # fraction of pheromone lost per evaporation cycle
    )
    pheromone_evaporation_interval_seconds: float = 21600.0  # evaporate every 6h
    max_concurrent_agents: int = 2  # agents running in parallel
    trigger: TriggerPolicy = field(default_factory=TriggerPolicy)

    # ACO selection parameters
    alpha: float = 1.0  # weight of pheromone avoidance (high = avoid recently-visited)
    beta: float = 2.0  # weight of heuristic desirability (high = prefer needy nodes)

    # Safety
    dry_run: bool = False  # global dry-run override
    require_confirmation: bool = False  # if True, queue actions instead of applying
    max_salience_boost: float = 0.2  # max salience increase per cycle
    max_tags_per_cycle: int = 5  # max new tags to add to a single node

    # Persistence
    pheromone_persist_path: str | None = (
        None  # path to save pheromones (default: vault/.swarm/)
    )
    report_persist_path: str | None = None  # path to save cycle reports

    # Per-agent configs
    tagger: AgentConfig = field(default_factory=AgentConfig)
    linker: AgentConfig = field(default_factory=AgentConfig)
    gap: AgentConfig = field(
        default_factory=lambda: AgentConfig(max_nodes_per_cycle=10)
    )
    salience: AgentConfig = field(default_factory=AgentConfig)
    summarizer: AgentConfig = field(
        default_factory=lambda: AgentConfig(enabled=False)
    )  # LLM-gated
    folder: AgentConfig = field(
        default_factory=lambda: AgentConfig(enabled=False, dry_run=True)
    )  # reorganizes existing notes into the hierarchy; opt-in + dry-run first
