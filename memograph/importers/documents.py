"""Document importer for converting TXT, PDF, and Word files to Markdown."""

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


class DocumentImporter:
    """Import and convert documents (TXT, PDF, DOCX) to Markdown for MemoGraph."""

    def __init__(self, vault_path: str):
        """
        Initialize the document importer.

        Args:
            vault_path: Path to the MemoGraph vault directory
        """
        self.vault_path = Path(vault_path).expanduser()
        self.vault_path.mkdir(parents=True, exist_ok=True)

    def import_file(
        self,
        file_path: str,
        memory_type: str = "episodic",
        salience: float = 0.7,
        tags: list[str] | None = None,
        overwrite: bool = False,
    ) -> tuple[bool, str]:
        """
        Import a single file and convert to markdown.

        Args:
            file_path: Path to the file to import
            memory_type: Type of memory (episodic, semantic, procedural, fact)
            salience: Importance score (0.0-1.0)
            tags: Optional list of tags to add
            overwrite: Whether to overwrite existing files

        Returns:
            Tuple of (success, message)
        """
        source_file = Path(file_path)

        if not source_file.exists():
            return False, f"File not found: {file_path}"

        extension = source_file.suffix.lower()

        if extension not in [".txt", ".pdf", ".docx", ".doc"]:
            return False, f"Unsupported file format: {extension}"

        # Generate output filename
        output_name = source_file.stem.lower().replace(" ", "-")
        output_file = self.vault_path / f"{output_name}.md"

        # Check if file already exists
        if output_file.exists() and not overwrite:
            return False, f"File already exists: {output_file.name} (use --overwrite to replace)"

        # Convert based on format
        try:
            if extension == ".txt":
                content = self._convert_txt(source_file)
            elif extension == ".pdf":
                content = self._convert_pdf(source_file)
            elif extension in [".docx", ".doc"]:
                content = self._convert_word(source_file)
            else:
                return False, f"Unsupported format: {extension}"

            if not content:
                return False, "Failed to extract content from file"

            # Generate frontmatter
            frontmatter = self._generate_frontmatter(source_file, memory_type, salience, tags)

            # Write markdown file
            markdown_content = f"{frontmatter}\n{content}\n"
            output_file.write_text(markdown_content, encoding="utf-8")

            return True, f"Imported: {source_file.name} → {output_file.name}"

        except Exception as e:
            return False, f"Error importing {source_file.name}: {str(e)}"

    def import_folder(
        self,
        folder_path: str,
        memory_type: str = "episodic",
        salience: float = 0.7,
        tags: list[str] | None = None,
        overwrite: bool = False,
        recursive: bool = False,
    ) -> dict:
        """
        Import all supported files from a folder.

        Args:
            folder_path: Path to the folder containing files
            memory_type: Type of memory
            salience: Importance score
            tags: Optional list of tags
            overwrite: Whether to overwrite existing files
            recursive: Whether to scan subdirectories

        Returns:
            Dictionary with statistics
        """
        source_folder = Path(folder_path)

        if not source_folder.exists() or not source_folder.is_dir():
            return {
                "success": 0,
                "failed": 0,
                "skipped": 0,
                "errors": [f"Folder not found: {folder_path}"],
            }

        # Find all supported files
        files = list(source_folder.rglob("*")) if recursive else list(source_folder.glob("*"))

        # Filter to supported formats
        supported_files = [
            f
            for f in files
            if f.is_file() and f.suffix.lower() in [".txt", ".pdf", ".docx", ".doc"]
        ]

        if not supported_files:
            return {
                "success": 0,
                "failed": 0,
                "skipped": 0,
                "errors": ["No supported files found (.txt, .pdf, .docx)"],
            }

        # Process each file
        results: dict[str, Any] = {"success": 0, "failed": 0, "skipped": 0, "errors": []}

        for file in supported_files:
            success, message = self.import_file(str(file), memory_type, salience, tags, overwrite)

            if success:
                results["success"] += 1
                print(f"✓ {message}")
            elif "already exists" in message:
                results["skipped"] += 1
                print(f"⊘ Skipped: {file.name} (already exists)")
            else:
                results["failed"] += 1
                results["errors"].append(message)
                print(f"✗ {message}")

        return results

    def _convert_txt(self, file_path: Path) -> str:
        """Convert TXT file to markdown content."""
        return file_path.read_text(encoding="utf-8").strip()

    def _convert_pdf(self, file_path: Path) -> str:
        """Convert PDF file to markdown content."""
        # Try pypdf first
        try:
            import pypdf

            reader = pypdf.PdfReader(str(file_path))
            text_parts = []

            for page in reader.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(text)

            content = "\n\n".join(text_parts)
            if content.strip():
                return content

        except ImportError:
            pass  # pypdf not available, try pandoc
        except Exception as e:
            print(f"Warning: pypdf failed, trying pandoc: {e}")

        # Fall back to pandoc
        return self._convert_with_pandoc(file_path)

    def _convert_word(self, file_path: Path) -> str:
        """Convert Word/DOCX file to markdown content."""
        # Try python-docx first
        try:
            import docx

            doc = docx.Document(str(file_path))
            paragraphs = [para.text for para in doc.paragraphs if para.text.strip()]
            content = "\n\n".join(paragraphs)

            if content.strip():
                return content

        except ImportError:
            pass  # python-docx not available, try pandoc
        except Exception as e:
            print(f"Warning: python-docx failed, trying pandoc: {e}")

        # Fall back to pandoc
        return self._convert_with_pandoc(file_path)

    def _convert_with_pandoc(self, file_path: Path) -> str:
        """Convert file using pandoc (universal fallback)."""
        try:
            result = subprocess.run(
                ["pandoc", str(file_path), "-t", "markdown", "--wrap=none"],
                capture_output=True,
                text=True,
                check=True,
                timeout=60,
            )
            return result.stdout.strip()

        except FileNotFoundError as e:
            raise RuntimeError(
                "Pandoc not found. Install it for PDF/Word support:\n"
                "  Windows: choco install pandoc\n"
                "  Mac: brew install pandoc\n"
                "  Linux: sudo apt install pandoc\n"
                "Or install Python libraries:\n"
                "  pip install pypdf python-docx"
            ) from e
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Pandoc conversion failed: {e.stderr}") from e
        except subprocess.TimeoutExpired as e:
            raise RuntimeError("Pandoc conversion timed out (>60s)") from e

    def _generate_frontmatter(
        self,
        source_file: Path,
        memory_type: str,
        salience: float,
        tags: list[str] | None,
    ) -> str:
        """Generate YAML frontmatter for the markdown file."""
        # Generate title from filename
        title = source_file.stem.replace("-", " ").replace("_", " ").title()

        # Get file creation time
        try:
            stat = source_file.stat()
            created = datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc)
        except Exception:
            created = datetime.now(timezone.utc)

        # Build frontmatter dict
        fm_data = {
            "title": title,
            "memory_type": memory_type,
            "salience": salience,
            "created": created.isoformat(),
            "meta": {
                "source_file": source_file.name,
                "source_format": source_file.suffix[1:],
                "imported_at": datetime.now(timezone.utc).isoformat(),
            },
        }

        # Add tags to content (will be added after frontmatter)
        frontmatter = "---\n" + yaml.safe_dump(fm_data, sort_keys=False) + "---\n"

        # Prepare tags line
        if tags:
            tags_line = " ".join(f"#{tag}" for tag in tags)
            return frontmatter + f"\n{tags_line}\n"

        return frontmatter
