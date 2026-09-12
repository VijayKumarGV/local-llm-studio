"""Unit tests for the eval runner's pure helpers + reporting logic."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from pytest_httpx import HTTPXMock

from evals import run as evals_run

# ── load_spec ─────────────────────────────────────────────────────────


class TestLoadSpec:
    def test_parses_valid_jsonl(self, tmp_path: Path) -> None:
        p = tmp_path / "spec.jsonl"
        p.write_text(
            '{"id":"a","query":"q","workspace":"security","answer_must_contain":["x"]}\n'
            "\n"  # blank line skipped
            "# comment line\n"
            '{"id":"b","query":"q2","workspace":"coding","expected_sources":["file.md"]}\n',
            encoding="utf-8",
        )
        specs = evals_run.load_spec(p)
        assert [s.id for s in specs] == ["a", "b"]
        assert specs[0].answer_must_contain == ("x",)
        assert specs[1].expected_sources == ("file.md",)

    def test_missing_required_field_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.jsonl"
        p.write_text('{"id":"a","workspace":"security","answer_must_contain":["x"]}\n', encoding="utf-8")
        with pytest.raises(ValueError, match="missing required 'query'"):
            evals_run.load_spec(p)

    def test_spec_without_grading_signal_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.jsonl"
        p.write_text('{"id":"a","query":"q","workspace":"security"}\n', encoding="utf-8")
        with pytest.raises(ValueError, match="no grading signals"):
            evals_run.load_spec(p)

    def test_invalid_json_reports_line(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.jsonl"
        p.write_text("not json here\n", encoding="utf-8")
        with pytest.raises(ValueError, match=":1"):
            evals_run.load_spec(p)


# ── grading primitives ───────────────────────────────────────────────


class TestCheckRetrieval:
    def test_true_on_substring_match(self) -> None:
        assert evals_run.check_retrieval(
            ["OWASP_SQL_Injection_Prevention_Cheat_Sheet.md"],
            ("SQL_Injection_Prevention",),
        )

    def test_case_insensitive(self) -> None:
        assert evals_run.check_retrieval(["FOO.md"], ("foo",))

    def test_false_when_none_match(self) -> None:
        assert not evals_run.check_retrieval(["unrelated.md"], ("SQL",))

    def test_vacuously_true(self) -> None:
        assert evals_run.check_retrieval(["anything.md"], ())


class TestCheckMustContain:
    def test_all_required_present(self) -> None:
        assert evals_run.check_must_contain("Use Argon2 for password storage.", ("argon2",))

    def test_missing_any_fails(self) -> None:
        assert not evals_run.check_must_contain("Argon2 is great.", ("argon2", "bcrypt"))

    def test_vacuously_true(self) -> None:
        assert evals_run.check_must_contain("anything", ())


class TestCheckMustNotContain:
    def test_absent_passes(self) -> None:
        assert evals_run.check_must_not_contain("Never store plaintext.", ("md5 is fine",))

    def test_present_fails(self) -> None:
        assert not evals_run.check_must_not_contain("MD5 is fine for passwords", ("md5 is fine",))

    def test_vacuously_true(self) -> None:
        assert evals_run.check_must_not_contain("anything", ())


class TestCheckTechniqueIds:
    def test_all_present(self) -> None:
        assert evals_run.check_technique_ids("Detects T1055 and T1078.", ("T1055", "T1078"))

    def test_missing_fails(self) -> None:
        assert not evals_run.check_technique_ids("Only T1055 here.", ("T1055", "T1078"))


# ── SSE parsing ──────────────────────────────────────────────────────


class TestParseSseAnswer:
    def test_prefers_done_content(self) -> None:
        sse = (
            'event: token\ndata: {"delta": "Hello "}\n\n'
            'event: token\ndata: {"delta": "world"}\n\n'
            'event: done\ndata: {"content": "Hello world.", "message_id": 42}\n\n'
        )
        assert evals_run.parse_sse_answer(sse) == "Hello world."

    def test_falls_back_to_token_deltas_when_no_done(self) -> None:
        sse = (
            'event: token\ndata: {"delta": "a"}\n\n'
            'event: token\ndata: {"delta": "b"}\n\n'
            'event: token\ndata: {"delta": "c"}\n\n'
        )
        assert evals_run.parse_sse_answer(sse) == "abc"

    def test_ignores_non_content_events(self) -> None:
        sse = (
            'event: plan_step\ndata: {"step": 1}\n\n'
            'event: token\ndata: {"delta": "hi"}\n\n'
            'event: done\ndata: {"content": "hi"}\n\n'
        )
        assert evals_run.parse_sse_answer(sse) == "hi"

    def test_empty_stream(self) -> None:
        assert evals_run.parse_sse_answer("") == ""

    def test_malformed_data_skipped(self) -> None:
        sse = 'event: token\ndata: not json\n\nevent: token\ndata: {"delta": "ok"}\n\n'
        assert evals_run.parse_sse_answer(sse) == "ok"


# ── reporting + baseline ─────────────────────────────────────────────


class TestReporting:
    def test_build_report_counts(self, tmp_path: Path) -> None:
        spec_path = tmp_path / "s.jsonl"
        results = [{"id": "a", "pass": True}, {"id": "b", "pass": False}]
        r = evals_run.build_report(spec_path, results, "http://s", "m")
        assert r["counts"] == {"total": 2, "pass": 1, "fail": 1}
        assert r["pass_rate"] == 0.5

    def test_write_report_creates_latest_pointer(self, tmp_path: Path) -> None:
        report = {"generated_at": "x", "results": [], "counts": {"total": 0}, "pass_rate": 0.0}
        out = evals_run.write_report(report, tmp_path)
        assert out.exists()
        latest = tmp_path / "latest.json"
        assert latest.exists()
        assert json.loads(latest.read_text()) == report

    def test_load_baseline_returns_newest_for_spec(self, tmp_path: Path) -> None:
        spec_path = Path("evals/security_expert.jsonl")
        older = {
            "generated_at": "2026-09-10T10:00:00Z",
            "spec_file": str(spec_path),
            "pass_rate": 0.8,
            "results": [],
        }
        newer = {
            "generated_at": "2026-09-11T10:00:00Z",
            "spec_file": str(spec_path),
            "pass_rate": 0.9,
            "results": [],
        }
        other = {
            "generated_at": "2026-09-11T11:00:00Z",
            "spec_file": "evals/other.jsonl",
            "pass_rate": 0.5,
            "results": [],
        }
        (tmp_path / "old.json").write_text(json.dumps(older))
        (tmp_path / "new.json").write_text(json.dumps(newer))
        (tmp_path / "other.json").write_text(json.dumps(other))
        got = evals_run.load_baseline(spec_path, tmp_path)
        assert got is not None
        assert got["generated_at"] == "2026-09-11T10:00:00Z"

    def test_load_baseline_none_when_empty(self, tmp_path: Path) -> None:
        assert evals_run.load_baseline(Path("evals/foo.jsonl"), tmp_path) is None

    def test_diff_finds_pass_to_fail(self) -> None:
        baseline = {"pass_rate": 0.9, "results": [{"id": "a", "pass": True}, {"id": "b", "pass": True}]}
        current = {"pass_rate": 0.5, "results": [{"id": "a", "pass": True}, {"id": "b", "pass": False}]}
        d = evals_run.diff_against_baseline(current, baseline)
        assert d["regressions"] == [{"id": "b", "was": True, "now": False}]
        assert d["pass_rate_delta"] == -0.4


# ── async client integration (mocked server) ─────────────────────────


class TestEvaluateSpec:
    SERVER = "http://studio.local"

    @pytest.mark.asyncio
    async def test_full_pass_path(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=f"{self.SERVER}/api/rag/query?q=How+to+prevent+SQLi%3F&project_id=proj-1&top_k=6",
            json={"hits": [{"filename": "SQL_Injection_Prevention_Cheat_Sheet.md"}]},
        )
        httpx_mock.add_response(
            url=f"{self.SERVER}/api/conversations",
            method="POST",
            json={"conversation": {"id": "conv-1"}},
        )
        httpx_mock.add_response(
            url=f"{self.SERVER}/api/chat/stream",
            method="POST",
            text='event: done\ndata: {"content": "Use parameterized queries with ? placeholders."}\n\n',
        )
        spec = evals_run.Spec(
            id="sec-001",
            workspace="security",
            query="How to prevent SQLi?",
            expected_sources=("SQL_Injection_Prevention",),
            answer_must_contain=("parameterized", "?"),
            answer_must_not_contain=("string concatenation is safe",),
        )
        async with httpx.AsyncClient(base_url=self.SERVER) as client:
            got = await evals_run.evaluate_spec(client, spec, "proj-1", "qwen2.5:32b")
        assert got["pass"] is True
        assert got["retrieval_hit"] is True
        assert got["must_contain_hit"] is True
        assert got["must_not_contain_avoided"] is True

    @pytest.mark.asyncio
    async def test_must_not_contain_violation_fails_spec(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=f"{self.SERVER}/api/rag/query?q=q&project_id=proj-1&top_k=6",
            json={"hits": [{"filename": "any.md"}]},
        )
        httpx_mock.add_response(
            url=f"{self.SERVER}/api/conversations",
            method="POST",
            json={"conversation": {"id": "conv-1"}},
        )
        httpx_mock.add_response(
            url=f"{self.SERVER}/api/chat/stream",
            method="POST",
            text='event: done\ndata: {"content": "md5 is fine for passwords."}\n\n',
        )
        spec = evals_run.Spec(
            id="sec-005",
            workspace="security",
            query="q",
            answer_must_not_contain=("md5 is fine",),
        )
        async with httpx.AsyncClient(base_url=self.SERVER) as client:
            got = await evals_run.evaluate_spec(client, spec, "proj-1", "m")
        assert got["pass"] is False
        assert got["must_not_contain_avoided"] is False

    @pytest.mark.asyncio
    async def test_captures_answer_error_without_raising(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=f"{self.SERVER}/api/rag/query?q=q&project_id=p&top_k=6",
            json={"hits": []},
        )
        httpx_mock.add_response(
            url=f"{self.SERVER}/api/conversations",
            method="POST",
            status_code=500,
            text="boom",
        )
        spec = evals_run.Spec(id="x", workspace="security", query="q", answer_must_contain=("y",))
        async with httpx.AsyncClient(base_url=self.SERVER) as client:
            got = await evals_run.evaluate_spec(client, spec, "p", "m")
        assert "answer_error" in got
        assert got["pass"] is False
