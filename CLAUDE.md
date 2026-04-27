# Hydra Publisher — Claude Code Instructions

## Meta — keeping these instructions up to date

**Update this file proactively.** Whenever a debugging session reveals a non-obvious gotcha, a new dev workflow step is confirmed, or a convention is established, add it here without waiting to be asked. The goal is that future conversations start with full context and never repeat the same investigation twice.

## Documentation index (read first)

- `docs/AGENT-CHARACTER.md` — execution style and communication constraints (brevity, minimal changes, no unnecessary commands/builds).
- `docs/APP-BASELINE.md` — stable app map and entry points to avoid repeating broad repository exploration.

---

## What this project is

**Hydra Publisher** is a cross-platform desktop app (Tauri) that lets users import product articles (photos + metadata) and publish them simultaneously to multiple e-commerce marketplaces (eBay, Facebook Marketplace, Vinted, Subito, …).

The core loop is:
1. Import photos from filesystem → create an article (YAML manifest + image files)
2. Optionally use AI to generate the description
3. Select articles + target platforms → publish in batch
4. Track publish status per article/platform and retry on failure

---

## Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Angular 21 (standalone components, Signals, Angular Material) |
| Desktop shell | Tauri 2 (Rust) |
| Native backend | Rust (eBay REST API, file I/O, system dialogs, settings persistence) |
| Browser automation | Python 3 + Selenium (spawned as subprocess by Rust) |
| Storage | YAML files per article, Tauri Store (JSON) for settings |

---

## Architecture

```
Angular (UI)
    │  Tauri IPC (invoke)
    ▼
Rust/Tauri commands    ──────────────────────────────────────────────────┐
  commands/publish.rs                                                    │
  commands/catalog.rs                                                    │
  commands/ai.rs                                                         │
  commands/settings.rs                                                   │
    │                                                                    │
    │  HTTP localhost (port discovered at runtime)                       │
    ▼                                                                    │
Python provider server (server.py)                                       │
    │  Provider registry (PROVIDERS dict)                                │
    ▼                                                                    │
Provider implementations                                                 │
  providers/facebook_marketplace.py  (Selenium)                          │
  providers/subito.py                (HTTP API, stub)                    │
  providers/vinted.py                (Selenium, add here)                │
  providers/base.py                  (Provider / SeleniumProvider ABCs)  │
                                                                         │
eBay API (REST) ◄────────────────────────────────────────────────────────┘
  models/ebay_platform.rs
```

### Key data flows

- **Article on disk**: `~/.hydra-publisher/catalog/<uuid>/manifest.yaml` + images
- **Publish record**: stored in Tauri Store (`publish_records.json`), keyed by `article_id + platform_id`
- **Python server**: spawned once at app start, port written to stdout as `LISTENING:<port>`, stored in `PythonBridge` state
- **Selenium sessions**: one shared Chrome instance with a single persistent profile at `~/.hydra-publisher/chrome-profile/`, reused across all providers

---

## Platform trait (Rust side)

Every platform must implement the `Platform` trait (`models/platform.rs`):

```rust
pub trait Platform: Send + Sync {
    fn id(&self) -> &str;
    fn publish(&self, article: &Article) -> Result<String, String>; // returns external listing id
    fn update(&self, article: &Article, listing_id: &str) -> Result<(), String>;
}
```

Platforms are registered in `commands/publish.rs` in the `get_platforms()` function.

### Two kinds of Rust platforms

- **Native** (e.g. `EbayPlatform`): implemented fully in Rust, calls external REST API
- **Python-backed** (`PythonPlatform`): thin Rust wrapper that forwards to the Python server over HTTP

---

## Adding a new Selenium-based platform (end-to-end checklist)

### 1. Python provider

Create `src-tauri/resources/python/providers/<name>.py`:

```python
from base import SeleniumProvider

class VintedProvider(SeleniumProvider):
    def login(self, driver): ...          # or use start_login/confirm_login
    def publish(self, article, driver): ...
    def update(self, article, driver): ... # optional
```

Register it in `server.py`:
```python
from vinted import VintedProvider
PROVIDERS = {
    ...
    "vinted": VintedProvider(),
}
```

### 2. Rust platform wrapper

Add a `PythonPlatform::new("vinted")` entry in `commands/publish.rs` → `get_platforms()`.

### 3. Frontend model

Add the platform id to `src/app/models/platform.model.ts` so the UI knows about it.

### 4. Settings (if credentials needed)

Add credential fields to `AppSettings` in `models/settings.rs` and `settings.model.ts`, then expose them in `settings.component.html`.

---

## Subito.it — implementation status and manual session

The `providers/subito.py` provider is **fully implemented** as a `SeleniumProvider`.
Full session log & selectors: `docs/subito-manual-publish-session.md`

### Verified publish flow (10 Selenium steps)
1. Navigate to `https://inserimento.subito.it/?category=<id>&subject=<title>&from=vendere`
2. Hide modal via JS: `document.querySelector('[role="dialog"]').style.display='none'`
3. Set `textarea` (description) + `#price` via **React native setter** + dispatch `input`/`change`
4. Open **Condizione** React-Select: `el.click()` (real CDP) + `send_keys(Keys.ARROW_DOWN)` → poll `[role="option"]` → JS click
5. Show hidden `input[type="file"]` via JS, then `send_keys(path)` per photo
6. Set `#location` (Comune) via React setter → wait AJAX `[role="option"]` → JS click
7. Set `#phone` via React setter
8. Click **Continua** → `/anteprima` page
9. Click **Pubblica annuncio** → `promuovi-form/id:ad:<UUID>` (extract UUID here)
10. Skip upsell: "Non mi interessa" modal → "Continua con visibilità minima" page → `/inserito` confirmation

### Critical JS trick — React controlled inputs
Plain `el.value = x` or Selenium `send_keys` do NOT trigger React state for comboboxes.
Use the native setter hack:
```python
driver.execute_script("""
  var p = el.tagName === 'TEXTAREA'
    ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(p, 'value').set.call(arguments[0], arguments[1]);
  arguments[0].dispatchEvent(new Event('input',  {bubbles: true}));
  arguments[0].dispatchEvent(new Event('change', {bubbles: true}));
""", el, value)
```

### React-Select combobox (Condizione) — JS .click() does NOT open it
```python
el.click()                      # real Selenium click (CDP) — required
el.send_keys(Keys.ARROW_DOWN)   # ensures listbox opens
# then poll [role="option"] and JS-click the target
```

---

## Selector strategy for Selenium providers

See **`docs/selenium-selectors.md`** for the recommended approach to discovering and maintaining CSS/XPath selectors without manual DOM inspection every time.

**TL;DR**: use Playwright `codegen` to record interactions → copy reliable locators → paste into a per-provider `selectors/*.yaml` config → the `FormFiller` helper in `base.py` handles the actual filling.

---

## Conventions

- **Article dict keys** (Python side): `id`, `name`, `description`, `price`, `photos` (list of filenames), `folderPath`, `category`, `condition`
- **Provider IDs** must match exactly between `PROVIDERS` dict, Rust `PythonPlatform::new(id)`, and the frontend model
- **Selectors** prefer `aria-label`, `data-testid`, `name` attributes over CSS classes — classes change with every deploy
- **Waits**: always use `WebDriverWait` + `expected_conditions`, never bare `time.sleep()` except after a click that triggers a React re-render (max 2 s)
- **Errors**: raise `ValueError` for missing required fields, `RuntimeError` for browser interaction failures — the server converts these to HTTP 500 with `{"error": "..."}` which Rust surfaces to the UI
- **MCP publish policy**: when the user asks to finalize/publish an article, execute the full flow end-to-end **without asking for confirmation**.
- **MCP batching policy**: minimize tool calls by grouping text-field operations into one `evaluate_script`; keep separate real interactions only where required (e.g. React-Select dropdowns need real click/keyboard).
- **Multi-article runs**: treat each article as an atomic transaction: publish → skip upsell → verify `/annunci/inserito?adId=...` → move to next article.

## Execution guardrails (2026-04)

- Do not run compilation/syntax/lint checks by default (`py_compile`, `cargo check`, `tsc`, etc.) unless explicitly requested by the user.
- Do not run `cd` commands unless strictly necessary for executing a required command.
- If the user asks for low-noise execution (no extra checks), perform only the requested edits and stop.

## Login flow update (2026-04)

- Selenium providers no longer own a coded credential/TOTP login procedure in the publish flow.
- Publish now runs directly on selected article/platform pairs; if a session is not authenticated, provider publish fails normally and the record is marked failed.
- Manual login is triggered from **Settings** via per-provider buttons that only open/reuse the Selenium Chrome session with the Hydra persistent profile.
- Python server endpoint `POST /<provider>/login` is now session-opening only (`{"status":"ready"}`), not a credential workflow.

## Vinted publish flow updates (2026-04)

- Vinted form fields are dynamic by category/type; provider logic must detect optional fields (`brand`, `condition`, `color`, `size`) and fill only those present.
- Brand selection policy: after typing the brand in the popup search, always click the **last** available option (this covers the fallback action like "crea articolo con brand ...").
- Size policy: when `Taglia` is present, open the popup, count available `size-*` options and select the middle item.

## Data reset behavior (2026-04)

- A new Settings action clears all app data: local catalog copies, publish records, in-memory queues/counters, and settings.
- The reset intentionally **does not delete** the Selenium Chrome profile under `~/.hydra-publisher/chrome-profile/`.
- Original source photos are never touched because only catalog copies under `catalogRoot` are removed.

---

## Dev workflow

```bash
# Start the full app (preferred — handles yarn install + tauri dev)
scripts/run.sh

# Frontend + Rust dev server (alternative, from inside hydra-publisher/)
cd hydra-publisher && yarn tauri dev

# Run Python server standalone (for provider development)
# Use the app venv, not the system Python
~/.local/share/com.jasoc.hydra-publisher.app/python-venv/bin/python3 \
  src-tauri/resources/python/server.py --port 8765

# Curl a provider directly
curl -X POST http://localhost:8765/vinted/publish \
  -H 'Content-Type: application/json' \
  -d '{"name":"Test","price":10,"photos":[],"folderPath":"/tmp"}'
```

### Dev vs bundle layout (important for Python providers)

Tauri bundles Python resources with `"resources/python/**/*": "python/"`, which **flattens** the entire tree into a single `python/` directory. This means:

| | Dev mode | Bundle |
|---|---|---|
| `server.py` location | `resources/python/server.py` | `python/server.py` |
| Provider `.py` files | `resources/python/providers/*.py` | `python/*.py` (flat) |
| Selector YAML files | `resources/python/providers/selectors/*.yaml` | `python/*.yaml` (flat) |

`server.py` adds both `python/` and `python/providers/` to `sys.path` to handle both layouts.

When writing a provider that loads a YAML selector file, always try the dev path first and fall back to the flat bundle path:
```python
_SELECTORS = os.path.join(os.path.dirname(__file__), "selectors", "myprovider.yaml")
if not os.path.exists(_SELECTORS):
    _SELECTORS = os.path.join(os.path.dirname(__file__), "myprovider.yaml")
```

### Python venv

The app manages its own venv at `~/.local/share/com.jasoc.hydra-publisher.app/python-venv/`. Dependencies are installed automatically from `requirements.txt` at startup. Never use the system `python3` directly — it does not have selenium installed.

---

## File map (quick reference)

```
hydra-publisher/
├── src/                              Angular frontend
│   └── app/
│       ├── pages/                    One directory per route/page
│       ├── services/                 Tauri IPC wrappers
│       └── models/                   Shared TypeScript interfaces
└── src-tauri/
    ├── src/
    │   ├── commands/                 Tauri command handlers (IPC endpoints)
    │   ├── models/                   Rust structs & platform implementations
    │   ├── state.rs                  Global app state (Arc<Mutex<…>>)
    │   └── lib.rs                    Tauri app bootstrap & command registration
    └── resources/python/
        ├── server.py                 HTTP dispatcher + Selenium session manager
        └── providers/
            ├── base.py               Provider & SeleniumProvider ABCs
            ├── facebook_marketplace.py
            ├── subito.py
            └── <new_provider>.py     ← add here
```
