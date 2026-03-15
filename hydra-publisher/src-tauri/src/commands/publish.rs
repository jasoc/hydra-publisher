use std::path::Path;
use tauri::AppHandle;
use tauri_plugin_store::StoreExt;
use crate::models::article::ArticleManifest;
use crate::models::platform::{PlatformInfo, Platform, PublishRecord, PublishStatus, TestPlatform};
use crate::models::settings::AppSettings;
use crate::state::AppState;

fn get_platforms() -> Vec<Box<dyn Platform>> {
    vec![Box::new(TestPlatform)]
}

#[tauri::command]
pub fn list_platforms() -> Vec<PlatformInfo> {
    get_platforms()
        .iter()
        .map(|p| PlatformInfo {
            id: p.id().to_string(),
            name: p.name().to_string(),
        })
        .collect()
}

#[tauri::command]
pub async fn publish_articles(
    state: tauri::State<'_, AppState>,
    app: AppHandle,
    article_ids: Vec<String>,
    platform_ids: Vec<String>,
) -> Result<(), String> {
    // Load settings to get catalog root
    let store = app.store("settings.json").map_err(|e| e.to_string())?;
    let settings: AppSettings = match store.get("settings") {
        Some(value) => serde_json::from_value(value.clone()).map_err(|e| e.to_string())?,
        None => AppSettings::default(),
    };

    let root = Path::new(&settings.catalog_root);
    let platforms = get_platforms();

    // Load articles
    let mut articles = Vec::new();
    if root.exists() {
        let entries = std::fs::read_dir(root).map_err(|e| e.to_string())?;
        for entry in entries {
            let entry = entry.map_err(|e| e.to_string())?;
            let path = entry.path();
            if path.is_dir() {
                let manifest_path = path.join("manifest.yaml");
                if manifest_path.exists() {
                    let content =
                        std::fs::read_to_string(&manifest_path).map_err(|e| e.to_string())?;
                    let manifest: ArticleManifest =
                        serde_yaml::from_str(&content).map_err(|e| e.to_string())?;
                    if article_ids.contains(&manifest.id) {
                        articles.push(manifest.to_article(path.to_string_lossy().to_string()));
                    }
                }
            }
        }
    }

    // Mark as publishing
    {
        let mut records = state.publish_records.lock().map_err(|e| e.to_string())?;
        for article in &articles {
            for pid in &platform_ids {
                // Skip if already published
                let already = records.iter().any(|r| {
                    r.article_id == article.id
                        && r.platform_id == *pid
                        && r.status == PublishStatus::Published
                });
                if already {
                    continue;
                }

                // Remove any previous failed/not-published record for this combo
                records.retain(|r| !(r.article_id == article.id && r.platform_id == *pid));

                records.push(PublishRecord {
                    article_id: article.id.clone(),
                    platform_id: pid.clone(),
                    status: PublishStatus::Publishing,
                });
            }
        }
    }

    // Publish
    for article in &articles {
        for pid in &platform_ids {
            if let Some(platform) = platforms.iter().find(|p| p.id() == pid) {
                let result = platform.publish(article);

                let mut records = state.publish_records.lock().map_err(|e| e.to_string())?;
                if let Some(record) = records.iter_mut().find(|r| {
                    r.article_id == article.id
                        && r.platform_id == *pid
                        && r.status == PublishStatus::Publishing
                }) {
                    record.status = match result {
                        Ok(()) => PublishStatus::Published,
                        Err(e) => PublishStatus::Failed(e),
                    };
                }
            }
        }
    }

    Ok(())
}

#[tauri::command]
pub async fn get_publish_records(
    state: tauri::State<'_, AppState>,
) -> Result<Vec<PublishRecord>, String> {
    let records = state.publish_records.lock().map_err(|e| e.to_string())?;
    Ok(records.clone())
}
