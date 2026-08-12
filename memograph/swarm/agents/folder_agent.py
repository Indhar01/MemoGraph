"""FolderAgent — swarm agent that reorganizes existing notes into the vault
folder hierarchy defined by ``kernel.hierarchy``.

New notes are already filed by strategy at ``remember()`` time (Steps 2-3).
This agent handles the *existing* corpus: for each candidate node it computes
the target relative path from the kernel's ``HierarchyResolver`` and, if the
file is not already there, moves it via ``VaultStorage.move``.

Safety-first design (mirrors SummarizerAgent's disabled-by-default posture):

* **Disabled by default** (``AgentConfig(enabled=False)``) — opt in explicitly.
* **Dry-run friendly**: honors global/agent dry_run; records ``move_file``
  actions without touching disk.
* **Read-only aware**: if the kernel/server is read-only, it never moves.
* **Move ceiling**: caps moves per cycle so a mis-set strategy can't churn the
  whole vault at once.
* **Identity-safe**: a note's ``id`` lives in frontmatter, so moving the file
  does NOT rewrite any ``[[wikilinks]]`` — the graph is unaffected by location.
* Never touches dotfiles / cache / lock files (VaultStorage guards paths too).

See docs/ADR_SELF_ORGANIZING_HIERARCHY.md (Steps 4-5).
"""

from __future__ import annotations

import logging
from pathlib import Path

from memograph.swarm.agent_base import SwarmAction, SwarmAgent, SwarmCycleReport

logger = logging.getLogger("memograph.swarm.folder")

# Hard safety cap on moves per cycle, independent of max_nodes_per_cycle, so a
# misconfigured resolver cannot reorganize an entire vault in one pass.
_DEFAULT_MOVE_CEILING = 50


class FolderAgent(SwarmAgent):
    """Reorganize existing notes to match the kernel's hierarchy strategy.

    Example:
        >>> agent = FolderAgent(kernel, pheromone, config, config.folder)
        >>> report = await agent.run_cycle(SwarmCycleReport(cycle_id=1))
        >>> print(f"Moved {report.nodes_modified} notes")
    """

    agent_type: str = "folder"

    def _is_readonly(self) -> bool:
        # Respect an explicit readonly flag on the kernel if present.
        return bool(getattr(self.kernel, "readonly", False))

    def _current_rel_path(self, node) -> str | None:
        """Relative POSIX path of the node's file within the vault, or None."""
        src = getattr(node, "source_path", None)
        if not src:
            return None
        try:
            return (
                Path(src)
                .resolve()
                .relative_to(self.kernel.vault_path.resolve())
                .as_posix()
            )
        except (ValueError, OSError):
            return None

    async def run_cycle(self, report: SwarmCycleReport) -> SwarmCycleReport:
        if not self._is_enabled():
            logger.debug("FolderAgent disabled — skipping cycle.")
            return report

        resolver = getattr(self.kernel, "hierarchy", None)
        if resolver is None:
            logger.debug("FolderAgent: kernel has no hierarchy resolver — skipping.")
            return report

        # A flat strategy is a no-op: nothing to reorganize into.
        if getattr(resolver, "strategy_name", "flat") == "flat":
            logger.debug("FolderAgent: strategy is 'flat' — nothing to do.")
            return report

        dry_run = self._effective_dry_run()
        readonly = self._is_readonly()

        # Lazily build a VaultStorage bound to the same root for safe moves.
        from memograph.storage.vault import VaultStorage

        storage = VaultStorage(self.kernel.vault_path)

        candidates = self._candidate_nodes(
            top_k=self.agent_config.max_nodes_per_cycle,
        )
        if not candidates:
            logger.debug("FolderAgent: no candidate nodes.")
            return report

        report.nodes_processed += len(candidates)
        moves_done = 0

        for node in candidates:
            if moves_done >= _DEFAULT_MOVE_CEILING:
                logger.info(
                    "FolderAgent: hit per-cycle move ceiling (%d).",
                    _DEFAULT_MOVE_CEILING,
                )
                break

            try:
                current = self._current_rel_path(node)
                if current is None:
                    action = self._make_skip_action(node.id, reason="no_source_path")
                    report.actions.append(action)
                    continue

                # Slug = the file's stem (identity is the frontmatter id, which
                # equals this for hierarchy purposes; we keep the filename).
                slug = Path(current).stem
                target = resolver.relative_path_for(slug, node.memory_type, node.tags)

                if current == target:
                    self._deposit_pheromone(
                        node_id=node.id,
                        signal_type="skipped",
                        strength=0.2,
                        payload={"reason": "already_filed"},
                    )
                    report.actions.append(
                        self._make_skip_action(node.id, reason="already_filed")
                    )
                    continue

                applied = False
                error: str | None = None
                if not dry_run and not readonly:
                    try:
                        new_path = storage.move(current, target)
                        # Keep the in-memory node's source_path in sync so a
                        # subsequent cycle sees it as already filed.
                        node.source_path = str(new_path)
                        applied = True
                        moves_done += 1
                    except FileExistsError as exc:
                        error = f"destination exists: {exc}"
                    except (FileNotFoundError, ValueError, OSError) as exc:
                        error = str(exc)

                action = SwarmAction(
                    node_id=node.id,
                    agent_type=self.agent_type,
                    action_type="move_file",
                    payload={"from": current, "to": target, "readonly": readonly},
                    confidence=1.0,
                    applied=applied,
                    dry_run=dry_run,
                    error=error,
                )
                report.actions.append(action)
                if applied:
                    report.nodes_modified += 1
                    self._deposit_pheromone(
                        node_id=node.id,
                        signal_type="moved",
                        strength=0.8,
                        payload={"to": target},
                    )
                elif error:
                    report.add_error(self.agent_type, node.id, error)

            except Exception as exc:  # defensive: never let one node kill the cycle
                msg = str(exc)
                logger.warning("FolderAgent: error on node %s: %s", node.id, msg)
                report.add_error(self.agent_type, node.id, msg)

        # After moving files, the incremental indexer's mtime cache is keyed on
        # the OLD relative paths, so a subsequent ingest(force=False) would see
        # spurious deletes/adds and leave the graph stale. Force a clean
        # re-index so the graph reflects the new locations. Ids are unchanged
        # (frontmatter), so wikilinks/backlinks reconcile correctly.
        if moves_done > 0 and not dry_run and not readonly:
            try:
                self.kernel.ingest(force=True)
            except Exception as exc:  # never let reindex failure crash the cycle
                logger.warning("FolderAgent: post-move reindex failed: %s", exc)
                report.add_error(self.agent_type, "*", f"reindex_failed: {exc}")

        if self.agent_type not in report.agents_run:
            report.agents_run.append(self.agent_type)
        return report
