# Repository metadata (for the maintainer)

Copy-paste-able strings for GitHub's *Settings → General* and *About*
panels when publishing v1.0. Not part of the runtime; keeps the
canonical wording under version control.

## Repository description (one-liner)

> Local-first LLM workspace on top of Ollama — hybrid RAG, tool loop,
> a menu-bar `.app`, and a Grafana stack.

*Constraints: 350 chars max; "Local", "LLM", "Ollama", "RAG" are the
useful search terms.*

## Website

- Docs: `https://<user>.github.io/local-llm-studio/`

## Topics

Recommended repository topics (paste into *Settings → Topics*):

```
llm  local-llm  ollama  rag  fastapi  python  macos  apple-silicon
agent  tool-use  chat  self-hosted  private-ai  workspace  observability
```

## Social preview

Suggested Open Graph image spec (replaces GitHub's auto-generated
preview):

- 1280 × 640 px, PNG.
- Studio logo left, "Local LLM Studio" 72 pt, subhead
  "Professional-grade AI workspace, on your machine" 32 pt.
- Bottom bar: `github.com/<user>/local-llm-studio` @ 20 pt monospace.
- Palette matches the app: bg `#0a0a0f`, primary `#a855f7`, accent
  `#22d3ee`.

Not committed to the repo — export from Figma / your image editor and
upload via *Settings → Social preview*.

## Release description (v1.0)

For the GitHub Release body, use the intro from
[`RELEASE_NOTES_v1.0.md`](RELEASE_NOTES_v1.0.md) — GitHub's markdown
render handles the same syntax MkDocs does.

## Discussion / issue templates

Not yet shipped. Suggested layout when adding:

- `.github/ISSUE_TEMPLATE/bug.yml` — version, install path, repro
  steps, expected/actual, logs (redact tokens).
- `.github/ISSUE_TEMPLATE/feature.yml` — problem, non-goals, sketch.
- `.github/DISCUSSION_TEMPLATE/showcase.yml` — for community
  workspaces / prompt packs.

## Sponsorship / funding

Skip for v1 — the project isn't taking donations. If that changes,
add `.github/FUNDING.yml` per GitHub docs.
