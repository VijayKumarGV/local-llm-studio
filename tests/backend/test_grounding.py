"""Hallucination/grounding check — verify sentences against retrieved chunks."""

from __future__ import annotations

import numpy as np
import pytest

from backend import grounding


class TestSplitSentences:
    def test_empty(self) -> None:
        assert grounding.split_sentences("") == []

    def test_whitespace_only(self) -> None:
        assert grounding.split_sentences("   \n\n  ") == []

    def test_single_short_sentence_dropped(self) -> None:
        # Below MIN_SENTENCE_CHARS (20)
        assert grounding.split_sentences("Short.") == []

    def test_splits_on_period_boundary(self) -> None:
        text = (
            "First long sentence with quite a few words. "
            "Second one is also long enough to keep. "
            "Third stays too since it has body."
        )
        out = grounding.split_sentences(text)
        assert len(out) == 3

    def test_normalizes_whitespace(self) -> None:
        text = "First   sentence   with   extra   spacing.   Second   one   too."
        out = grounding.split_sentences(text)
        assert all("  " not in s for s in out)


class TestCheck:
    @pytest.mark.asyncio
    async def test_skipped_when_no_chunks(self) -> None:
        r = await grounding.check("This is a response with some sentences in it here.", [])
        assert r["status"] == "skipped"
        assert "no RAG chunks" in r["reason"]

    @pytest.mark.asyncio
    async def test_skipped_when_no_substantive_sentences(self) -> None:
        r = await grounding.check("Hi.", ["some retrieved chunk text"])
        assert r["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_supported_sentences_pass(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Fake embed: each text embeds to a deterministic 4-dim vector based
        # on whether it mentions "quantum" — so query & chunk about quantum
        # will be near-identical, other sentence stays far away.
        async def _fake_embed(texts, model, batch_size=32):
            out = []
            for t in texts:
                v = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32) if "quantum" in t.lower() \
                    else np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)
                out.append(v)
            return out
        monkeypatch.setattr("backend.grounding._embed_batch", _fake_embed)

        response = (
            "Quantum computing exploits quantum superposition to process information. "
            "This is a totally off-topic sentence about cooking pasta al dente."
        )
        chunks = [
            "In quantum computing, qubits use superposition and entanglement to compute.",
            "Another chunk about quantum error correction methods and codes.",
        ]
        r = await grounding.check(response, chunks, threshold=0.5)
        assert r["status"] == "success"
        assert r["total"] == 2
        # The quantum sentence is supported, the pasta one is not
        by_sent = {s["sentence"][:20]: s for s in r["sentences"]}
        supported = [s for s in r["sentences"] if s["supported"]]
        assert len(supported) == 1
        assert "quantum" in supported[0]["sentence"].lower()
        # Coverage is 0.5 (1 of 2)
        assert r["supported"] == 1
        assert r["coverage"] == 0.5

    @pytest.mark.asyncio
    async def test_all_supported_gives_full_coverage(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Every embed returns the same vector → cosine = 1 → every sentence supported.
        async def _fake_embed(texts, model, batch_size=32):
            return [np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32) for _ in texts]
        monkeypatch.setattr("backend.grounding._embed_batch", _fake_embed)

        response = (
            "The first sentence is grounded in the docs. "
            "The second one also matches something in the source material."
        )
        r = await grounding.check(response, ["chunk text here that has enough content"], threshold=0.5)
        assert r["status"] == "success"
        assert r["coverage"] == 1.0

    @pytest.mark.asyncio
    async def test_embed_failure_returns_error(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def _boom(texts, model, batch_size=32):
            raise RuntimeError("ollama unreachable")
        monkeypatch.setattr("backend.grounding._embed_batch", _boom)

        r = await grounding.check(
            "Some sentence long enough to pass the min length check.",
            ["a chunk"],
        )
        assert r["status"] == "error"
        assert "ollama unreachable" in r["error"]

    @pytest.mark.asyncio
    async def test_threshold_controls_supported_count(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Fixed similarity = 0.6
        async def _fake_embed(texts, model, batch_size=32):
            vecs = []
            for i, _ in enumerate(texts):
                v = np.array([1.0, 0.6, 0.0, 0.0], dtype=np.float32) if i % 2 == 0 \
                    else np.array([0.6, 1.0, 0.0, 0.0], dtype=np.float32)
                vecs.append(v)
            return vecs
        monkeypatch.setattr("backend.grounding._embed_batch", _fake_embed)

        response = "The first sentence right here in the text is nicely long enough."
        chunks = ["chunk one with content long enough"]
        low = await grounding.check(response, chunks, threshold=0.3)
        high = await grounding.check(response, chunks, threshold=0.99)
        assert low["supported"] >= high["supported"]
