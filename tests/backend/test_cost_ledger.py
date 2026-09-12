"""cost_ledger unit tests + a smoke test for /api/cost/summary."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend import cost_ledger


class TestRecord:
    def test_row_created(self, fresh_schema: str) -> None:
        cost_ledger.record("conv-1", "proj-1", "qwen2.5:32b", 100, 200)
        rows = cost_ledger.summary(group_by="model")
        assert rows == [
            {
                "bucket": "qwen2.5:32b",
                "completions": 1,
                "prompt_tokens": 100,
                "completion_tokens": 200,
                "total_tokens": 300,
            }
        ]

    def test_all_zero_is_no_op(self, fresh_schema: str) -> None:
        cost_ledger.record("c", "p", "m", 0, 0)
        assert cost_ledger.summary() == []

    def test_negative_tokens_rejected_silently(self, fresh_schema: str) -> None:
        cost_ledger.record("c", "p", "m", -5, 200)
        assert cost_ledger.summary() == []

    def test_null_project_id_ok(self, fresh_schema: str) -> None:
        cost_ledger.record("c", None, "m", 10, 20)
        rows = cost_ledger.summary(group_by="project")
        assert rows[0]["bucket"] == "(none)"
        assert rows[0]["total_tokens"] == 30


class TestSummary:
    def test_group_by_model_orders_by_spend(self, fresh_schema: str) -> None:
        cost_ledger.record("c1", "p", "small", 10, 20)
        cost_ledger.record("c2", "p", "large", 100, 500)
        rows = cost_ledger.summary(group_by="model")
        assert [r["bucket"] for r in rows] == ["large", "small"]

    def test_group_by_day_returns_iso_dates(self, fresh_schema: str) -> None:
        cost_ledger.record("c", "p", "m", 5, 5)
        rows = cost_ledger.summary(group_by="day")
        assert rows and len(rows[0]["bucket"]) == 10  # YYYY-MM-DD

    def test_invalid_group_by_raises(self, fresh_schema: str) -> None:
        with pytest.raises(ValueError):
            cost_ledger.summary(group_by="user")


class TestSummaryEndpoint:
    def test_endpoint_returns_rows(self, fresh_schema: str, monkeypatch: pytest.MonkeyPatch) -> None:
        cost_ledger.record("c", "p", "m", 10, 20)
        # Bypass auth by disabling the middleware token check for the client.
        monkeypatch.setenv("SESSION_TOKEN", "test-token")
        from backend import auth, server

        auth._TOKEN = None
        client = TestClient(server.app)
        r = client.get("/api/cost/summary?group_by=model", headers={"Authorization": "Bearer test-token"})
        assert r.status_code == 200
        assert r.json()["rows"][0]["bucket"] == "m"

    def test_invalid_group_by_returns_400(self, fresh_schema: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SESSION_TOKEN", "test-token")
        from backend import auth, server

        auth._TOKEN = None
        client = TestClient(server.app)
        r = client.get("/api/cost/summary?group_by=nope", headers={"Authorization": "Bearer test-token"})
        assert r.status_code == 400
