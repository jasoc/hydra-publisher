use std::path::Path;
use tauri::AppHandle;
use tauri_plugin_store::StoreExt;
use crate::models::article::{Article, ArticleManifest};
use crate::models::settings::AppSettings;
use crate::models::platform::PublishRecord;
use crate::state::AppState;

fn get_catalog_root(app: &AppHandle) -> Result<String, String> {
    let store = app.store("settings.json").map_err(|e| e.to_string())?;
    match store.get("settings") {
        Some(value) => {
            let settings: AppSettings = serde_json::from_value(value.clone()).map_err(|e| e.to_string())?;
            Ok(settings.catalog_root)
        }
        None => Ok(AppSettings::default().catalog_root),
    }
}

#[tauri::command]
pub async fn create_article(
    state: tauri::State<'_, AppState>,
    app: AppHandle,
    name: Option<String>,
    photo_paths: Vec<String>,
) -> Result<Article, String> {
    let catalog_root = get_catalog_root(&app)?;
    let root = Path::new(&catalog_root);

    if !root.exists() {
        std::fs::create_dir_all(root).map_err(|e| e.to_string())?;
    }

    // Generate progressive article name
    let mut counter = state.article_counter.lock().map_err(|e| e.to_string())?;
    *counter += 1;
    let article_name = name.unwrap_or_else(|| format!("Article {}", *counter));

    let id = uuid::Uuid::new_v4().to_string();
    let folder_name = sanitize_folder_name(&article_name);
    let article_folder = root.join(&folder_name);

    // Handle folder name collision
    let article_folder = if article_folder.exists() {
        let mut i = 1;
        loop {
            let candidate = root.join(format!("{}_{}", folder_name, i));
            if !candidate.exists() {
                break candidate;
            }
            i += 1;
        }
    } else {
        article_folder
    };

    std::fs::create_dir_all(&article_folder).map_err(|e| e.to_string())?;

    // Copy photos
    let mut photo_filenames = Vec::new();
    for src_path in &photo_paths {
        let src = Path::new(src_path);
        if let Some(filename) = src.file_name() {
            let dest = article_folder.join(filename);
            std::fs::copy(src, &dest).map_err(|e| e.to_string())?;
            photo_filenames.push(filename.to_string_lossy().to_string());
        }
    }

    // Create manifest
    let manifest = ArticleManifest::new(id, article_name, photo_filenames);
    let yaml = serde_yaml::to_string(&manifest).map_err(|e| e.to_string())?;
    let manifest_path = article_folder.join("manifest.yaml");
    std::fs::write(&manifest_path, yaml).map_err(|e| e.to_string())?;

    let folder_path = article_folder.to_string_lossy().to_string();
    Ok(manifest.to_article(folder_path))
}

#[tauri::command]
pub async fn list_articles(app: AppHandle) -> Result<Vec<Article>, String> {
    let catalog_root = get_catalog_root(&app)?;
    let root = Path::new(&catalog_root);

    if !root.exists() {
        return Ok(Vec::new());
    }

    let mut articles = Vec::new();
    let entries = std::fs::read_dir(root).map_err(|e| e.to_string())?;

    for entry in entries {
        let entry = entry.map_err(|e| e.to_string())?;
        let path = entry.path();
        if path.is_dir() {
            let manifest_path = path.join("manifest.yaml");
            if manifest_path.exists() {
                let content = std::fs::read_to_string(&manifest_path).map_err(|e| e.to_string())?;
                let manifest: ArticleManifest =
                    serde_yaml::from_str(&content).map_err(|e| e.to_string())?;
                articles.push(manifest.to_article(path.to_string_lossy().to_string()));
            }
        }
    }

    // Sort by name
    articles.sort_by(|a, b| a.name.cmp(&b.name));
    Ok(articles)
}

#[tauri::command]
pub async fn get_article(folder_path: String) -> Result<Article, String> {
    let path = Path::new(&folder_path);
    let manifest_path = path.join("manifest.yaml");

    if !manifest_path.exists() {
        return Err(format!("Manifest not found in {}", folder_path));
    }

    let content = std::fs::read_to_string(&manifest_path).map_err(|e| e.to_string())?;
    let manifest: ArticleManifest =
        serde_yaml::from_str(&content).map_err(|e| e.to_string())?;
    Ok(manifest.to_article(folder_path))
}

#[tauri::command]
pub async fn update_article(article: Article) -> Result<Article, String> {
    let path = Path::new(&article.folder_path);
    let manifest_path = path.join("manifest.yaml");

    let manifest = ArticleManifest {
        version: 1,
        id: article.id.clone(),
        name: article.name.clone(),
        description: article.description.clone(),
        price: article.price,
        photos: article.photos.clone(),
        videos: article.videos.clone(),
        category: article.category.clone(),
        condition: article.condition.clone(),
    };

    let yaml = serde_yaml::to_string(&manifest).map_err(|e| e.to_string())?;
    std::fs::write(&manifest_path, yaml).map_err(|e| e.to_string())?;

    Ok(article)
}

#[tauri::command]
pub async fn delete_article(folder_path: String) -> Result<(), String> {
    let path = Path::new(&folder_path);
    if path.exists() {
        std::fs::remove_dir_all(path).map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
pub async fn clear_all_app_data(
    state: tauri::State<'_, AppState>,
    app: AppHandle,
) -> Result<(), String> {
    let catalog_root = get_catalog_root(&app)?;

    // Stop Python bridge (closes running Selenium sessions) but keep persisted profiles.
    {
        let mut bridge = state.python_bridge.lock().map_err(|e| e.to_string())?;
        *bridge = None;
    }

    // Delete all local catalog copies managed by the app.
    let root = Path::new(&catalog_root);
    if root.exists() {
        std::fs::remove_dir_all(root).map_err(|e| e.to_string())?;
    }
    std::fs::create_dir_all(root).map_err(|e| e.to_string())?;

    // Reset settings to defaults.
    {
        let settings_store = app.store("settings.json").map_err(|e| e.to_string())?;
        let defaults = AppSettings::default();
        let value = serde_json::to_value(&defaults).map_err(|e| e.to_string())?;
        settings_store.set("settings", value);
        settings_store.save().map_err(|e| e.to_string())?;
    }

    // Clear publish records persisted on disk.
    {
        let records_store = app.store("publish_records.json").map_err(|e| e.to_string())?;
        let empty = serde_json::to_value(Vec::<PublishRecord>::new()).map_err(|e| e.to_string())?;
        records_store.set("records", empty);
        records_store.save().map_err(|e| e.to_string())?;
    }

    // Clear in-memory runtime state.
    {
        let mut publish_records = state.publish_records.lock().map_err(|e| e.to_string())?;
        publish_records.clear();
    }
    {
        let mut ai_requests = state.ai_requests.lock().map_err(|e| e.to_string())?;
        ai_requests.clear();
    }
    {
        let mut article_counter = state.article_counter.lock().map_err(|e| e.to_string())?;
        *article_counter = 0;
    }

    Ok(())
}

fn sanitize_folder_name(name: &str) -> String {
    name.chars()
        .map(|c| {
            if c.is_alphanumeric() || c == '-' || c == '_' || c == ' ' {
                c
            } else {
                '_'
            }
        })
        .collect::<String>()
        .trim()
        .to_string()
}
