# core/parser.py
import contextlib
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .enums import MemoryType
from .node import MemoryNode

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
TAG_RE = re.compile(r"(?:^|\s)#([\w/-]+)")
FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)


def parse_file(path: Path, vault_root: Path) -> MemoryNode:
    raw = path.read_text(encoding="utf-8").lstrip("\ufeff")
    frontmatter = {}
    content = raw

    if m := FRONTMATTER_RE.match(raw):
        with contextlib.suppress(yaml.YAMLError):
            frontmatter = yaml.safe_load(m.group(1)) or {}
        content = raw[m.end() :]

    links = [link.lower().replace(" ", "-") for link in WIKILINK_RE.findall(content)]
    tags = TAG_RE.findall(content)

    node_id = path.relative_to(vault_root).with_suffix("").as_posix()
    node_id = node_id.lower().replace(" ", "-")

    stat = path.stat()

    try:
        mem_type = MemoryType(frontmatter.get("memory_type", MemoryType.SEMANTIC.value))
    except (TypeError, ValueError):
        mem_type = MemoryType.SEMANTIC

    created = frontmatter.get("created")
    try:
        created_at = datetime.fromisoformat(created) if created else datetime.now(timezone.utc)
    except (TypeError, ValueError):
        created_at = datetime.now(timezone.utc)

    return MemoryNode(
        id=node_id,
        title=frontmatter.get("title", path.stem),
        content=content.strip(),
        memory_type=mem_type,
        links=links,
        tags=tags,
        salience=float(frontmatter.get("salience", 1.0)),
        created_at=created_at,
        modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
        source_path=str(path),
        frontmatter=frontmatter,
    )
