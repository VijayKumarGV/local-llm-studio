# NOTICE

Local LLM Studio
Copyright 2026 Local LLM Studio contributors

Licensed under the Apache License, Version 2.0 (see [`LICENSE`](LICENSE)).

## Third-party content

### Corpus (downloaded on-demand by `scripts/curate_corpus.py`)

The reference corpus is fetched at first run — it isn't bundled in the
source tree. Each source keeps its upstream license; if you distribute
a workspace DB that embeds these documents' vector chunks, honor the
originating license.

| Source                        | Upstream                                                      | License               |
| ----------------------------- | ------------------------------------------------------------- | --------------------- |
| OWASP Cheat Sheet Series      | github.com/OWASP/CheatSheetSeries                             | CC-BY-SA 4.0          |
| OWASP Top 10 (2021)           | github.com/OWASP/Top10                                        | CC-BY-SA 4.0          |
| OWASP ASVS                    | github.com/OWASP/ASVS                                         | CC-BY-SA 4.0          |
| MITRE CTI (ATT&CK)            | github.com/mitre-attack/attack-stix-data                      | U.S. Gov. work (public) |
| PayloadsAllTheThings          | github.com/swisskyrepo/PayloadsAllTheThings                   | MIT                   |
| The Rust Programming Language | github.com/rust-lang/book                                     | Apache-2.0 / MIT      |
| CPython docs (tutorial+howto) | github.com/python/cpython                                     | PSF                   |
| Go Blog + Effective Go        | github.com/golang/website                                     | CC-BY-3.0             |
| TypeScript Handbook           | github.com/microsoft/TypeScript-Website                       | MIT                   |

**CC-BY-SA is copyleft:** distributing a workspace DB that embeds OWASP
content may make the DB a derivative work; keep the derived DB under a
compatible license, or bundle only the retrieval index (chunk vectors)
without redistributing the OWASP text verbatim.

### Python runtime dependencies

Full list in `requirements.txt` — pinned exact versions in
`requirements-lock.txt`. Notable licenses:

| Package                                  | License              |
| ---------------------------------------- | -------------------- |
| fastapi, starlette, uvicorn              | MIT                  |
| pydantic                                 | MIT                  |
| httpx, anyio                             | BSD-3-Clause         |
| tiktoken                                 | MIT                  |
| ddgs                                     | MIT                  |
| numpy                                    | BSD-3-Clause         |
| yoyo-migrations                          | Apache-2.0           |
| pypdf                                    | BSD-3-Clause         |
| trafilatura                              | Apache-2.0           |
| slowapi                                  | MIT                  |
| keyring                                  | MIT                  |
| prometheus-client, prometheus-fastapi-instrumentator | Apache-2.0 |
| opentelemetry-* (api / sdk / instrumentation-fastapi / exporter-otlp-proto-http) | Apache-2.0 |

### Frontend dependencies (loaded from esm.sh CDN at runtime)

Not bundled in this repo. The `<script type="module" src="https://esm.sh/…">`
tags in `static/index.html` and inline imports in `static/js/*.js` point
at:

- **marked** — MIT
- **DOMPurify** — MPL-2.0 / Apache-2.0 dual
- **highlight.js** (github-dark theme) — BSD-3-Clause

### Packaging deps (macOS `.app`)

`desktop/requirements.txt` — installed only when building the bundle:

- **pyinstaller** — GPLv2-with-runtime-exception (bundled apps aren't
  GPL-tainted).
- **rumps** — BSD-3-Clause.
- **pynput** — LGPL-3.0.

### Runtime services (bring your own)

Not bundled or redistributed by this project — the studio talks to them
over HTTP:

- **Ollama** — MIT (github.com/ollama/ollama).
- **whisper.cpp** (optional STT) — MIT.
- **piper** (optional TTS) — MIT.

## Trademarks

The Local LLM Studio name and any associated logos are not covered by
the Apache 2.0 License. See [`LICENSE`](LICENSE) §6.
