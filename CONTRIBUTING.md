# Contributing

Thanks for considering a contribution. This document is a checklist —
short and specific — for anyone opening a PR.

## Ground rules

- Be nice. See [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).
- Security issues → don't open a public issue. See
  [`SECURITY.md`](SECURITY.md).
- Anything you contribute is licensed under Apache-2.0
  (see [`LICENSE`](LICENSE)).

## Set up

```sh
git clone https://github.com/avishwakarma/local-llm-studio.git
cd local-llm-studio
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Optional: docs build (`.venv/bin/pip install mkdocs mkdocs-material`),
desktop bundle (`pip install -r desktop/requirements.txt`), Playwright
e2e (`.venv/bin/pip install pytest-playwright && .venv/bin/playwright install chromium`).

## Local dev loop

```sh
make dev           # uvicorn on 127.0.0.1:8080 with reload
make test          # unit tests (fast, no docker/ollama needed)
make lint          # ruff check
make format        # ruff format
make typecheck     # mypy strict-ish
```

Before opening a PR, all four gates below must be green:

```sh
make lint
make format        # or: ruff format --check
make typecheck
make test          # or: pytest --cov=backend
```

CI runs the same commands on every push (`.github/workflows/ci.yml`).

## Commits

- Small, focused commits — each should stand alone in `git blame`.
- Imperative subject line, wrap at 72 chars.
- Body explains **why**, not what — the diff already shows what.
- Reference issues / PRs in the body when it helps (`fixes #123`).

We use the "keep-a-changelog" style categories informally in commit
messages: `feat(area): …`, `fix(area): …`, `docs: …`, `test: …`,
`chore: …`, `refactor: …`. Not enforced — clarity beats convention.

## Pull requests

- Rebase (don't merge) onto `main` before opening.
- Include a short "what & why" in the description.
- If you touched an endpoint, update the API page in `docs/api.md`.
- If you touched behavior in a way that could change eval outcomes,
  run the eval harness locally and note the result in the PR
  description.

## Code style highlights

- **Types.** `mypy` is on for `backend/` and `desktop/`. Prefer
  concrete return types (`dict[str, Any]` is fine at boundaries, but
  a `TypedDict` in `backend/types.py` is better internally).
- **Comments.** Only when the *why* is non-obvious. Don't paraphrase
  the code. Don't reference PRs / issue numbers in comments — they
  rot. Put that in the commit body.
- **Error handling.** Fail fast at the module boundary; degrade
  gracefully at UI-facing endpoints. Never swallow silently in a
  path that a user is waiting on.
- **Tests.** New behavior needs a test. Prefer unit tests over
  integration tests over e2e — they run 10× faster and pinpoint
  faster too.
- **Frontend.** No new build step. Modules live under `static/js/`
  and load via native ES modules. If you must add a dependency, use
  `<script type="module" src="https://esm.sh/pkg@ver">`.

## Docs

Docs source is under `docs/`. Build locally with
`.venv/bin/mkdocs serve`. Every PR that changes user-visible behavior
should update the relevant page under `docs/`. CI enforces `mkdocs
build --strict` so broken internal links fail the build.

## Reporting bugs

Open an issue with:

1. Version (`git rev-parse --short HEAD` and the tag if any).
2. Environment (macOS version, Python version, Docker vs bare metal).
3. Repro steps.
4. Expected vs. actual.
5. Relevant log output (redact tokens!).

## Reporting a security issue

See [`SECURITY.md`](SECURITY.md). Do not open a public issue.
