# Hydra Publisher — App Baseline

## Goal
Cross-platform desktop app (Tauri) to import product articles and publish to multiple marketplaces.

## Stable architecture
- Frontend: Angular standalone app in `hydra-publisher/src/app`.
- Desktop/backend: Rust + Tauri commands in `hydra-publisher/src-tauri/src/commands`.
- Python automation: provider HTTP server + Selenium providers in `hydra-publisher/src-tauri/resources/python`.

## Main flow
1. Import photos and create local article copy (manifest + media).
2. Edit/complete article metadata.
3. Publish selected article-platform pairs.
4. Track per-platform status and retry failed entries.

## Key directories
- Frontend UI/routes/pages: `hydra-publisher/src/app/pages`
- Frontend models/services: `hydra-publisher/src/app/models`, `hydra-publisher/src/app/services`
- Tauri commands: `hydra-publisher/src-tauri/src/commands`
- Rust models/state: `hydra-publisher/src-tauri/src/models`, `hydra-publisher/src-tauri/src/state.rs`
- Python bridge/providers: `hydra-publisher/src-tauri/resources/python`
- Project docs: `docs/`

## Current behavioral baseline (2026-04)
- Selenium login is manual and separated from publish flow.
- Settings includes provider-specific “open login session” actions.
- Publish uses explicit article-platform pairs (no cartesian article×platform behavior).
- Publish UI is unified on one operational page.
- Settings includes full app-data reset:
  - clears local catalog copies, publish records, in-memory queues/counters, settings
  - keeps Selenium Chrome profiles
  - never touches original source photos

## Where to look first (by task)
- Publish flow/UI: `hydra-publisher/src/app/pages/publish`
- Settings actions/UI: `hydra-publisher/src/app/pages/settings`
- Publish backend logic: `hydra-publisher/src-tauri/src/commands/publish.rs`
- Data reset logic: `hydra-publisher/src-tauri/src/commands/catalog.rs`
- Python server session behavior: `hydra-publisher/src-tauri/resources/python/server.py`
- Provider-specific browser logic: `hydra-publisher/src-tauri/resources/python/providers/*.py`

## Operating principle
Read this file first before exploring code. Use targeted reads only for the exact area touched by the request.
