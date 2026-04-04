# core/parser.py
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .enums import MemoryType
from .node import MemoryNode

logger = logging.getLogger("memograph.parser")

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
TAG_RE = re.compile(r"(?:^|\s)#([\w/-]+)")
FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)


def parse_file(path: Path, vault_root: Path) -> MemoryNode | None:
    """Parse markdown file with error recovery.
    
    Returns None if file cannot be parsed (logs error).
    """
    try:
        raw = path.read_text(encoding="utf-8").lstrip("\ufeff")
    except UnicodeDecodeError as e:
        logger.error(f"Cannot decode {path.name}: {e} - skipping")
        return None
    except PermissionError as e:
        logger.error(f"Permission denied {path.name}: {e} - skipping")
        return None
    
    frontmatter: dict[str, Any] = {}
    content = raw
    
    # Parse frontmatter with explicit error handling
    if m := FRONTMATTER_RE.match(raw):
        try:
            frontmatter = yaml.safe_load(m.group(1))
            if not isinstance(frontmatter, dict):
                logger.error(
                    f"Invalid frontmatter in {path.name}: "
                    f"not a dict - skipping"
                )
                return None
        except yaml.YAMLError as e:
            logger.error(
                f"Corrupt YAML in {path.name}: {e}\n"
                f"  Fix the YAML or remove the file - skipping"
            )
            return None
        
        content = raw[m.end():]
    
    # Validate required fields
    if not frontmatter.get('title'):
        logger.warning(
            f"Missing 'title' in {path.name} - using filename"
        )
    
    # Parse with safe defaults
    try:
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
            created_at = (
                datetime.fromisoformat(created) if created else datetime.now(timezone.utc)
            )
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
    except Exception as e:
        logger.error(f"Unexpected error parsing {path.name}: {e} - skipping")
        return None
