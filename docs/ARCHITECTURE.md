# Architecture — Hydra Publisher

## Tech stack

| Layer | Technology |
|-------|-----------|
| Desktop shell | Tauri 2 (Rust backend, WebView frontend) |
| Frontend | Angular 17+ standalone components, Angular Material |
| Backend | Rust (commands exposed via Tauri IPC) |
| Persistence | `tauri-plugin-store` (JSON files in app data dir) |
| HTTP client (Rust) | `reqwest` (blocking for platform calls, async for AI) |
| Python bridge | System Python → venv → `http.server` HTTP server |
| AI | OpenAI-compatible API (`/v1/chat/completions`) via OpenRouter or any compatible host |

---

## Top-level directory layout

```
hydra-publisher/                      ← repo root
├── .github/workflows/release.yml     ← CI/CD (workflow_dispatch, Linux + Windows)
├── docs/                             ← this documentation
└── hydra-publisher/                  ← Tauri project root
    ├── src/                          ← Angular frontend
    │   └── app/
    │       ├── models/               ← TypeScript interfaces
    │       ├── services/             ← Tauri IPC wrappers + signal stores
    │       └── pages/                ← Lazy-loaded route components
    └── src-tauri/                    ← Rust backend
        ├── src/
        │   ├── lib.rs                ← app entry, plugin registration, setup hook
        │   ├── state.rs              ← AppState (shared mutable state)
        │   ├── commands/             ← Tauri command handlers
        │   │   ├── catalog.rs
        │   │   ├── publish.rs
        │   │   ├── ai.rs
        │   │   ├── settings.rs
        │   │   └── photos.rs
        │   └── models/               ← domain structs and platform impls
        │       ├── article.rs
        │       ├── platform.rs       ← Platform trait + TestPlatform
        │       ├── ebay_platform.rs
        │       ├── python_platform.rs
        │       ├── python_bridge.rs
        │       ├── settings.rs
        │       └── ai.rs
        ├── resources/python/         ← Python provider server (bundled at build time)
        │   ├── server.py
        │   ├── requirements.txt
        │   └── providers/
        │       ├── base.py
        │       ├── subito.py
        │       └── local_test_selenium.py
        └── tauri.conf.json
```

---

## Configuration and persistence

All persistent data lives in the OS app data directory (Tauri's `app_data_dir()`):

| File | Contents |
|------|----------|
| `settings.json` | `AppSettings` (catalog root, AI credentials, eBay token, language, etc.) |
| `publish_records.json` | `Vec<PublishRecord>` — survives app restarts |
| `python-venv/` | Python virtual environment, auto-created by `PythonBridge::start()` |

Settings are read via `tauri-plugin-store` on demand in every command handler (no global cached copy in Rust).

At startup, `lib.rs`'s `.setup()` hook restores `publish_records` from the store into `AppState::publish_records`.

---

## AppState (`state.rs`)

```rust
pub struct AppState {
    pub ai_requests:     Mutex<Vec<AiRequest>>,
    pub publish_records: Mutex<Vec<PublishRecord>>,
    pub article_counter: Mutex<u32>,          // monotonic counter for default article names
    pub python_bridge:   Arc<Mutex<Option<PythonBridge>>>,  // lazy-started, shared
}
```

- Managed by Tauri via `.manage(AppState::default())`.
- Accessed in commands via `tauri::State<'_, AppState>`.
- `python_bridge` is an `Arc` so `PythonPlatform` instances can each hold a clone without lifetime issues. The bridge is started lazily on the first Python-backed platform call.

---

## IPC flow (frontend → backend)

```
Angular component
  └─ calls service method (e.g. catalogService.loadArticles())
       └─ invoke('list_articles', {...})   [Tauri IPC]
            └─ Rust command handler
                 ├─ reads settings from store
                 ├─ performs work (fs, HTTP, ...)
                 └─ returns Result<T, String>
```

All Tauri commands return `Result<T, String>`. Errors are caught in the frontend and shown via `MatSnackBar`.

Serialization convention: Rust uses `#[serde(rename_all = "camelCase")]` so Rust `article_id` maps to TypeScript `articleId`.

---

## Catalog storage

Each article is a folder inside `catalogRoot`:

```
~/hydra-publisher/
└── My Article Name/
    ├── manifest.yaml    ← ArticleManifest (id, name, description, price, photos, videos, category, condition)
    ├── photo1.jpg
    ├── photo2.jpg
    └── ...
```

The article's `id` is a UUID v4 generated at creation time and stored in the manifest. The `folderPath` is the absolute path to the article folder (derived at read time, not stored in the manifest).

---

## Build and release

Development: `scripts/run.sh` → `yarn tauri dev`
Build: `yarn tauri build`
Release CI: `.github/workflows/release.yml` — `workflow_dispatch` with `version` input, builds for `ubuntu-22.04` and `windows-latest`, creates a draft GitHub release.

The workflow:
1. Bumps version in `tauri.conf.json` and `package.json` via Node.js inline script
2. Installs Linux system deps (`libwebkit2gtk-4.1-dev`, etc.) on Ubuntu
3. Runs `tauri-apps/tauri-action@v0` which builds + uploads artifacts to a draft GitHub release
