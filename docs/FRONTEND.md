# Frontend — Angular Application

## Stack

- Angular 17+ with **standalone components** (no `NgModule`)
- Angular Material for UI (dark theme)
- Angular Signals (`signal()`, `computed()`) for state — no RxJS
- Tauri IPC via `@tauri-apps/api/core` `invoke()`
- Lazy-loaded routes (each page is its own chunk)

---

## Routing (`app.routes.ts`)

| Path | Component | Description |
|------|-----------|-------------|
| `/` | → redirect `/import` | |
| `/import` | `ImportComponent` | Import photos from disk into a new article |
| `/catalog` | `CatalogComponent` | Grid of all articles |
| `/catalog/:id` | `ArticleDetailComponent` | Edit article metadata + photos; `:id` = `encodeURIComponent(folderPath)` |
| `/publish` | `PublishComponent` | Publish and sync articles to platforms |
| `/ai` | `AiRequestsComponent` | View AI fill request history and status |
| `/settings` | `SettingsComponent` | App configuration |

The shell (`AppComponent`) renders a Material sidenav with nav items and a `<router-outlet>`.

---

## Services

### `CatalogService`

Wraps catalog Tauri commands. Owns `articlesSignal: signal<Article[]>`.

| Method | Tauri command | Notes |
|--------|--------------|-------|
| `loadArticles()` | `list_articles` | Refreshes internal signal |
| `createArticle(name, photoPaths)` | `create_article` | Returns new `Article`, refreshes list |
| `getArticle(folderPath)` | `get_article` | Single article by folder path |
| `updateArticle(article)` | `update_article` | Saves manifest.yaml, refreshes list |
| `deleteArticle(folderPath)` | `delete_article` | Removes folder, refreshes list |

### `PublishService`

Wraps publish Tauri commands. Owns `recordsSignal` and `platformsSignal`.

| Method | Tauri command | Notes |
|--------|--------------|-------|
| `loadPlatforms()` | `list_platforms` | |
| `publish(articleIds, platformIds)` | `publish_articles` | Blocks until all platforms complete |
| `update(articleIds, platformIds)` | `update_articles` | |
| `refreshRecords()` | `get_publish_records` | |

### `AiService`

Wraps AI commands. Polls every 2 seconds while any request is `Pending` or `InProgress`.

| Method | Notes |
|--------|-------|
| `startFill(articleIds)` | Starts AI fill for articles missing name/description/price |
| `refreshRequests()` | Fetches current request list; stops polling when none are active |

### `PhotoService`

Wraps photo picker and copy commands (`pick_folder`, `pick_files`, `copy_photos_to_article`, `list_photos_in_folder`).

### `SettingsService`

Wraps `get_settings` / `save_settings`. Owns `settingsSignal`.

---

## Angular Signals pattern

All components use `signal()` for local state and read from service signals:

```typescript
// Local signal
loading = signal(false);
articles = signal<Article[]>([]);

// Computed signal
articleGroups = computed<ArticleGroup[]>(() => { ... });

// Usage in template
@if (loading()) { ... }
@for (a of articles(); track a.id) { ... }
```

Services expose readonly signals:
```typescript
// In service
private articlesSignal = signal<Article[]>([]);
readonly articles = this.articlesSignal.asReadonly();

// In component
this.articles.set(this.catalogService.articles()); // copy into local signal
```

---

## Data models (`src/app/models/`)

### `Article`
```typescript
interface Article {
  id: string;           // UUID v4
  name: string;
  description: string;
  price: number | null;
  photos: string[];     // filenames relative to folderPath
  videos: string[];
  folderPath: string;   // absolute path to article folder
  category: string | null;  // e.g. "Elettronica", "Casa e giardino"
  condition: string | null; // e.g. "Usato", "Come nuovo"
}
```

### `PlatformInfo`
```typescript
interface PlatformInfo { id: string; name: string; }
```

### `PublishRecord`
```typescript
interface PublishRecord {
  articleId: string;
  platformId: string;
  status: 'NotPublished' | 'Publishing' | 'Published'
        | 'Updating' | 'Updated'
        | { Failed: string } | { UpdateFailed: string };
}
```

`status` is a Rust enum serialized by serde: unit variants become strings, tuple variants become `{ "VariantName": "value" }` objects.

### `AppSettings`
```typescript
interface AppSettings {
  catalogRoot: string;      // default: ~/hydra-publisher
  aiHost: string;           // default: https://openrouter.ai/api
  aiToken: string;
  aiModel: string;          // default: gpt-4o
  language: string;         // "en" | "it" | "fr" | "de" | "es" | "pt"
  recentFolders: string[];
  ebayToken: string;        // eBay OAuth2 User Token
}
```

---

## Pages

### `CatalogComponent`
- On init: loads articles, renders a card grid with first photo as thumbnail
- **AI Fill button**: finds articles missing name/description/price, calls `aiService.startFill()`, navigates to `/ai`
- **Card click**: navigates to `/catalog/{encodeURIComponent(folderPath)}`

### `ArticleDetailComponent`
- Route param `:id` = `encodeURIComponent(folderPath)`, decoded in `ngOnInit`
- Editable fields: `name`, `description`, `price`, `category` (mat-select), `condition` (mat-select)
- **Save**: calls `catalogService.updateArticle()`
- **Add Photos**: opens file picker, copies files, updates manifest
- **Regenerate Fields**: calls `regenerate_article_fields` Tauri command (forces AI re-fill of all fields), navigates to `/ai`
- **Delete**: calls `catalogService.deleteArticle()`, navigates to `/catalog`

Category options: `Casa e giardino | Intrattenimento | Abbigliamento e accessori | Famiglia | Elettronica | Hobby | Piccoli annunci`
Condition options: `Usato | Come nuovo | Buono | Accettabile`

### `PublishComponent`
Three-step flow + accordion idle view.

**Idle view** (when `step === 'idle'`):
- Lists `articleGroups` (computed from records, grouped by article, sorted by name)
- Each group header: article name + summary chips (✓ N success, ✕ N error, … N in-progress)
- Expand/collapse to see per-platform rows with status icon + label + inline progress bar + sync button
- "Sell" button starts the publish flow

**Step 1 — select-articles**: checkbox list of all articles

**Step 2 — select-matrix**: table of selected articles × all platforms; already-published pairs are pre-checked and disabled

**Publishing**: shows indeterminate progress bar while `publish_articles` command runs

**Sync button** (`syncRecord(record)`): calls `publishService.update([articleId], [platformId])` for a single record.

Status rendering helpers:
```typescript
isInProgress(status)  → status === 'Publishing' || 'Updating'
isSuccess(status)     → status === 'Published' || 'Updated'
isError(status)       → typeof status === 'object' && 'Failed'|'UpdateFailed' in status
statusIcon(status)    → 'check_circle' | 'error' | 'sync' | 'radio_button_unchecked'
statusClass(status)   → 'status-success' | 'status-error' | 'status-progress' | 'status-idle'
statusLabel(status)   → human-readable string including error message
```

### `SettingsComponent`
Simple form. Fields: catalog root (with folder picker), AI host, AI token, AI model, language, eBay OAuth token.

### `AiRequestsComponent`
Polls requests every 2 seconds while any are active. Shows request history with status, description, prompt (expandable), raw response (expandable), and regenerate button.

---

## Tauri IPC conventions

- All commands are registered in `lib.rs`:`invoke_handler`
- Arguments are passed as an object: `invoke('command_name', { argName: value })`
- Rust receives them as named function parameters (Tauri maps by name)
- Photo display: use `convertFileSrc(absolutePath)` from `@tauri-apps/api/core` to convert local file paths to `asset://` protocol URLs (CSP allows `assetProtocol: { enable: true, scope: ["**"] }`)
