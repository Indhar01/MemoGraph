"""Infrastructure helpers for CLI commands.

This module provides functions for export, backup, configuration,
and statistics commands.
"""

import gzip
import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .cli_helpers import find_all_memories, find_memories_by_filter, format_csv_output
from .core.kernel import MemoryKernel


def run_export_command(kernel: MemoryKernel, args) -> None:
    """Handle export command for exporting vault data.

    Args:
        kernel: MemoryKernel instance
        args: Parsed command-line arguments
    """
    vault_path = Path(kernel.vault_path)
    output_path = Path(args.output)

    # Find memories to export
    if args.filter_tags:
        memories = find_memories_by_filter(vault_path, tags=args.filter_tags)
    else:
        memories = find_all_memories(vault_path)

    if not memories:
        print("No memories to export")
        return

    print(f"\n=== Exporting {len(memories)} memories ===")
    print(f"Format: {args.format}")
    print(f"Output: {output_path}")

    try:
        if args.format == "json":
            _export_json(memories, output_path, args.compress)
        elif args.format == "csv":
            _export_csv(memories, output_path, args.compress)
        elif args.format == "markdown":
            _export_markdown(memories, output_path, vault_path)
        elif args.format == "zip":
            _export_zip(memories, output_path, vault_path)

        print(f"\n[OK] Export complete: {output_path}")

        # Show file size
        if output_path.exists():
            size_mb = output_path.stat().st_size / (1024 * 1024)
            print(f"  Size: {size_mb:.2f} MB")

    except Exception as e:
        print(f"\n[ERROR] Export failed: {e}")


def run_import_backup_command(kernel: MemoryKernel, args) -> None:
    """Handle import-backup command for restoring from backup.

    Args:
        kernel: MemoryKernel instance
        args: Parsed command-line arguments
    """
    backup_path = Path(args.backup_file)

    if not backup_path.exists():
        print(f"Error: Backup file not found: {backup_path}")
        return

    vault_path = Path(kernel.vault_path)

    print("\n=== Importing from backup ===")
    print(f"Source: {backup_path}")
    print(f"Target: {vault_path}")
    print(f"Mode: {'merge' if args.merge else 'replace'}")

    # Confirmation for replace mode
    if not args.merge:
        response = input(
            "\n[WARNING]  Replace mode will delete existing vault! Continue? (y/N): "
        )
        if response.lower() != "y":
            print("Import cancelled")
            return

    try:
        # Load backup
        if backup_path.suffix.lower() == ".zip":
            memories = _import_from_zip(backup_path)
        elif backup_path.suffix.lower() in [".json", ".gz"]:
            memories = _import_from_json(backup_path)
        else:
            print(f"Error: Unsupported backup format: {backup_path.suffix}")
            return

        print(f"\nFound {len(memories)} memories in backup")

        # Clear vault if replace mode
        if not args.merge:
            print("Clearing existing vault...")
            for md_file in vault_path.rglob("*.md"):
                md_file.unlink()

        # Import memories
        print("Importing memories...")
        success_count = 0
        skip_count = 0
        error_count = 0

        try:
            from tqdm import tqdm

            iterator = tqdm(memories, desc="Importing", unit="memory")
        except ImportError:
            iterator = memories

        for memory in iterator:
            try:
                # Check for duplicates if skip mode
                if args.skip_duplicates:
                    from .cli_helpers import find_memory_by_id

                    if find_memory_by_id(vault_path, memory.get("id", "")):
                        skip_count += 1
                        continue

                # Create memory file
                from .core.enums import MemoryType

                kernel.remember(
                    title=memory.get("title", "Untitled"),
                    content=memory.get("content", ""),
                    memory_type=MemoryType(memory.get("memory_type", "fact")),
                    tags=memory.get("tags", []),
                    salience=memory.get("salience", 0.5),
                )
                success_count += 1
            except Exception:
                error_count += 1

        print("\n=== Import Summary ===")
        print(f"[OK] Imported: {success_count}")
        print(f"[SKIP] Skipped: {skip_count}")
        print(f"[ERROR] Failed: {error_count}")

        # Re-ingest
        if success_count > 0:
            print("\nRebuilding graph...")
            stats = kernel.ingest(force=True)
            print(f"[OK] Indexed {stats['indexed']} files")

    except Exception as e:
        print(f"\n[ERROR] Import failed: {e}")


def run_backup_command(kernel: MemoryKernel, args) -> None:
    """Handle backup command for creating vault backups.

    Args:
        kernel: MemoryKernel instance
        args: Parsed command-line arguments
    """
    vault_path = Path(kernel.vault_path)
    dest_dir = Path(args.destination)

    # Create destination directory
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Generate backup filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    vault_name = vault_path.name
    backup_name = f"{vault_name}_backup_{timestamp}"

    if args.compress:
        backup_path = dest_dir / f"{backup_name}.zip"
    else:
        backup_path = dest_dir / backup_name

    print("\n=== Creating Backup ===")
    print(f"Source: {vault_path}")
    print(f"Destination: {backup_path}")

    try:
        if args.compress:
            # Create ZIP backup
            with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                for md_file in vault_path.rglob("*.md"):
                    arcname = md_file.relative_to(vault_path)
                    zipf.write(md_file, arcname)
        else:
            # Create directory backup
            shutil.copytree(vault_path, backup_path, dirs_exist_ok=True)

        print(f"\n[OK] Backup created: {backup_path}")

        # Show size
        if backup_path.exists():
            if backup_path.is_file():
                size_mb = backup_path.stat().st_size / (1024 * 1024)
            else:
                size_mb = sum(
                    f.stat().st_size for f in backup_path.rglob("*") if f.is_file()
                ) / (1024 * 1024)
            print(f"  Size: {size_mb:.2f} MB")

        # Cleanup old backups
        if args.keep > 0:
            _cleanup_old_backups(dest_dir, vault_name, args.keep)

    except Exception as e:
        print(f"\n[ERROR] Backup failed: {e}")


def run_config_command(kernel: MemoryKernel, args) -> None:
    """Handle config command for configuration management.

    Args:
        kernel: MemoryKernel instance
        args: Parsed command-line arguments
    """
    config_dir = Path.home() / ".memograph"
    config_file = config_dir / "config.yaml"

    # Ensure config directory exists
    config_dir.mkdir(parents=True, exist_ok=True)

    # Load existing config
    if config_file.exists():
        with open(config_file, "r") as f:
            config = yaml.safe_load(f) or {}
    else:
        config = {
            "default_vault": str(kernel.vault_path),
            "default_provider": "ollama",
            "profiles": {},
        }

    if args.config_command == "set":
        # Set configuration value
        config[args.key] = args.value

        with open(config_file, "w") as f:
            yaml.dump(config, f, default_flow_style=False)

        print(f"[OK] Set {args.key} = {args.value}")

    elif args.config_command == "get":
        # Get configuration value
        value = config.get(args.key, "Not set")
        print(f"{args.key}: {value}")

    elif args.config_command == "list":
        # List all configuration
        print("\n=== Configuration ===")
        for key, value in config.items():
            if key != "profiles":
                print(f"{key}: {value}")

        if config.get("profiles"):
            print("\n=== Profiles ===")
            for name, profile in config["profiles"].items():
                print(f"\n{name}:")
                for key, value in profile.items():
                    print(f"  {key}: {value}")

    elif args.config_command == "profile":
        # Manage profiles
        if args.action == "create":
            if not args.name:
                print("Error: Profile name required")
                return

            config["profiles"][args.name] = {
                "vault": str(kernel.vault_path),
                "provider": config.get("default_provider", "ollama"),
            }

            with open(config_file, "w") as f:
                yaml.dump(config, f, default_flow_style=False)

            print(f"[OK] Created profile: {args.name}")

        elif args.action == "use":
            if not args.name:
                print("Error: Profile name required")
                return

            if args.name not in config.get("profiles", {}):
                print(f"Error: Profile '{args.name}' not found")
                return

            config["active_profile"] = args.name

            with open(config_file, "w") as f:
                yaml.dump(config, f, default_flow_style=False)

            print(f"[OK] Switched to profile: {args.name}")

        elif args.action == "list":
            profiles = config.get("profiles", {})
            if not profiles:
                print("No profiles configured")
            else:
                print("\n=== Profiles ===")
                active = config.get("active_profile")
                for name in profiles:
                    marker = " (active)" if name == active else ""
                    print(f"  • {name}{marker}")

        elif args.action == "delete":
            if not args.name:
                print("Error: Profile name required")
                return

            if args.name in config.get("profiles", {}):
                del config["profiles"][args.name]

                with open(config_file, "w") as f:
                    yaml.dump(config, f, default_flow_style=False)

                print(f"[OK] Deleted profile: {args.name}")
            else:
                print(f"Error: Profile '{args.name}' not found")


def run_stats_command(kernel: MemoryKernel, args) -> None:
    """Handle stats command for vault statistics.

    Args:
        kernel: MemoryKernel instance
        args: Parsed command-line arguments
    """
    vault_path = Path(kernel.vault_path)

    # Collect statistics
    memories = find_all_memories(vault_path)

    if not memories:
        print("No memories in vault")
        return

    # Calculate stats
    stats = {
        "total_memories": len(memories),
        "by_type": {},
        "by_tag": {},
        "salience_avg": 0.0,
        "salience_distribution": {"low": 0, "medium": 0, "high": 0},
        "total_tags": 0,
        "total_content_size": 0,
    }

    salience_sum = 0.0
    all_tags = set()

    for memory in memories:
        # Type distribution
        mem_type = memory.get("memory_type", "unknown")
        stats["by_type"][mem_type] = stats["by_type"].get(mem_type, 0) + 1

        # Tag distribution
        tags = memory.get("tags", [])
        for tag in tags:
            stats["by_tag"][tag] = stats["by_tag"].get(tag, 0) + 1
            all_tags.add(tag)

        # Salience stats
        salience = memory.get("salience", 0.0)
        salience_sum += salience

        if salience < 0.4:
            stats["salience_distribution"]["low"] += 1
        elif salience < 0.7:
            stats["salience_distribution"]["medium"] += 1
        else:
            stats["salience_distribution"]["high"] += 1

        # Content size
        content = memory.get("content", "")
        stats["total_content_size"] += len(content)

    stats["salience_avg"] = salience_sum / len(memories) if memories else 0.0
    stats["total_tags"] = len(all_tags)

    # Output
    if args.format == "json":
        print(json.dumps(stats, indent=2))
    else:
        _print_stats_text(stats, args.detailed)


def _export_json(
    memories: list[dict[str, Any]], output_path: Path, compress: bool
) -> None:
    """Export memories to JSON format."""
    from datetime import datetime

    # Clean memories for JSON
    clean_memories = []
    for memory in memories:
        clean_mem = {}
        for k, v in memory.items():
            if k == "path":
                continue
            if isinstance(v, datetime):
                clean_mem[k] = v.isoformat()
            else:
                clean_mem[k] = v
        clean_memories.append(clean_mem)

    data = {
        "export_date": datetime.now().isoformat(),
        "version": "1.0",
        "count": len(clean_memories),
        "memories": clean_memories,
    }

    json_str = json.dumps(data, indent=2, ensure_ascii=False)

    if compress:
        output_path = output_path.with_suffix(".json.gz")
        with gzip.open(output_path, "wt", encoding="utf-8") as f:
            f.write(json_str)
    else:
        output_path.write_text(json_str, encoding="utf-8")


def _export_csv(
    memories: list[dict[str, Any]], output_path: Path, compress: bool
) -> None:
    """Export memories to CSV format."""
    csv_content = format_csv_output(memories)

    if compress:
        output_path = output_path.with_suffix(".csv.gz")
        with gzip.open(output_path, "wt", encoding="utf-8") as f:
            f.write(csv_content)
    else:
        output_path.write_text(csv_content, encoding="utf-8")


def _export_markdown(
    memories: list[dict[str, Any]], output_path: Path, vault_path: Path
) -> None:
    """Export memories as markdown files in a directory."""
    output_path.mkdir(parents=True, exist_ok=True)

    for memory in memories:
        # Copy original file
        source_path = memory.get("path")
        if source_path and source_path.exists():
            rel_path = source_path.relative_to(vault_path)
            dest_path = output_path / rel_path
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, dest_path)


def _export_zip(
    memories: list[dict[str, Any]], output_path: Path, vault_path: Path
) -> None:
    """Export memories as a ZIP archive."""
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for memory in memories:
            source_path = memory.get("path")
            if source_path and source_path.exists():
                arcname = source_path.relative_to(vault_path)
                zipf.write(source_path, arcname)


def _import_from_json(backup_path: Path) -> list[dict[str, Any]]:
    """Import memories from JSON backup."""
    if backup_path.suffix.lower() == ".gz":
        with gzip.open(backup_path, "rt", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = json.loads(backup_path.read_text(encoding="utf-8"))

    if isinstance(data, dict) and "memories" in data:
        return data["memories"]
    elif isinstance(data, list):
        return data
    else:
        raise ValueError("Invalid backup format")


def _import_from_zip(backup_path: Path) -> list[dict[str, Any]]:
    """Import memories from ZIP backup."""
    import tempfile

    memories = []

    with tempfile.TemporaryDirectory() as tmpdir:
        with zipfile.ZipFile(backup_path, "r") as zipf:
            zipf.extractall(tmpdir)

        # Read all markdown files
        from .cli_helpers import read_memory_file

        for md_file in Path(tmpdir).rglob("*.md"):
            try:
                memory = read_memory_file(md_file)
                memories.append(memory)
            except Exception:
                continue

    return memories


def _cleanup_old_backups(dest_dir: Path, vault_name: str, keep: int) -> None:
    """Remove old backups, keeping only the most recent N."""
    # Find all backups for this vault
    pattern = f"{vault_name}_backup_*"
    backups = sorted(
        dest_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True
    )

    # Remove old backups
    removed = 0
    for backup in backups[keep:]:
        try:
            if backup.is_file():
                backup.unlink()
            else:
                shutil.rmtree(backup)
            removed += 1
        except Exception:
            pass

    if removed > 0:
        print(f"  Cleaned up {removed} old backup(s)")


def _print_stats_text(stats: dict[str, Any], detailed: bool) -> None:
    """Print statistics in text format."""
    print("\n=== Vault Statistics ===\n")
    print(f"Total Memories: {stats['total_memories']}")
    print(f"Total Tags: {stats['total_tags']}")
    print(f"Average Salience: {stats['salience_avg']:.2f}")

    # Content size
    size_mb = stats["total_content_size"] / (1024 * 1024)
    print(f"Total Content: {size_mb:.2f} MB")

    # Type distribution
    print("\n=== By Type ===")
    for mem_type, count in sorted(
        stats["by_type"].items(), key=lambda x: x[1], reverse=True
    ):
        bar = "#" * min(int(count / stats["total_memories"] * 50), 50)
        print(f"{mem_type:15} {bar} {count}")

    # Salience distribution
    print("\n=== Salience Distribution ===")
    for level, count in stats["salience_distribution"].items():
        bar = "#" * min(int(count / stats["total_memories"] * 50), 50)
        print(f"{level:15} {bar} {count}")

    # Top tags
    if detailed and stats["by_tag"]:
        print("\n=== Top Tags ===")
        top_tags = sorted(stats["by_tag"].items(), key=lambda x: x[1], reverse=True)[
            :10
        ]
        for tag, count in top_tags:
            bar = "#" * min(int(count / stats["total_memories"] * 50), 50)
            print(f"{tag:15} {bar} {count}")


def run_eval_command(kernel: MemoryKernel, args: Any) -> None:
    """Run `memograph eval retrieval <gold.json>`.

    Deterministic, offline retrieval-ranking evaluation (no LLM). Complements
    the LLM-judged benchmark in benchmarks/ — this guards ranking regressions
    in CI. Exits non-zero when --fail-under is set and mean f1@k is below it.
    """
    import sys

    from .eval.retrieval import evaluate_retrieval, load_gold_set

    sub = getattr(args, "eval_command", None)
    if sub != "retrieval":
        print(
            "Usage: memograph eval retrieval <gold.json> [--top-k N] [--format text|json]"
        )
        sys.exit(2)

    # Make sure the graph is populated before scoring.
    kernel.ingest(force=False)

    try:
        gold = load_gold_set(args.gold)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Failed to load gold set {args.gold!r}: {exc}")
        sys.exit(2)

    if not gold:
        print("Gold set is empty; nothing to evaluate.")
        sys.exit(2)

    report = evaluate_retrieval(kernel, gold, top_k=args.top_k, depth=args.depth)

    if args.format == "json":
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(f"=== Retrieval eval: {len(report.cases)} cases, k={report.k} ===")
        print("Aggregate (macro-averaged):")
        for name, value in sorted(report.aggregate.items()):
            print(f"  {name:14} {value:.4f}")
        print("\nPer-query:")
        for case in report.cases:
            f1 = case.metrics.get(f"f1@{report.k}", 0.0)
            hit = case.metrics.get(f"hit@{report.k}", 0.0)
            flag = "" if hit else "  <-- MISS"
            print(f"  f1={f1:.3f} mrr={case.metrics['mrr']:.3f} | {case.query}{flag}")

    if args.fail_under is not None:
        mean_f1 = report.aggregate.get(f"f1@{report.k}", 0.0)
        if mean_f1 < args.fail_under:
            print(
                f"\nFAIL: mean f1@{report.k}={mean_f1:.4f} < "
                f"--fail-under={args.fail_under}"
            )
            sys.exit(1)
        print(f"\nPASS: mean f1@{report.k}={mean_f1:.4f} >= {args.fail_under}")


def run_reorganize_command(kernel: MemoryKernel, args: Any) -> None:
    """Run `memograph reorganize` — file existing notes into a folder hierarchy.

    Dry-run by default (prints the move plan). Pass --apply to move files.
    Drives the HierarchyResolver + VaultStorage.move directly (no swarm
    dependency). Identity lives in frontmatter, so moves never break
    [[wikilinks]]. See docs/ADR_SELF_ORGANIZING_HIERARCHY.md.
    """
    import sys
    from pathlib import Path

    from .core.hierarchy import HierarchyResolver
    from .core.parser import parse_file
    from .storage.vault import VaultStorage

    strategy = getattr(args, "strategy", "by_type")
    apply = getattr(args, "apply", False)
    fmt = getattr(args, "format", "text")

    if getattr(args, "backfill_ids", False):
        result = kernel.backfill_ids(dry_run=not apply)
        if fmt == "text":
            verb = "would backfill" if not apply else "backfilled"
            print(f"id backfill: {verb} {result['updated']} note(s).")

    try:
        resolver = HierarchyResolver(strategy)
    except ValueError as exc:
        print(f"Invalid strategy: {exc}")
        sys.exit(2)

    vault_root = kernel.vault_path
    storage = VaultStorage(vault_root)

    # Build the move plan by re-parsing each note (so slug/type reflect disk).
    plan: list[tuple[str, str]] = []
    for md in sorted(vault_root.rglob("*.md")):
        rel = md.relative_to(vault_root)
        # Skip dotfiles / cache / lock files living in the vault.
        if any(part.startswith(".") for part in rel.parts):
            continue
        node = parse_file(md, vault_root)
        if node is None:
            continue
        slug = md.stem
        target = resolver.relative_path_for(slug, node.memory_type, node.tags)
        current = rel.as_posix()
        if current != target:
            plan.append((current, target))

    if fmt == "json":
        print(
            json.dumps(
                {
                    "strategy": strategy,
                    "apply": apply,
                    "moves": [{"from": a, "to": b} for a, b in plan],
                    "count": len(plan),
                },
                indent=2,
            )
        )
    else:
        if not plan:
            print(f"Nothing to reorganize — all notes already match '{strategy}'.")
        else:
            header = "Planned moves" if not apply else "Applying moves"
            print(f"=== {header} ({strategy}): {len(plan)} ===")
            for src, dst in plan:
                print(f"  {src}  ->  {dst}")

    if not plan or not apply:
        if plan and not apply and fmt == "text":
            print("\nDry-run only. Re-run with --apply to move files.")
        return

    # Confirmation gate for the destructive path.
    if not getattr(args, "yes", False):
        reply = input(f"\nMove {len(plan)} file(s)? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("Aborted.")
            return

    moved = 0
    errors = 0
    for src, dst in plan:
        # Collision-safe: if the destination exists, append -2, -3, ...
        final_dst = dst
        counter = 2
        while (vault_root / final_dst).exists():
            stem = Path(dst).stem
            parent = Path(dst).parent.as_posix()
            name = f"{stem}-{counter}.md"
            final_dst = f"{parent}/{name}" if parent != "." else name
            counter += 1
        try:
            storage.move(src, final_dst)
            moved += 1
        except (FileNotFoundError, FileExistsError, ValueError, OSError) as exc:
            errors += 1
            print(f"  ! failed to move {src}: {exc}")

    # Re-index so the graph reflects new locations (mtime cache was keyed on
    # old paths). Ids are unchanged, so wikilinks reconcile.
    kernel.ingest(force=True)
    print(f"\nMoved {moved} file(s), {errors} error(s). Vault re-indexed.")
