# Privacy

**One-line summary:** Local LLM Studio is local-first. Nothing about
your conversations leaves the machine unless you explicitly enable a
tool that talks to the outside world.

This document is authoritative — if the code disagrees, the code is a
bug. Report at [SECURITY.md](SECURITY.md).

## What is stored, where

| Data                                  | Location                                                     |
| ------------------------------------- | ------------------------------------------------------------ |
| Conversations, messages, attachments  | SQLite at `backend/workspace.db` (or `/data/workspace.db` in Docker) |
| Uploaded files (raw bytes)            | `backend/uploads/` (or `/data/uploads/`)                     |
| Generated artifacts (raw bytes)       | `backend/artifacts/` (or `/data/artifacts/`)                 |
| RAG embeddings                        | Same SQLite DB — `file_chunks.embedding` as float32 BLOBs    |
| Session token                         | `backend/token` (or `/data/token`) — chmod 0600 on POSIX     |
| Sensitive settings (e.g., API keys)   | macOS Keychain via `keyring` — see `backend/secure_settings.py` for the allowlist |
| Audit log                             | Same SQLite DB — append-only, read via `GET /api/audit`      |
| Cost / token ledger                   | Same SQLite DB — one row per completion                      |

Everything is on your disk. Backups (via `make backup`) are also local.

## What leaves the machine, when

**By default (no tools enabled): nothing.** Chats stream from Ollama on
localhost. RAG queries embed against the local `nomic-embed-text`
model. Metrics stay in the local Prometheus.

**Only when you explicitly enable a tool per-conversation:**

| Tool                        | Talks to                                          | Data sent                                |
| --------------------------- | ------------------------------------------------- | ---------------------------------------- |
| `search_web`                | duckduckgo.com                                    | The user's query text.                    |
| `fetch_url`                 | The URL you pasted                                | Standard HTTP GET (no cookies unless the site sets them via a redirect). |
| `execute_python_code`       | Nothing external (network is denied in-sandbox). | —                                        |
| `read_file` / `list_files`  | Nothing external.                                 | —                                        |
| `create_artifact`           | Nothing external.                                 | —                                        |

Web search and URL fetch are the only paths where a request carrying
your input leaves the machine, and both are per-turn opt-in via
tool-permission settings (see `backend/security.py` —
`DEFAULT_TOOL_PERMISSIONS`).

## What we do NOT do

- **No telemetry.** No app-level metrics reporting to any remote
  endpoint. The Prometheus stack (`docker/observability-compose.yml`)
  runs entirely on your machine and binds only to `127.0.0.1`.
- **No error reporting.** No Sentry, no crash dump uploader.
- **No update pings** except one best-effort GitHub Releases check
  from the macOS tray app on launch — a single HTTPS `GET` to
  `api.github.com/repos/OWNER/REPO/releases/latest`. Never
  auto-downloads.
- **No account system.** Auth is a single session token generated on
  first run. No third-party identity, no OAuth.
- **No cloud LLMs.** All chat/embed/rerank inference goes through the
  local Ollama daemon.

## Cookies / local storage

- `studio_token` — session bearer cookie, `HttpOnly`, `SameSite=strict`.
  Set by `GET /auth?token=<token>` on first browser session, 1-year TTL.
- `studio.wizard.dismissed` — localStorage flag remembering that you
  dismissed the setup wizard.
- `theme` — localStorage flag for the dark/light preference (if you
  toggle it).

No third-party cookies. No analytics.

## Corpus content

`scripts/curate_corpus.py` clones public git repos (OWASP, MITRE,
CPython, Rust book, TS handbook, Go docs) into `corpus/`. Every clone
uses `git clone --depth 1 --filter=blob:none --sparse` — the initial
fetch is the only outbound network use of the corpus system. No
telemetry back to the source repos.

## Deleting everything

```sh
docker compose down -v          # Docker path: wipes the named volumes
rm -rf backend/workspace.db* backend/uploads backend/artifacts backend/token corpus/  # bare metal
```

## Contact

Questions about this policy or a specific data path: see
[SECURITY.md](SECURITY.md) for the reporting channel.
