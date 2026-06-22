"""Specialized swarm agents for MemoGraph knowledge curation."""

from memograph.swarm.agents.tagger_agent import TaggerAgent
from memograph.swarm.agents.linker_agent import LinkerAgent
from memograph.swarm.agents.gap_agent import GapAgent
from memograph.swarm.agents.salience_agent import SalienceAgent
from memograph.swarm.agents.summarizer_agent import SummarizerAgent

__all__ = [
    "TaggerAgent",
    "LinkerAgent",
    "GapAgent",
    "SalienceAgent",
    "SummarizerAgent",
]
