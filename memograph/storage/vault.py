from pathlib import Path

# Characters that have no business in a vault filename. NUL terminates C
# strings, the rest are control codes that filesystem tools interpret
# inconsistently. Reject early rather than rely on the OS to reject them.
_FORBIDDEN_CHARS = frozenset(chr(c) for c in range(32)) | {chr(127)}

# Windows reserved names. Even on POSIX hosts we reject them so vaults
# remain portable.
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class VaultStorage:
    def __init__(self, vault_root: str | Path):
        self.root = Path(vault_root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def markdown_files(self) -> list[Path]:
        return sorted(self.root.rglob("*.md"))

    def write(self, relative_path: str, content: str) -> Path:
        target = self._safe_path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def _safe_path(self, relative_path: str) -> Path:
        if not isinstance(relative_path, str) or not relative_path:
            raise ValueError("relative_path must be a non-empty string")

        if any(c in _FORBIDDEN_CHARS for c in relative_path):
            raise ValueError("relative_path contains control characters")

        candidate = Path(relative_path)
        # Path.is_absolute() is platform-dependent: on Windows a leading "/"
        # without a drive letter is *not* absolute, so test that explicitly
        # too. We want to reject "/etc/passwd" the same way on every OS.
        if (
            candidate.is_absolute()
            or candidate.drive
            or relative_path.startswith(("/", "\\"))
        ):
            raise ValueError(f"relative_path must not be absolute: {relative_path!r}")

        for part in candidate.parts:
            if part in {"", ".", ".."}:
                # "." and "" are noise; ".." is the actual escape attempt.
                if part == "..":
                    raise ValueError(
                        f"relative_path must not traverse upward: {relative_path!r}"
                    )
            stem = part.split(".")[0].upper()
            if stem in _WINDOWS_RESERVED:
                raise ValueError(f"relative_path contains a reserved name: {part!r}")

        # resolve(strict=False) lets us handle paths that don't exist yet
        # (the common case for a write). After resolution, the result must
        # still be inside self.root — this catches symlink escapes that the
        # textual ".." check above wouldn't.
        target = (self.root / candidate).resolve(strict=False)
        if not target.is_relative_to(self.root):
            raise ValueError(f"relative_path escapes the vault root: {relative_path!r}")
        return target
