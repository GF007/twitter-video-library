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
- When changing licensing or copyright text, keep `LICENSE`, `README.md`, and `README.en.md` aligned; the open-source license covers tracked source code, tooling, and documentation only, not third-party media, downloaded metadata, generated indexes, thumbnails, contact sheets, accepted tagging results, or private data.
- When this repo is nested inside a parent workspace, prefix `apply_patch` filenames with the repo directory (for example `twitter-video-library/...`) or patch from the repo root; bare `library/...` paths can write into the parent container.
- For main-classification JSONL containing Chinese category labels, validate with a UTF-8-safe path that cannot turn `动画分镜`, `动画片段`, or `其他` into `????`/`??`; include a raw-byte check for question-mark category values before merge/build.
- In local preview/editing mode, `其他` may be visible so records can be manually rescued into `动画片段` or `动画分镜`; in online/published mode, keep `其他` hidden and manual category writes disabled.
- For daily update indicators, write metadata with `tools/update_daily_update_metadata.py` after the final index rebuild and before online package build; use the final publishable diff for page counts, keep `daily_update` as the legacy mirror, and use `update_feed` for multiple public-safe update items.
- The Posts-tab downloader should wait and retry automatically after `rate_limited`/HTTP 429, using the configured `--rate-limit-retry-minutes` interval. If automatic retry is disabled or the process exits with `status=rate_limited`, stop before tagging, rebuilding, or publishing and resume only after download health is clean.
- Do not collapse same-`tweet_id` records with different `media_id` or `media_index` as automatic duplicates; show `/video/N`, `media_index`, or `media_id` in duplicate audits and treat content-hash matches as review candidates unless a stricter reviewed rule exists.
- For Twitter/X following or network audits, keep all credential use local through existing settings helpers, write full lists and reports only under ignored `download_state/`, never print cookies/tokens or full private lists, and stop on API 429/503 with resumable state instead of continuing expansion.
