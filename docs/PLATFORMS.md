# Platforms and Python Bridge

## The `Platform` trait

Defined in `src-tauri/src/models/platform.rs`:

```rust
pub trait Platform: Send + Sync {
    fn id(&self) -> &str;
    fn name(&self) -> &str;
    fn publish(&self, article: &Article) -> Result<(), String>;
    fn update(&self, _article: &Article) -> Result<(), String> {
        // default: returns error "not supported"
    }
}
```

Every platform is instantiated inside `get_platforms()` in `commands/publish.rs` per-request (not stored in state). The `python_bridge` Arc is shared across all Python platform instances.

---

## Registered platforms

| id | Name | Rust struct | Notes |
|----|------|-------------|-------|
| `test` | Test Platform | `TestPlatform` | Prints to stdout, always succeeds |
| `ebay` | eBay | `EbayPlatform` | eBay Inventory API v1, OAuth token required |
| `subito` | Subito.it | `PythonPlatform("subito", ...)` | Delegates to Python `SubitoProvider` — stub, not implemented |
| `local_test_selenium` | Local Test Selenium | `PythonPlatform("local_test_selenium", ...)` | Working Selenium example, opens Chrome |

Adding a new platform:
- **Pure Rust**: implement `Platform`, add to `get_platforms()`, add to `list_platforms()`.
- **Python**: add `<id>.py` in `resources/python/providers/`, register in `server.py` PROVIDERS dict, add `PythonPlatform::new(id, name, ...)` in `get_platforms()`, add entry in `list_platforms()`.

---

## eBay platform (`ebay_platform.rs`)

Authentication: OAuth 2.0 User Token with `sell.inventory` scope. Token is stored in `AppSettings::ebay_token` and configured in the Settings page.

**publish() flow:**
1. `PUT /sell/inventory/v1/inventory_item/{sku}` — upsert inventory item (SKU = article UUID)
2. `POST /sell/inventory/v1/offer` — create offer (marketplace: `EBAY_IT`, fixed price, quantity 1)
3. `POST /sell/inventory/v1/offer/{offerId}/publish` — publish the offer

**update() flow:**
1. Same `PUT` to upsert inventory item (idempotent)
2. `GET /sell/inventory/v1/offer?sku={sku}` — find existing offer ID
3. `PUT /sell/inventory/v1/offer/{offerId}` — update the offer

**Known limitations / TODOs:**
- `categoryId` is hardcoded to `"9800"` — should be configurable or derived from `article.category`
- `condition` is hardcoded to `"USED_EXCELLENT"` — should map from `article.condition`
- Photos are referenced as local file paths; a real deployment needs to upload them to eBay EPS gallery first
- `listingPolicies` fulfillment/payment/return IDs are empty strings — must be filled with IDs from eBay Seller Hub

---

## Python bridge architecture

### Overview

```
Rust (PythonPlatform) ──HTTP──► Python server (server.py)
                                    │
                     ┌──────────────┼──────────────┐
                     ▼              ▼               ▼
               SubitoProvider  LocalTestSelenium  (future)
               (HTTP-based)    (Selenium)
```

### Startup sequence (`PythonBridge::start`)

1. Derive `venv_dir = app_data_dir + "/python-venv"`
2. If venv does not exist: `python3 -m venv <venv_dir>`
3. If `requirements.txt` exists: `<venv>/bin/pip install --quiet -r requirements.txt`
4. Spawn `<venv>/bin/python3 server.py --port 0` with stdout piped
5. Read first line from stdout; expect `LISTENING:<port>`
6. Drain remaining stdout in background thread to prevent blocking
7. Store `port` in `PythonBridge`

The bridge is started lazily: `PythonPlatform::ensure_bridge()` locks the Arc and starts it only if `Option` is `None`.

### Shutdown

`Drop for PythonBridge`:
1. `POST http://127.0.0.1:{port}/stop` (graceful: closes Selenium sessions, waits 5s)
2. `process.kill()` (hard kill as fallback)

### HTTP call format (`PythonBridge::call`)

```
POST http://127.0.0.1:{port}/{provider_id}/{method}
Content-Type: application/json
Body: JSON-serialized Article (camelCase keys)
Timeout: 300 seconds (Selenium interactions can be slow)
```

Success: HTTP 2xx → `Ok(())`
Error: HTTP non-2xx → extracts `{"error": "..."}` from body → `Err(message)`

---

## Python server (`resources/python/server.py`)

Single-threaded HTTP server using Python's built-in `http.server`. Started on `--port 0` (OS assigns a free port).

**Key design decisions:**
- `sys.path.insert(0, dirname(abspath(__file__)))` ensures flat imports work regardless of working directory
- All provider files import directly: `from base import ...`, `from subito import ...` (NOT package-relative imports like `from .base import ...`)
- `PROVIDERS` dict maps provider id → instance (built at module load time)
- Selenium sessions are cached in `_selenium_sessions: Dict[str, WebDriver]` — browser opens once per provider per session

**Endpoints:**
| Method | Path | Description |
|--------|------|-------------|
| POST | `/{provider_id}/publish` | Publish article; Body: Article JSON |
| POST | `/{provider_id}/update` | Update article; Body: Article JSON |
| POST | `/stop` | Close Selenium sessions, signal shutdown |

---

## Tauri resource bundling — IMPORTANT QUIRK

`tauri.conf.json` bundle resources:
```json
"resources": { "resources/python/**/*": "python/" }
```

This glob **flattens the directory tree**. At runtime:
- `resources/python/server.py` → `<resource_dir>/python/server.py`
- `resources/python/providers/base.py` → `<resource_dir>/python/base.py`
- `resources/python/providers/subito.py` → `<resource_dir>/python/subito.py`

**There is no `providers/` subdirectory at runtime.** All files land directly in `python/`.

Consequences:
- All imports in Python files must be flat: `from base import Provider` ✓, `from providers.base import Provider` ✗
- No relative imports (`from .base import ...` fails because there is no package)
- `server.py` must do `sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))` to find sibling modules

---

## Python base classes (`providers/base.py`)

### `Provider` — HTTP-based platforms (no browser)

```python
class Provider(ABC):
    uses_selenium: bool = False
    def publish(self, article: dict) -> None: ...   # abstract
    def update(self, article: dict) -> None: ...    # default raises NotImplementedError
```

### `SeleniumProvider` — browser-based platforms

```python
class SeleniumProvider(ABC):
    uses_selenium: bool = True
    def login(self, driver: Any) -> None: ...       # default: no-op; override to handle login
    def publish(self, article: dict, driver: Any) -> None: ...  # abstract
    def update(self, article: dict, driver: Any) -> None: ...   # default raises NotImplementedError
```

For `SeleniumProvider` subclasses, `server.py` manages the `WebDriver` lifecycle:
- First call: create `Chrome(options=Options())` with `detach=True`, call `provider.login(driver)`, cache in `_selenium_sessions`
- Subsequent calls: retrieve cached driver, skip login

### Article dict keys (passed to Python providers)

All keys are camelCase (Rust serializes with `rename_all = "camelCase"`):

```python
{
    "id":          str,           # UUID v4
    "name":        str,
    "description": str,
    "price":       float | None,
    "photos":      list[str],     # filenames only (no path)
    "videos":      list[str],
    "folderPath":  str,           # absolute path to article folder
    "category":    str | None,    # e.g. "Elettronica"
    "condition":   str | None,    # e.g. "Usato"
}
```

`photos` are filenames relative to `folderPath`. To get absolute paths use `os.path.join(article["folderPath"], photo)`.

---

## Adding a new Python provider — checklist

1. Create `resources/python/providers/<id>.py` with a class extending `Provider` or `SeleniumProvider`
2. Use `from base import Provider` (flat import, no package prefix)
3. Register in `server.py`: add import + entry in `PROVIDERS = { "<id>": MyProvider() }`
4. Add `PythonPlatform::new("<id>", "Display Name", python_bridge.clone(), python_dir.clone(), app_data_dir.clone())` in `get_platforms()` in `commands/publish.rs`
5. Add `PlatformInfo { id: "<id>".to_string(), name: "Display Name".to_string() }` in `list_platforms()` in `commands/publish.rs`
6. If extra Python deps needed, add to `resources/python/requirements.txt`
