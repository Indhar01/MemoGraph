"""Backwards-compatibility alias.

EnhancedVaultGraph features have been merged into VaultGraph.
This module re-exports VaultGraph as EnhancedVaultGraph for existing code.
"""

from memograph.core.graph import GraphStats, VaultGraph

# Backwards-compat aliases
EnhancedVaultGraph = VaultGraph

__all__ = ["EnhancedVaultGraph", "GraphStats"]
