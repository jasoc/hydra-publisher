# Implementing a New Provider

A **Provider** (or Platform) is a module that publishes articles to an external platform (e.g. Facebook Marketplace, Vinted, eBay, Subito.it).

This guide explains how to implement the base interface.

## Architecture

The provider system lives entirely in the Rust backend. The frontend does not need changes -- it discovers available providers at runtime via the `list_platforms` command.

```
src-tauri/src/models/platform.rs   -- Platform trait + data models
src-tauri/src/commands/publish.rs   -- Provider registry + publish orchestration
```

## The `Platform` trait

Every provider must implement the `Platform` trait defined in `src-tauri/src/models/platform.rs`:

```rust
pub trait Platform: Send + Sync {
    fn id(&self) -> &str;
    fn name(&self) -> &str;
    fn publish(&self, article: &Article) -> Result<(), String>;
}
```

| Method    | Description                                                                 |
|-----------|-----------------------------------------------------------------------------|
| `id()`    | Unique slug used internally (e.g. `"facebook"`, `"vinted"`, `"ebay"`).      |
| `name()`  | Human-readable name shown in the UI (e.g. `"Facebook Marketplace"`).        |
| `publish()`| Receives an `Article` and performs the actual publishing. Returns `Ok(())` on success or `Err(message)` on failure. |

The trait requires `Send + Sync` because publishing runs on Tauri's async runtime.

## The `Article` struct

The `Article` passed to `publish()` contains all the data you need:

```rust
pub struct Article {
    pub id: String,
    pub name: String,
    pub description: String,
    pub price: Option<f64>,
    pub photos: Vec<String>,   // filenames relative to folder_path
    pub videos: Vec<String>,   // filenames relative to folder_path
    pub folder_path: String,   // absolute path to the article directory
}
```

To get the full path of a photo: `Path::new(&article.folder_path).join(&article.photos[i])`.

## Step-by-step

### 1. Create the provider struct

Add your struct in `src-tauri/src/models/platform.rs` (or in a separate file, re-exported from the module):

```rust
pub struct FacebookMarketplace {
    // Add any fields you need (API keys, tokens, etc.)
}

impl Platform for FacebookMarketplace {
    fn id(&self) -> &str {
        "facebook-marketplace"
    }

    fn name(&self) -> &str {
        "Facebook Marketplace"
    }

    fn publish(&self, article: &Article) -> Result<(), String> {
        // 1. Build the request payload from article fields
        // 2. Read photo files from article.folder_path
        // 3. Call the external API
        // 4. Return Ok(()) or Err("reason")
        todo!()
    }
}
```

### 2. Register the provider

Open `src-tauri/src/commands/publish.rs` and add the new provider to the `get_platforms()` function:

```rust
fn get_platforms() -> Vec<Box<dyn Platform>> {
    vec![
        Box::new(TestPlatform),
        Box::new(FacebookMarketplace { /* ... */ }),
    ]
}
```

That's it. The frontend will automatically show the new platform in the publish matrix.

### 3. (Optional) Add provider settings

If your provider requires credentials (API keys, tokens), add fields to `AppSettings` in `src-tauri/src/models/settings.rs`:

```rust
pub struct AppSettings {
    // ... existing fields ...
    pub facebook_api_token: String,
}
```

Then read them from the store inside `publish()` or pass them when constructing the struct in `get_platforms()`.

## Example: minimal eBay provider

```rust
pub struct EbayPlatform;

impl Platform for EbayPlatform {
    fn id(&self) -> &str {
        "ebay"
    }

    fn name(&self) -> &str {
        "eBay"
    }

    fn publish(&self, article: &Article) -> Result<(), String> {
        let price = article.price.ok_or("eBay requires a price")?;
        // Upload photos, create listing via eBay API...
        println!("[eBay] Listing '{}' at {:.2} EUR", article.name, price);
        Ok(())
    }
}
```

## Status tracking

You do not need to manage status yourself. The orchestrator in `publish_articles()` automatically:

1. Creates a `PublishRecord` with status `Publishing` before calling your `publish()`.
2. Updates it to `Published` on `Ok(())` or `Failed(message)` on `Err(message)`.
3. The frontend polls `get_publish_records()` to reflect real-time status.
