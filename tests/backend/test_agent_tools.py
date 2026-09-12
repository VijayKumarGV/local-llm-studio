"""agent_tools unit tests — cover the pure logic paths so the tool
dispatch surface stays honest even when DuckDuckGo / ollama are down."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend import agent_tools


class TestSearchWeb:
    def test_returns_placeholder_when_no_results(self) -> None:
        # Empty iterator = no results.
        fake_ddgs = MagicMock()
        fake_ddgs.__enter__ = MagicMock(return_value=fake_ddgs)
        fake_ddgs.__exit__ = MagicMock(return_value=False)
        fake_ddgs.text.return_value = iter([])
        with patch("ddgs.DDGS", return_value=fake_ddgs):
            got = agent_tools.search_web("nothing anywhere")
        assert got["status"] == "success"
        assert got["results"][0]["snippet"].startswith("No results")

    def test_flattens_result_shape(self) -> None:
        fake = [{"title": "t1", "body": "b1", "href": "https://x/1"}]
        fake_ddgs = MagicMock()
        fake_ddgs.__enter__ = MagicMock(return_value=fake_ddgs)
        fake_ddgs.__exit__ = MagicMock(return_value=False)
        fake_ddgs.text.return_value = iter(fake)
        with patch("ddgs.DDGS", return_value=fake_ddgs):
            got = agent_tools.search_web("q")
        assert got["count"] == 1
        assert got["results"][0]["url"] == "https://x/1"
        assert got["results"][0]["snippet"] == "b1"

    def test_swallows_ddg_exception(self) -> None:
        fake_ddgs = MagicMock()
        fake_ddgs.__enter__ = MagicMock(return_value=fake_ddgs)
        fake_ddgs.__exit__ = MagicMock(return_value=False)
        fake_ddgs.text.side_effect = RuntimeError("network died")
        with patch("ddgs.DDGS", return_value=fake_ddgs):
            got = agent_tools.search_web("q")
        # search_web reports the error as status="error" — the orchestrator
        # decides how to surface it to the user.
        assert got["status"] == "error"
        assert "network died" in got["error"]


class TestListFiles:
    def test_rejects_traversal(self) -> None:
        got = agent_tools.list_files("../../../etc")
        assert got["status"] == "error"
        assert "outside workspace" in got["error"].lower()

    def test_lists_workspace_entries(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Point the tool at a sandbox tree.
        (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.txt").write_text("ho", encoding="utf-8")
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "junk.pyc").write_bytes(b"x")
        monkeypatch.setattr(agent_tools, "WORKSPACE_DIR", str(tmp_path))
        got = agent_tools.list_files("")
        assert got["status"] == "success"
        # __pycache__ excluded
        assert not any("__pycache__" in f for f in got["files"])
        # relative paths
        assert "a.txt" in got["files"]
        assert os.path.join("sub", "b.txt") in got["files"]


class TestReadFile:
    def test_rejects_traversal(self) -> None:
        got = agent_tools.read_file("../../etc/passwd")
        assert got["status"] == "error"
        assert "outside workspace" in got["error"].lower()

    def test_missing_file(self) -> None:
        got = agent_tools.read_file("this-does-not-exist.md")
        assert got["status"] == "error"
        assert "not found" in got["error"].lower()

    def test_reads_first_n_lines(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        p = tmp_path / "sample.md"
        p.write_text("\n".join(f"line {i}" for i in range(1, 21)), encoding="utf-8")
        monkeypatch.setattr(agent_tools, "WORKSPACE_DIR", str(tmp_path))
        got = agent_tools.read_file("sample.md", max_lines=5)
        assert got["status"] == "success"
        assert got["content"].count("\n") <= 5


class TestFetchUrl:
    def test_rejects_missing_scheme(self) -> None:
        got = agent_tools.fetch_url("example.com")
        assert got["status"] == "error"
        assert "http" in got["error"].lower()

    def test_swallows_extractor_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "backend.extractors.fetch_url_as_text",
            lambda url: (_ for _ in ()).throw(RuntimeError("gateway timeout")),
        )
        got = agent_tools.fetch_url("https://example.com")
        assert got["status"] == "error"
        assert "gateway timeout" in got["error"]

    def test_success_truncates_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
        long = "x" * 20_000
        monkeypatch.setattr("backend.extractors.fetch_url_as_text", lambda url: (long, "Title"))
        got = agent_tools.fetch_url("https://example.com")
        assert got["status"] == "success"
        assert got["title"] == "Title"
        assert len(got["text"]) == 8000
        assert got["chars"] == 20_000


class TestCreateArtifact:
    def test_delegates_to_artifacts_and_shapes_result(self, fresh_schema: str, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_saved = {
            "id": "art-1",
            "name": "fib.py",
            "type": "code",
            "language": "python",
            "size_bytes": 42,
        }
        monkeypatch.setattr("backend.artifacts.save_artifact", lambda **kw: fake_saved)
        got = agent_tools.create_artifact(
            name="fib.py", content="def fib(n): ...", artifact_type="code", language="python"
        )
        assert got["status"] == "success"
        assert got["artifact_id"] == "art-1"
        assert got["size_bytes"] == 42
        assert "successfully created" in got["message"].lower()


class TestNotesRoundtrip:
    def test_save_then_read(self, fresh_schema: str) -> None:
        from backend import database

        conv = database.create_conversation(title="t", project_id=None)
        conv_id = conv["id"]
        r = agent_tools.save_note(conv_id, "plan: refactor auth", note_key="plan")
        assert r["status"] == "success"
        out = agent_tools.read_notes(conv_id, note_key="plan")
        assert out["status"] == "success"
        assert out["count"] >= 1
        assert any("refactor auth" in n["text"] for n in out["notes"])
