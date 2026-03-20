use std::path::Path;
use std::sync::{Arc, Mutex};
use tauri::{AppHandle, Manager};
use tauri_plugin_store::StoreExt;
use reqwest::header::AUTHORIZATION;
use crate::models::article::ArticleManifest;
use crate::models::platform::{PlatformInfo, Platform, PublishRecord, PublishStatus, TestPlatform};
use crate::models::ebay_platform::EbayPlatform;
use crate::models::python_platform::PythonPlatform;
use crate::models::python_bridge::PythonBridge;
use crate::models::settings::AppSettings;
use crate::state::AppState;

fn get_platforms(
    settings: &AppSettings,
    python_bridge: Arc<Mutex<Option<PythonBridge>>>,
    python_dir: String,
    app_data_dir: String,
) -> Vec<Box<dyn Platform>> {
    vec![
        Box::new(TestPlatform),
        Box::new(EbayPlatform::new(
            settings.ebay_token.clone(),
            if settings.ebay_marketplace_id.is_empty() {
                "EBAY_IT".to_string()
            } else {
                settings.ebay_marketplace_id.clone()
            },
            settings.ebay_fulfillment_policy_id.clone(),
            settings.ebay_payment_policy_id.clone(),
            settings.ebay_return_policy_id.clone(),
            settings.ebay_category_id.clone(),
        )),
        Box::new(PythonPlatform::new(
            "subito".to_string(),
            "Subito.it".to_string(),
            python_bridge.clone(),
            python_dir.clone(),
            app_data_dir.clone(),
        )),
        Box::new(PythonPlatform::new(
            "local_test_selenium".to_string(),
            "Local Test Selenium".to_string(),
            python_bridge,
            python_dir,
            app_data_dir,
        )),
    ]
}

#[tauri::command]
pub fn list_platforms() -> Vec<PlatformInfo> {
    vec![
        PlatformInfo { id: "test".to_string(),                name: "Test Platform".to_string() },
        PlatformInfo { id: "ebay".to_string(),                name: "eBay".to_string() },
        PlatformInfo { id: "subito".to_string(),              name: "Subito.it".to_string() },
        PlatformInfo { id: "local_test_selenium".to_string(), name: "Local Test Selenium".to_string() },
    ]
}

fn resolve_python_dir(app: &AppHandle) -> String {
    app.path()
        .resource_dir()
        .map(|p| p.join("python").to_string_lossy().to_string())
        .unwrap_or_else(|_| "resources/python".to_string())
}

fn resolve_app_data_dir(app: &AppHandle) -> String {
    app.path()
        .app_data_dir()
        .map(|p| p.to_string_lossy().to_string())
        .unwrap_or_else(|_| ".".to_string())
}

/// Persist the current publish records to the store.
fn save_records(app: &AppHandle, state: &AppState) -> Result<(), String> {
    let store = app.store("publish_records.json").map_err(|e| e.to_string())?;
    let records = state.publish_records.lock().map_err(|e| e.to_string())?;
    let value = serde_json::to_value(&*records).map_err(|e| e.to_string())?;
    store.set("records", value);
    store.save().map_err(|e| e.to_string())
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
    let python_dir = resolve_python_dir(&app);
    let app_data_dir = resolve_app_data_dir(&app);
    let platforms = get_platforms(&settings, state.python_bridge.clone(), python_dir, app_data_dir);

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
    save_records(&app, &state)?;

    // Publish
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
    save_records(&app, &state)?;

    Ok(())
}

#[tauri::command]
pub async fn get_publish_records(
    state: tauri::State<'_, AppState>,
) -> Result<Vec<PublishRecord>, String> {
    let records = state.publish_records.lock().map_err(|e| e.to_string())?;
    Ok(records.clone())
}

/// Deletes the eBay offer for a given article SKU and removes the publish record.
/// This allows the user to reset a stuck/broken offer and republish from scratch.
#[tauri::command]
pub async fn delete_ebay_offer(
    state: tauri::State<'_, AppState>,
    app: AppHandle,
    article_id: String,
) -> Result<String, String> {
    let store = app.store("settings.json").map_err(|e| e.to_string())?;
    let settings: AppSettings = match store.get("settings") {
        Some(v) => serde_json::from_value(v.clone()).map_err(|e| e.to_string())?,
        None => AppSettings::default(),
    };

    if settings.ebay_token.is_empty() {
        return Err("eBay token not configured".to_string());
    }

    let token = settings.ebay_token.clone();
    let auth = format!("Bearer {}", token);
    let client = reqwest::Client::new();

    // 1. Find the offerId for this SKU
    let find_url = format!(
        "https://api.ebay.com/sell/inventory/v1/offer?sku={}",
        urlencoding::encode(&article_id)
    );
    let resp = client
        .get(&find_url)
        .header(AUTHORIZATION, &auth)
        .send()
        .await
        .map_err(|e| format!("Find offer failed: {}", e))?;

    let status = resp.status();
    if !status.is_success() && status.as_u16() != 404 {
        let body = resp.text().await.unwrap_or_default();
        return Err(format!("Find offer error (HTTP {}): {}", status, body));
    }

    let offer_id = if status.is_success() {
        let json: serde_json::Value = resp
            .json()
            .await
            .map_err(|e| format!("Parse error: {}", e))?;
        json["offers"]
            .as_array()
            .and_then(|arr| arr.first())
            .and_then(|o| o["offerId"].as_str())
            .map(|s| s.to_string())
    } else {
        None
    };

    // 2. Delete the offer if it exists
    let deleted_offer = if let Some(ref oid) = offer_id {
        let del_url = format!("https://api.ebay.com/sell/inventory/v1/offer/{}", oid);
        let del_resp = client
            .delete(&del_url)
            .header(AUTHORIZATION, &auth)
            .send()
            .await
            .map_err(|e| format!("Delete offer request failed: {}", e))?;

        let del_status = del_resp.status();
        if del_status.is_success() || del_status.as_u16() == 204 {
            println!("[eBay] Offer '{}' deleted OK", oid);
            true
        } else {
            let body = del_resp.text().await.unwrap_or_default();
            return Err(format!("Delete offer failed (HTTP {}): {}", del_status, body));
        }
    } else {
        println!("[eBay] No offer found for SKU '{}' — nothing to delete", article_id);
        false
    };

    // 3. Remove the publish record from state
    {
        let mut records = state.publish_records.lock().map_err(|e| e.to_string())?;
        records.retain(|r| !(r.article_id == article_id && r.platform_id == "ebay"));
    }
    save_records(&app, &state)?;

    let msg = if deleted_offer {
        format!("eBay offer '{}' deleted and record reset. You can now republish.", offer_id.unwrap_or_default())
    } else {
        "No eBay offer found — record reset. You can now republish.".to_string()
    };
    Ok(msg)
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
    let python_dir = resolve_python_dir(&app);
    let app_data_dir = resolve_app_data_dir(&app);
    let platforms = get_platforms(&settings, state.python_bridge.clone(), python_dir, app_data_dir);

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
    save_records(&app, &state)?;

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
    save_records(&app, &state)?;

    Ok(())
}
