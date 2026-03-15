# CONTEXT — Hydra Publisher (LLM Quick Reference)

> This is the authoritative quick-reference for an LLM resuming work on this codebase.
> Read this file first, then consult `ARCHITECTURE.md`, `PLATFORMS.md`, `FRONTEND.md` for depth.

---

## What this app does

Hydra Publisher is a **desktop app** (Tauri 2 + Angular 17+) for listing second-hand items on multiple marketplaces simultaneously. The user:
1. Imports article folders (photos + metadata)
2. Optionally fills missing fields (name, description, price) via AI (OpenAI-compatible API)
3. Publishes or updates articles on platforms (eBay, Subito.it, …)

All article data lives on disk in `~/hydra-publisher/<Article Name>/manifest.yaml` plus photo files.

---

## Complete file map

```
hydra-publisher/
├── .github/workflows/release.yml

└── hydra-publisher/                        ← Tauri project root
    ├── src/app/
    │   ├── app.component.ts/html           ← shell with sidenav navigation
    │   ├── app.routes.ts                   ← lazy-loaded routes
    │   ├── models/
    │   │   ├── article.model.ts            ← Article interface
    │   │   ├── platform.model.ts           ← PlatformInfo, PublishRecord, status union
    │   │   ├── settings.model.ts           ← AppSettings interface
    │   │   └── ai-request.model.ts         ← AiRequest interface
    │   ├── services/
    │   │   ├── catalog.service.ts          ← article CRUD + signal store
    │   │   ├── publish.service.ts          ← publish/update + signal store
    │   │   ├── ai.service.ts               ← AI fill + 2s polling
    │   │   ├── photo.service.ts            ← file picker / copy wrappers
    │   │   └── settings.service.ts         ← load/save settings
    │   └── pages/
    │       ├── import/                     ← drag-drop / picker → create article
    │       ├── catalog/                    ← article card grid
    │       ├── article-detail/             ← edit metadata + photos
    │       ├── publish/                    ← accordion publish status + sell flow
    │       ├── ai-requests/                ← AI request history
    │       └── settings/                   ← settings form

    └── src-tauri/
        ├── tauri.conf.json                 ← identifier, window size, bundle resources
        ├── Cargo.toml
        └── src/
            ├── lib.rs                      ← plugin registration, setup hook (restore records)
            ├── state.rs                    ← AppState: ai_requests, publish_records, article_counter, python_bridge
            ├── commands/
            │   ├── catalog.rs              ← create/list/get/update/delete_article
            │   ├── publish.rs              ← list_platforms, publish_articles, update_articles, get_publish_records
            │   ├── ai.rs                   ← start_ai_fill, get_ai_requests, regenerate_article_fields
            │   ├── settings.rs             ← get_settings, save_settings
            │   └── photos.rs               ← pick_folder, pick_files, list_photos_in_folder, copy_photos_to_article
            └── models/
                ├── mod.rs                  ← pub mod declarations
                ├── article.rs              ← Article + ArticleManifest structs
                ├── platform.rs             ← Platform trait + TestPlatform + PublishRecord/Status enums
                ├── ebay_platform.rs        ← EbayPlatform (eBay Inventory API v1)
                ├── python_platform.rs      ← PythonPlatform (generic; delegates to Python bridge)
                ├── python_bridge.rs        ← PythonBridge: venv bootstrap + spawn server.py + HTTP call
                ├── settings.rs             ← AppSettings struct
                └── ai.rs                   ← AiRequest + AiRequestStatus structs

        resources/python/                   ← bundled at build time → flattened into <resource_dir>/python/
            ├── server.py                   ← HTTP server (Python built-in), manages Selenium sessions
            ├── requirements.txt            ← selenium, requests
            └── providers/
                ├── base.py                 ← Provider + SeleniumProvider abstract base classes
                ├── subito.py               ← STUB — SubitoProvider (not yet implemented)
                └── local_test_selenium.py  ← WORKING example — LocalTestSeleniumProvider
```

---

## Key invariants and constraints

### Rust serialization
All Rust structs use `#[serde(rename_all = "camelCase")]`. Rust `article_id` → TS `articleId`. The `PublishStatus` enum serializes unit variants as strings (`"Published"`) and tuple variants as objects (`{"Failed": "reason"}`).

### Article ID vs folderPath
- `id` is a UUID v4 stored in `manifest.yaml`, stable forever
- `folderPath` is the absolute filesystem path, computed at read time
- The Angular router uses `encodeURIComponent(folderPath)` as the `:id` route param

### Publish records persistence
`publish_records` are kept in `AppState::publish_records: Mutex<Vec<PublishRecord>>` at runtime AND persisted to `publish_records.json` via `tauri-plugin-store` after every mutation. On startup, `lib.rs`'s `.setup()` restores them.

### Python resource flattening
`tauri.conf.json` maps `resources/python/**/*` → `python/`. **All files end up in the same flat directory** — no subdirectories. Python imports must be flat (`from base import X`), never package-relative (`from .base import X`). `server.py` does `sys.path.insert(0, dirname(abspath(__file__)))` to ensure sibling files are importable.

### Python bridge lifetime
`PythonBridge` is started lazily on the first call to a Python-backed platform. It lives in `AppState::python_bridge: Arc<Mutex<Option<PythonBridge>>>`. The `Arc` is cloned into each `PythonPlatform` instance. When dropped (app exit), `Drop for PythonBridge` sends `POST /stop` then kills the process.

### Blocking calls in async commands
Tauri commands are `async`. Platform publish/update calls are blocking (HTTP). Uses `tokio::task::block_in_place(|| platform.publish(article))` to avoid blocking the async executor.

### lib.rs lifetime fix
In `.setup()`, the `if let Ok(mut guard) = state.publish_records.lock() { ... };` requires a trailing **semicolon** to make the temporary `Result<MutexGuard>` drop before `state` goes out of scope (Rust lifetime rule).

---

## AppState fields

```rust
pub struct AppState {
    pub ai_requests:     Mutex<Vec<AiRequest>>,
    pub publish_records: Mutex<Vec<PublishRecord>>,
    pub article_counter: Mutex<u32>,               // default article name counter
    pub python_bridge:   Arc<Mutex<Option<PythonBridge>>>,
}
```

---

## Registered Tauri commands

| Command | File | Description |
|---------|------|-------------|
| `get_settings` | commands/settings.rs | Load AppSettings from store |
| `save_settings` | commands/settings.rs | Save AppSettings to store |
| `pick_folder` | commands/photos.rs | Open folder picker |
| `pick_files` | commands/photos.rs | Open multi-file picker |
| `list_photos_in_folder` | commands/photos.rs | List image files in a folder |
| `copy_photos_to_article` | commands/photos.rs | Copy selected files into article folder |
| `create_article` | commands/catalog.rs | Create folder + manifest.yaml, copies photos |
| `list_articles` | commands/catalog.rs | Scan catalog root, return sorted articles |
| `get_article` | commands/catalog.rs | Read single article by folderPath |
| `update_article` | commands/catalog.rs | Overwrite manifest.yaml |
| `delete_article` | commands/catalog.rs | Remove entire article folder |
| `start_ai_fill` | commands/ai.rs | Start async AI fill for articles needing it |
| `get_ai_requests` | commands/ai.rs | Return current AI request list |
| `regenerate_article_fields` | commands/ai.rs | Force AI re-fill of all fields for one article |
| `list_platforms` | commands/publish.rs | Return hardcoded PlatformInfo list |
| `publish_articles` | commands/publish.rs | Publish articles to platforms, save records |
| `update_articles` | commands/publish.rs | Update articles on platforms, save records |
| `get_publish_records` | commands/publish.rs | Return current publish records |

---

## Registered platforms

| id | TS display name | Implementation |
|----|----------------|---------------|
| `test` | Test Platform | `TestPlatform` — always succeeds, prints to stdout |
| `ebay` | eBay | `EbayPlatform` — eBay Inventory API, needs `ebayToken` in settings |
| `subito` | Subito.it | `PythonPlatform("subito")` — delegates to `SubitoProvider` in Python (STUB) |
| `local_test_selenium` | Local Test Selenium | `PythonPlatform("local_test_selenium")` — working Selenium demo |

---

## AI subsystem

- Uses OpenAI `/v1/chat/completions` format (compatible with OpenRouter and others)
- Sends article photos as base64 inline images (`data:<mime>;base64,...`)
- Prompt asks AI to return JSON `{"name": "...", "description": "...", "price": 0.0}`
- Response is extracted from potential markdown code fences via `extract_json()`
- AI language is controlled by `settings.language` (mapped to full language name in the prompt)
- On completion, manifest.yaml is overwritten with the new values
- `AiRequestStatus`: `Pending → InProgress → Completed | Failed(String)`
- Frontend polls every 2 seconds while any request is active

---

## Settings fields

| Rust field | TS field | Default | Description |
|-----------|---------|---------|-------------|
| `catalog_root` | `catalogRoot` | `~/hydra-publisher` (Linux/Mac) or `Desktop/hydra-publisher` (Windows) | Article storage root |
| `ai_host` | `aiHost` | `https://openrouter.ai/api` | AI API base URL |
| `ai_token` | `aiToken` | `""` | AI API key |
| `ai_model` | `aiModel` | `gpt-4o` | Model name |
| `language` | `language` | `en` | Response language for AI |
| `recent_folders` | `recentFolders` | `[]` | Not currently used in UI |
| `ebay_token` | `ebayToken` | `""` | eBay OAuth2 User Token |

---

## Cargo.toml key dependencies

```toml
tauri = "2"                 # with protocol-asset feature
tauri-plugin-store = "2"    # JSON persistence
tauri-plugin-fs = "2"
tauri-plugin-dialog = "2"
tauri-plugin-opener = "2"
reqwest = "0.12"            # json + blocking features
serde_yaml = "0.9"          # manifest.yaml
uuid = "1"                  # v4 feature
base64 = "0.22"             # AI image encoding
tokio = "1"                 # full features
dirs-next = "2"             # default catalog root path
urlencoding = "2"           # eBay API URL encoding
```

---

## Known TODOs / incomplete features

- **Subito.it provider** (`providers/subito.py`): stub only — `publish()` and `update()` raise `NotImplementedError`
- **eBay `categoryId`**: hardcoded to `"9800"` — should derive from `article.category`
- **eBay `condition`**: hardcoded to `"USED_EXCELLENT"` — should map from `article.condition`
- **eBay photos**: local file paths used as image URLs — a real deployment needs eBay EPS gallery upload
- **eBay listing policies**: `fulfillmentPolicyId`, `paymentPolicyId`, `returnPolicyId` are empty strings
- **`recent_folders`** in settings: stored but not used in any UI
- **Import page**: photo selection and article creation; exact implementation details not reviewed in this context

---

## Gotchas for future LLM sessions

1. **Don't confuse `subito_platform.rs` with `python_platform.rs`**: the module was renamed. The current file is `python_platform.rs`, module declared as `pub mod python_platform` in `mod.rs`. There is no `subito_platform.rs`.

2. **`@for` over `Set` in Angular**: `selectedArticleIds()` returns a `Set<string>`; Angular's `@for` supports any JS iterable so this works directly.

3. **`matrixSelections` is `Map<string, Set<string>>`**: articleId → selected platformIds. Initialized in `goToMatrix()` with all non-published platforms pre-selected.

4. **`publish_articles` collects unique platform IDs across all articles**: the frontend sends a flat list of platformIds that applies to ALL selected articles. The backend skips already-published article+platform pairs.

5. **Python server port is dynamic**: OS assigns a free port at startup (`--port 0`). The port is communicated to Rust via stdout `LISTENING:<port>`.

6. **Selenium `detach: True`**: Chrome is opened with the `detach` option so it stays open when the WebDriver object goes out of scope. Sessions are explicitly closed only on `POST /stop`.

7. **`save_records()` is called twice per publish/update**: once after marking `Publishing`/`Updating` and once after updating final status. This means even if the app crashes mid-publish, the in-progress status is persisted.

8. **`lib.rs` semicolon**: `if let Ok(mut guard) = state.publish_records.lock() { *guard = records; };` — the trailing `;` is required to fix a Rust lifetime error (forces temp drop before `state` goes out of scope).
