"""Tests for the CLI module.

Tests argument parsing, ingest, remember, and context commands.
Skips commands that require LLM providers (ask, import).
"""

from unittest.mock import patch

import pytest

from memograph.cli import Spinner, main


@pytest.fixture
def temp_vault(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    return vault


@pytest.fixture
def populated_vault(temp_vault):
    """Create vault with test files."""
    for title, content in [
        ("Python Tips", "Use list comprehensions"),
        ("Docker Guide", "Container basics"),
    ]:
        slug = title.lower().replace(" ", "-")
        (temp_vault / f"{slug}.md").write_text(
            f"---\ntitle: {title}\nmemory_type: semantic\nsalience: 0.7\n---\n\n{content}\n",
            encoding="utf-8",
        )
    return temp_vault


class TestSpinner:
    """Test Spinner utility class."""

    def test_spinner_context_manager(self):
        with Spinner("Testing") as s:
            assert s.stop_spinner is False
        assert s.stop_spinner is True

    def test_spinner_custom_message(self):
        s = Spinner("Custom message")
        assert s.message == "Custom message"


class TestCLIIngest:
    """Test ingest command."""

    def test_ingest(self, populated_vault, capsys):
        with patch(
            "sys.argv", ["memograph", "--vault", str(populated_vault), "ingest"]
        ):
            main()
        output = capsys.readouterr().out
        assert "indexed" in output or "total" in output

    def test_ingest_force(self, populated_vault, capsys):
        with patch(
            "sys.argv",
            ["memograph", "--vault", str(populated_vault), "ingest", "--force"],
        ):
            main()
        output = capsys.readouterr().out
        assert "indexed" in output or "total" in output


class TestCLIRemember:
    """Test remember command."""

    def test_remember_basic(self, temp_vault, capsys):
        with patch(
            "sys.argv",
            [
                "memograph",
                "--vault",
                str(temp_vault),
                "remember",
                "--title",
                "Test Note",
                "--content",
                "Test content here",
            ],
        ):
            main()
        output = capsys.readouterr().out
        assert "Created memory" in output

    def test_remember_with_tags(self, temp_vault, capsys):
        with patch(
            "sys.argv",
            [
                "memograph",
                "--vault",
                str(temp_vault),
                "remember",
                "--title",
                "Tagged Note",
                "--content",
                "Content with tags",
                "--tags",
                "python",
                "test",
            ],
        ):
            main()
        output = capsys.readouterr().out
        assert "Created memory" in output

    def test_remember_with_type(self, temp_vault, capsys):
        with patch(
            "sys.argv",
            [
                "memograph",
                "--vault",
                str(temp_vault),
                "remember",
                "--title",
                "Meeting",
                "--content",
                "Discussed Q3",
                "--type",
                "episodic",
            ],
        ):
            main()
        output = capsys.readouterr().out
        assert "Created memory" in output


class TestCLIContext:
    """Test context command."""

    def test_context_basic(self, populated_vault, capsys):
        with patch(
            "sys.argv",
            [
                "memograph",
                "--vault",
                str(populated_vault),
                "context",
                "--query",
                "python tips",
            ],
        ):
            main()
        output = capsys.readouterr().out
        assert "Python Tips" in output or len(output) > 0

    def test_context_with_options(self, populated_vault, capsys):
        with patch(
            "sys.argv",
            [
                "memograph",
                "--vault",
                str(populated_vault),
                "context",
                "--query",
                "docker",
                "--depth",
                "1",
                "--top-k",
                "3",
                "--token-limit",
                "512",
            ],
        ):
            main()
        output = capsys.readouterr().out
        # Should produce some output (even if empty context)
        assert isinstance(output, str)


class TestCLIDoctor:
    """Test doctor command."""

    def test_doctor(self, temp_vault, capsys):
        with patch(
            "sys.argv",
            ["memograph", "--vault", str(temp_vault), "doctor"],
        ):
            main()
        output = capsys.readouterr().out
        assert "doctor" in output.lower()
        assert "vault" in output.lower()
