use std::path::Path;
use tauri::AppHandle;
use tauri_plugin_store::StoreExt;
use crate::models::article::ArticleManifest;
use crate::models::platform::{PlatformInfo, Platform, PublishRecord, PublishStatus, TestPlatform};
use crate::models::ebay_platform::EbayPlatform;
use crate::models::settings::AppSettings;
use crate::state::AppState;

fn get_platforms(settings: &AppSettings) -> Vec<Box<dyn Platform>> {
    vec![
        Box::new(TestPlatform),
        Box::new(EbayPlatform::new(
            settings.ebay_token.clone(),
            "EBAY_IT".to_string(),
        )),
    ]
}

#[tauri::command]
pub fn list_platforms() -> Vec<PlatformInfo> {
    // List all supported platforms; token configuration is checked at publish time
    let dummy = AppSettings::default();
    get_platforms(&dummy)
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
    let store = app.store("settings.json").map_err(|e| e.to_string())?;
    let settings: AppSettings = match store.get("settings") {
        Some(value) => serde_json::from_value(value.clone()).map_err(|e| e.to_string())?,
        None => AppSettings::default(),
    };

    let root = Path::new(&settings.catalog_root);
    let platforms = get_platforms(&settings);

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
                let already = records.iter().any(|r| {
                    r.article_id == article.id
                        && r.platform_id == *pid
                        && r.status == PublishStatus::Published
                });
                if already {
                    continue;
                }
                records.retain(|r| !(r.article_id == article.id && r.platform_id == *pid));
                records.push(PublishRecord {
                    article_id: article.id.clone(),
                    platform_id: pid.clone(),
                    status: PublishStatus::Publishing,
                });
            }
        }
    }

    // Publish (block_in_place allows blocking HTTP from async context)
    for article in &articles {
        for pid in &platform_ids {
            if let Some(platform) = platforms.iter().find(|p| p.id() == pid) {
                let result = tokio::task::block_in_place(|| platform.publish(article));

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

#[tauri::command]
pub async fn update_articles(
    state: tauri::State<'_, AppState>,
    app: AppHandle,
    article_ids: Vec<String>,
    platform_ids: Vec<String>,
) -> Result<(), String> {
    let store = app.store("settings.json").map_err(|e| e.to_string())?;
    let settings: AppSettings = match store.get("settings") {
        Some(value) => serde_json::from_value(value.clone()).map_err(|e| e.to_string())?,
        None => AppSettings::default(),
    };

    let root = Path::new(&settings.catalog_root);
    let platforms = get_platforms(&settings);

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

    // Mark as updating
    {
        let mut records = state.publish_records.lock().map_err(|e| e.to_string())?;
        for article in &articles {
            for pid in &platform_ids {
                records.retain(|r| !(r.article_id == article.id && r.platform_id == *pid));
                records.push(PublishRecord {
                    article_id: article.id.clone(),
                    platform_id: pid.clone(),
                    status: PublishStatus::Updating,
                });
            }
        }
    }

    // Call update (block_in_place allows blocking HTTP from async context)
    for article in &articles {
        for pid in &platform_ids {
            if let Some(platform) = platforms.iter().find(|p| p.id() == pid) {
                let result = tokio::task::block_in_place(|| platform.update(article));

                let mut records = state.publish_records.lock().map_err(|e| e.to_string())?;
                if let Some(record) = records.iter_mut().find(|r| {
                    r.article_id == article.id
                        && r.platform_id == *pid
                        && r.status == PublishStatus::Updating
                }) {
                    record.status = match result {
                        Ok(()) => PublishStatus::Updated,
                        Err(e) => PublishStatus::UpdateFailed(e),
                    };
                }
            }
        }
    }

    Ok(())
}
