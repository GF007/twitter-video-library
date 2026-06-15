# AGENTS.md

## Scope

This repository is public-safe code only:

- Keep static frontend code and local tagging/build tools tracked.
- Do not commit media, downloaded metadata, generated indexes, accepted tag results, creator lists, private settings, deployment outputs, or remote publish workflow details.
- Treat `Downloads/`, `library/`, `download_state/`, `dist/`, `verification/`, and `settings.json` as local-only.

## Development Rules

- Before substantial code changes, check `.learnings/` if it exists locally, but do not track that directory.
- For frontend changes to `index.html`, run a JavaScript syntax check and verify through a local HTTP server.
- Use `python .\tools\serve_video_library.py --port 8765` for local preview when testing playback, because it supports HTTP Range requests.
- Tagging worker outputs and generated contact sheets are local data. Keep them under ignored `library/`.
- Do not add provider-specific deployment notes, credentials, account cookies, creator lists, or upload/publish instructions to tracked files.
