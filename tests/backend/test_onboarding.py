"""Onboarding detection tests. Ollama is mocked; corpus + token file
are exercised against a temp `CONFIG.corpus_dir` / `session_token_file`."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend import config as config_module
from backend import database, onboarding


class TestRecommendedMissing:
    def test_all_installed_returns_empty(self) -> None:
        installed = list(onboarding.RECOMMENDED_MODELS)
        assert onboarding._recommended_missing(installed) == []

    def test_match_ignores_tag_when_base_present(self) -> None:
        # User has qwen2.5:7b installed → still counts as "qwen2.5:32b" absent
        # for the specific-tag entry, but base-name match should exempt it.
        installed = ["qwen2.5:7b"]
        missing = onboarding._recommended_missing(installed)
        # qwen2.5:32b uses base "qwen2.5" which matches installed "qwen2.5:7b"
        assert "qwen2.5:32b" not in missing

    def test_all_missing_returns_full_list(self) -> None:
        assert set(onboarding._recommended_missing([])) == set(onboarding.RECOMMENDED_MODELS)


@pytest.fixture
def config_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect CONFIG.corpus_dir + session_token_file at tmp_path via env
    overrides + config.reload(). Restores on teardown."""
    corpus = tmp_path / "corpus"
    token = tmp_path / "token"
    monkeypatch.setenv("STUDIO_CORPUS_DIR", str(corpus))
    monkeypatch.setenv("STUDIO_TOKEN_FILE", str(token))
    original = config_module.CONFIG
    config_module.reload()
    # Rebind onboarding's imported CONFIG reference to the reloaded object.
    monkeypatch.setattr(onboarding, "CONFIG", config_module.CONFIG)
    yield {"corpus": corpus, "token": token}
    config_module.CONFIG = original
    monkeypatch.setattr(onboarding, "CONFIG", original)


class TestCorpusDetection:
    def test_missing_dir_returns_false(self, config_paths) -> None:
        assert onboarding._corpus_downloaded() is False

    def test_empty_dir_returns_false(self, config_paths) -> None:
        config_paths["corpus"].mkdir()
        assert onboarding._corpus_downloaded() is False

    def test_populated_dir_returns_true(self, config_paths) -> None:
        d = config_paths["corpus"]
        (d / "sec").mkdir(parents=True)
        (d / "sec" / "cheat.md").write_text("hi", encoding="utf-8")
        assert onboarding._corpus_downloaded() is True


class TestAuthBootstrapped:
    def test_missing_token_file(self, config_paths) -> None:
        assert onboarding._auth_bootstrapped() is False

    def test_present_token_file(self, config_paths) -> None:
        config_paths["token"].write_text("abc123", encoding="utf-8")
        assert onboarding._auth_bootstrapped() is True


class TestWorkspacesCreated:
    def test_counts_projects(self, fresh_schema: str) -> None:
        assert onboarding._workspaces_created() == 0
        database.create_project(name="Security Expert")
        assert onboarding._workspaces_created() == 1


class TestStatusEndpoint:
    @pytest.mark.asyncio
    async def test_needs_setup_when_everything_missing(
        self,
        fresh_schema: str,
        config_paths,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = AsyncMock()
        fake.get.side_effect = OSError("unreachable")
        monkeypatch.setattr("backend.onboarding.get_ollama_client", lambda: fake)

        s = await onboarding.status()
        assert s["ollama_up"] is False
        assert s["models_installed"] == []
        assert set(s["recommended_missing"]) == set(onboarding.RECOMMENDED_MODELS)
        assert s["workspaces_created"] == 0
        assert s["corpus_downloaded"] is False
        assert s["auth_bootstrapped"] is False
        assert s["needs_setup"] is True

    @pytest.mark.asyncio
    async def test_fully_set_up_returns_needs_setup_false(
        self,
        fresh_schema: str,
        config_paths,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        resp = MagicMock()
        resp.json = MagicMock(return_value={"models": [{"name": r} for r in onboarding.RECOMMENDED_MODELS]})
        resp.raise_for_status = MagicMock(return_value=None)
        fake = AsyncMock()
        fake.get = AsyncMock(return_value=resp)
        monkeypatch.setattr("backend.onboarding.get_ollama_client", lambda: fake)

        corpus = config_paths["corpus"]
        corpus.mkdir()
        (corpus / "x.md").write_text("hi", encoding="utf-8")
        config_paths["token"].write_text("abc", encoding="utf-8")
        database.create_project(name="Security Expert")

        s = await onboarding.status()
        assert s["ollama_up"] is True
        assert s["needs_setup"] is False
        assert s["recommended_missing"] == []
