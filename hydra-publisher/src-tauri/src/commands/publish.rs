use std::path::Path;
use std::sync::{Arc, Mutex};
use std::collections::{HashMap, HashSet};
use tauri::{AppHandle, Manager};
use tauri_plugin_store::StoreExt;
use serde::Deserialize;
use crate::models::article::ArticleManifest;
use crate::models::platform::{PlatformInfo, Platform, PublishRecord, PublishStatus};
use crate::models::python_platform::PythonPlatform;
use crate::models::python_bridge::PythonBridge;
use crate::models::settings::AppSettings;
use crate::state::AppState;

fn get_platforms(
    _settings: &AppSettings,
    python_bridge: Arc<Mutex<Option<PythonBridge>>>,
    python_dir: String,
    app_data_dir: String,
) -> Vec<Box<dyn Platform>> {
    let make = |id: &str, name: &str| -> Box<dyn Platform> {
        Box::new(PythonPlatform::new(
            id.to_string(),
            name.to_string(),
            python_bridge.clone(),
            python_dir.clone(),
            app_data_dir.clone(),
        ))
    };
    vec![
        make("subito", "Subito.it"),
        make("facebook_marketplace", "Facebook Marketplace"),
        make("vinted", "Vinted"),
    ]
}

#[tauri::command]
pub fn list_platforms() -> Vec<PlatformInfo> {
    vec![
        PlatformInfo { id: "subito".to_string(),               name: "Subito.it".to_string() },
        PlatformInfo { id: "facebook_marketplace".to_string(), name: "Facebook Marketplace".to_string() },
        PlatformInfo { id: "vinted".to_string(),               name: "Vinted".to_string() },
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

/// Persist publish records using only an AppHandle (for spawned tasks).
fn save_records_from_handle(app: &AppHandle) -> Result<(), String> {
    let state = app.state::<AppState>();
    save_records(app, &state)
}

/// Ensure the Python bridge is running and return a reference to it.
fn ensure_bridge(
    state: &AppState,
    app: &AppHandle,
) -> Result<(), String> {
    let python_dir = resolve_python_dir(app);
    let app_data_dir = resolve_app_data_dir(app);
    let mut guard = state.python_bridge.lock().map_err(|e| format!("Mutex poisoned: {e}"))?;
    if guard.is_none() {
        *guard = Some(PythonBridge::start(&python_dir, &app_data_dir)?);
    }
    Ok(())
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PublishTargetInput {
    pub article_id: String,
    pub platform_id: String,
}

#[tauri::command]
pub async fn open_provider_session(
    state: tauri::State<'_, AppState>,
    app: AppHandle,
    provider_id: String,
) -> Result<serde_json::Value, String> {
    ensure_bridge(&state, &app)?;
    let body = serde_json::json!({});
    let bridge = state.python_bridge.clone();
    tokio::task::block_in_place(move || {
        let guard = bridge.lock().map_err(|e| format!("Mutex poisoned: {e}"))?;
        guard
            .as_ref()
            .expect("bridge was just started")
            .call_json(&provider_id, "login", &body)
    })
}

#[tauri::command]
pub async fn publish_articles(
    state: tauri::State<'_, AppState>,
    app: AppHandle,
    targets: Vec<PublishTargetInput>,
) -> Result<(), String> {
    if targets.is_empty() {
        return Err("No publish targets provided".to_string());
    }

    let store = app.store("settings.json").map_err(|e| e.to_string())?;
    let settings: AppSettings = match store.get("settings") {
        Some(value) => serde_json::from_value(value.clone()).map_err(|e| e.to_string())?,
        None => AppSettings::default(),
    };

    let root = Path::new(&settings.catalog_root);
    let python_dir = resolve_python_dir(&app);
    let app_data_dir = resolve_app_data_dir(&app);
    let platforms = get_platforms(&settings, state.python_bridge.clone(), python_dir, app_data_dir);
    let article_id_set: HashSet<String> = targets.iter().map(|t| t.article_id.clone()).collect();

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
                    if article_id_set.contains(&manifest.id) {
                        articles.push(manifest.to_article(path.to_string_lossy().to_string()));
                    }
                }
            }
        }
    }
    let articles_by_id: HashMap<String, crate::models::article::Article> = articles
        .into_iter()
        .map(|a| (a.id.clone(), a))
        .collect();

    // Mark all targets as publishing
    {
        let mut records = state.publish_records.lock().map_err(|e| e.to_string())?;
        for target in &targets {
            records.retain(|r| {
                !(r.article_id == target.article_id && r.platform_id == target.platform_id)
            });
            records.push(PublishRecord {
                article_id: target.article_id.clone(),
                platform_id: target.platform_id.clone(),
                status: PublishStatus::Publishing,
            });
        }
    }
    save_records(&app, &state)?;

    // Publish all targets concurrently — the Python server's Chrome pool
    // handles parallelism (up to HYDRA_POOL_SIZE windows).
    let platforms = Arc::new(platforms);
    let articles_by_id = Arc::new(articles_by_id);

    let mut handles = Vec::new();
    for target in &targets {
        let article_id = target.article_id.clone();
        let platform_id = target.platform_id.clone();
        let platforms = Arc::clone(&platforms);
        let article = articles_by_id.get(&target.article_id).cloned();
        let app_handle = app.clone();

        let handle = tokio::task::spawn_blocking(move || {
            let result = if let Some(ref article) = article {
                if let Some(platform) = platforms.iter().find(|p| p.id() == platform_id) {
                    platform.publish(article)
                } else {
                    Err(format!("Unknown platform '{}'", platform_id))
                }
            } else {
                Err(format!("Article '{}' not found in catalog", article_id))
            };

            // Update the record immediately so the UI can poll progress
            let st = app_handle.state::<AppState>();
            if let Ok(mut records) = st.publish_records.lock() {
                if let Some(record) = records.iter_mut().find(|r| {
                    r.article_id == article_id
                        && r.platform_id == platform_id
                        && r.status == PublishStatus::Publishing
                }) {
                    record.status = match result {
                        Ok(()) => PublishStatus::Published,
                        Err(e) => PublishStatus::Failed(e),
                    };
                }
            }
            // Best-effort save after each result
            let _ = save_records_from_handle(&app_handle);
        });
        handles.push(handle);
    }

    // Wait for all publish tasks to complete
    for handle in handles {
        let _ = handle.await;
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

/// Force-reset a stuck task (Publishing / AwaitingLogin) to Failed.
/// Lets the user unblock a record that will never complete on its own.
#[tauri::command]
pub async fn force_reset_task(
    state: tauri::State<'_, AppState>,
    app: AppHandle,
    article_id: String,
    platform_id: String,
) -> Result<(), String> {
    let mut records = state.publish_records.lock().map_err(|e| e.to_string())?;
    if let Some(record) = records.iter_mut().find(|r| {
        r.article_id == article_id && r.platform_id == platform_id
    }) {
        match &record.status {
            PublishStatus::Publishing
            | PublishStatus::AwaitingLogin => {
                record.status = PublishStatus::Failed("Force reset by user".to_string());
            }
            _ => {}
        }
    }
    drop(records);
    save_records(&app, &state)
}

/// Return the list of provider IDs that currently have an active Selenium session.
#[tauri::command]
pub async fn get_active_sessions(
    state: tauri::State<'_, AppState>,
    app: AppHandle,
) -> Result<Vec<String>, String> {
    ensure_bridge(&state, &app)?;
    let bridge = state.python_bridge.clone();
    tokio::task::block_in_place(move || {
        let guard = bridge.lock().map_err(|e| format!("Mutex poisoned: {e}"))?;
        guard.as_ref().expect("bridge was just started").get_sessions()
    })
}

/// Kill the Selenium browser session for `provider_id`.
#[tauri::command]
pub async fn kill_session(
    state: tauri::State<'_, AppState>,
    app: AppHandle,
    provider_id: String,
) -> Result<(), String> {
    ensure_bridge(&state, &app)?;
    let bridge = state.python_bridge.clone();
    tokio::task::block_in_place(move || {
        let guard = bridge.lock().map_err(|e| format!("Mutex poisoned: {e}"))?;
        guard.as_ref().expect("bridge was just started").kill_session(&provider_id)
    })
}

/// Retry a failed publish record — removes the old record and republishes.
#[tauri::command]
pub async fn retry_publish(
    state: tauri::State<'_, AppState>,
    app: AppHandle,
    article_id: String,
    platform_id: String,
) -> Result<(), String> {
    {
        let mut records = state.publish_records.lock().map_err(|e| e.to_string())?;
        records.retain(|r| !(r.article_id == article_id && r.platform_id == platform_id));
    }
    save_records(&app, &state)?;

    publish_articles(
        state,
        app,
        vec![PublishTargetInput {
            article_id,
            platform_id,
        }],
    )
    .await
}
