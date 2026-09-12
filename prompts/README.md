# prompts/

System / instruction prompts used by the studio, extracted from
Python source strings into version-controlled Markdown files.

The runtime loader lives at `backend/prompts.py`:

```python
from backend import prompts
system = prompts.load("system_default")
```

Results are `lru_cache`d — call `prompts.reload()` in tests if you
monkey-patch a file on disk.

## Editing

Prompts here are load-bearing. Changing one is a real behavioral edit
and should be reviewed like any other code change:

1. Ship the diff in its own PR.
2. Run the eval suite against a spec set that exercises the affected
   behavior (`.venv/bin/python evals/run.py --spec …`).
3. In the PR description note what improved and, if any specs
   regressed, why the tradeoff is acceptable.

## Files

| file                       | consumer                                                    |
| -------------------------- | ----------------------------------------------------------- |
| `system_default.md`        | Default settings row (`backend/database.py` bootstrap).     |
| `hardware_context.md`      | `agent_orchestrator` — prepended to every system prompt.    |
| `tool_hint.md`             | `agent_orchestrator` — appended after user system prompt.   |
| `critique.md`              | `agent_orchestrator` deep-think reviewer loop.              |
| `hyde.md`                  | `rag._hyde_expand` — hypothetical-document query rewriter.  |
| `rerank.md`                | `rag._llm_rerank` — relevance-judge instruction.            |
