"""Shared helpers for the MemoGraph paper-evaluation pipeline.

Used by:
    scripts/parse_experimental_materials.py
    scripts/run_real_experiments.py
    scripts/score_experiments.py
    scripts/calibrate_judge.py
    scripts/insert_real_experimental_data.py
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PAPER_DIR = REPO_ROOT / "paper"
MATERIALS_DIR = PAPER_DIR / "experimental_materials"
RUNS_DIR = PAPER_DIR / "experimental_runs"
QUERIES_JSON = RUNS_DIR / "queries.json"

GENERATOR_MODEL = "claude-sonnet-4-6"
JUDGE_MODEL = "claude-opus-4-7"


def load_env_into_os() -> None:
    """Load .env from repo root into os.environ (idempotent).

    The harness reads secrets via os.environ; .env is the persistence layer.
    """
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        return
    load_dotenv(env_path, override=False)


def require_anthropic_key() -> str:
    load_env_into_os()
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        sys.stderr.write(
            "ERROR: ANTHROPIC_API_KEY is not set. Put it in .env at the repo root "
            f"({REPO_ROOT / '.env'}) as ANTHROPIC_API_KEY=sk-ant-...\n"
        )
        raise SystemExit(2)
    return key


@dataclass
class Query:
    idx: int
    session_id: int
    session_idx: int
    text: str
    retrieval_required: bool
    retrieval_source_sessions: list[int] = field(default_factory=list)
    ground_truth_titles: list[str] = field(default_factory=list)
    memory_to_create: str | None = None
    csc_facts: list[int] = field(default_factory=list)


@dataclass
class Session:
    id: int
    title: str
    queries: list[Query]


@dataclass
class QueriesDoc:
    sessions: list[Session]

    def all_queries(self) -> list[Query]:
        out: list[Query] = []
        for s in self.sessions:
            out.extend(s.queries)
        return out

    def to_json(self) -> dict[str, Any]:
        return {
            "sessions": [
                {
                    "id": s.id,
                    "title": s.title,
                    "queries": [asdict(q) for q in s.queries],
                }
                for s in self.sessions
            ]
        }

    @classmethod
    def from_json_path(cls, path: Path) -> "QueriesDoc":
        raw = json.loads(path.read_text(encoding="utf-8"))
        sessions = []
        for s in raw["sessions"]:
            queries = [Query(**q) for q in s["queries"]]
            sessions.append(Session(id=s["id"], title=s["title"], queries=queries))
        return cls(sessions=sessions)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
