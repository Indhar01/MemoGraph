from pathlib import Path


class VaultStorage:
    def __init__(self, vault_root: str | Path):
        self.root = Path(vault_root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)

    def markdown_files(self) -> list[Path]:
        return sorted(self.root.rglob("*.md"))

    def write(self, relative_path: str, content: str) -> Path:
        target = self.root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target
