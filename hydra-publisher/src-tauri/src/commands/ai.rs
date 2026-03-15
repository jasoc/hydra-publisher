use std::path::Path;
use base64::Engine;
use base64::engine::general_purpose::STANDARD as BASE64;
use tauri::{AppHandle, Manager};
use tauri_plugin_store::StoreExt;
use crate::models::ai::{AiRequest, AiRequestStatus};
use crate::models::article::ArticleManifest;
use crate::models::settings::AppSettings;
use crate::state::AppState;

const IMAGE_EXTENSIONS: &[&str] = &["jpg", "jpeg", "png", "webp", "heic", "bmp", "gif"];

#[tauri::command]
pub async fn start_ai_fill(
    state: tauri::State<'_, AppState>,
    app: AppHandle,
    article_ids: Vec<String>,
) -> Result<Vec<String>, String> {
    // Load settings
    let store = app.store("settings.json").map_err(|e| e.to_string())?;
    let settings: AppSettings = match store.get("settings") {
        Some(value) => serde_json::from_value(value.clone()).map_err(|e| e.to_string())?,
        None => AppSettings::default(),
    };

    if settings.ai_token.is_empty() {
        return Err("AI token not configured. Please set it in Settings.".to_string());
    }

    let catalog_root = &settings.catalog_root;
    let mut request_ids = Vec::new();

    // Scan catalog for matching articles
    let root = Path::new(catalog_root);
    if !root.exists() {
        return Err("Catalog root does not exist".to_string());
    }

    let entries = std::fs::read_dir(root).map_err(|e| e.to_string())?;
    let mut articles_to_process = Vec::new();

    for entry in entries {
        let entry = entry.map_err(|e| e.to_string())?;
        let path = entry.path();
        if path.is_dir() {
            let manifest_path = path.join("manifest.yaml");
            if manifest_path.exists() {
                let content = std::fs::read_to_string(&manifest_path).map_err(|e| e.to_string())?;
                let manifest: ArticleManifest =
                    serde_yaml::from_str(&content).map_err(|e| e.to_string())?;

                if article_ids.contains(&manifest.id) {
                    // Check if article needs AI fill (missing name or description or price)
                    let needs_name = manifest.name.starts_with("Article ");
                    let needs_desc = manifest.description.is_empty();
                    let needs_price = manifest.price.is_none() || manifest.price == Some(0.0);

                    if needs_name || needs_desc || needs_price {
                        articles_to_process.push((manifest, path.to_string_lossy().to_string()));
                    }
                }
            }
        }
    }

    // Create AI requests and spawn processing tasks
    for (manifest, folder_path) in articles_to_process {
        let request_id = uuid::Uuid::new_v4().to_string();
        let photo_count = manifest.photos.len();

        // Build description of what fields are missing
        let mut missing = Vec::new();
        if manifest.name.starts_with("Article ") {
            missing.push("name");
        }
        if manifest.description.is_empty() {
            missing.push("description");
        }
        if manifest.price.is_none() || manifest.price == Some(0.0) {
            missing.push("price");
        }

        let description = format!(
            "Determining {} for {} photos of {}",
            missing.join(", "),
            photo_count,
            manifest.name
        );

        let ai_request = AiRequest {
            id: request_id.clone(),
            article_id: manifest.id.clone(),
            article_name: manifest.name.clone(),
            description,
            status: AiRequestStatus::Pending,
            photo_count,
        };

        {
            let mut requests = state.ai_requests.lock().map_err(|e| e.to_string())?;
            requests.push(ai_request);
        }

        request_ids.push(request_id.clone());

        // Clone what we need for the spawned task
        let settings = settings.clone();
        let request_id_clone = request_id;

        // Spawn async task for AI processing
        let app_clone = app.clone();
        tokio::spawn(async move {
            let state = app_clone.state::<AppState>();
            process_ai_request(
                &state,
                &settings,
                &request_id_clone,
                &manifest,
                &folder_path,
            )
            .await;
        });
    }

    Ok(request_ids)
}

async fn process_ai_request(
    state: &AppState,
    settings: &AppSettings,
    request_id: &str,
    manifest: &ArticleManifest,
    folder_path: &str,
) {
    // Mark as in progress
    if let Ok(mut requests) = state.ai_requests.lock() {
        if let Some(req) = requests.iter_mut().find(|r| r.id == request_id) {
            req.status = AiRequestStatus::InProgress;
        }
    }

    // Collect image data
    let folder = Path::new(folder_path);
    let mut image_contents: Vec<(String, String)> = Vec::new(); // (mime, base64)

    for photo in &manifest.photos {
        let photo_path = folder.join(photo);
        if photo_path.exists() {
            let ext = photo_path
                .extension()
                .and_then(|e| e.to_str())
                .unwrap_or("jpg")
                .to_lowercase();

            if IMAGE_EXTENSIONS.contains(&ext.as_str()) {
                if let Ok(data) = std::fs::read(&photo_path) {
                    let mime = match ext.as_str() {
                        "png" => "image/png",
                        "webp" => "image/webp",
                        "gif" => "image/gif",
                        "bmp" => "image/bmp",
                        _ => "image/jpeg",
                    };
                    let b64 = BASE64.encode(&data);
                    image_contents.push((mime.to_string(), b64));
                }
            }
        }
    }

    if image_contents.is_empty() {
        if let Ok(mut requests) = state.ai_requests.lock() {
            if let Some(req) = requests.iter_mut().find(|r| r.id == request_id) {
                req.status = AiRequestStatus::Failed("No images found".to_string());
            }
        }
        return;
    }

    // Build missing fields info
    let needs_name = manifest.name.starts_with("Article ");
    let needs_desc = manifest.description.is_empty();
    let needs_price = manifest.price.is_none() || manifest.price == Some(0.0);

    let prompt = format!(
        "You are helping list a used item for sale on an online marketplace. \
         Look at the photos and provide the following fields that are currently missing: \
         {}{}{}. \
         Respond in {}. Return ONLY a JSON object with these keys (include all three even if some already exist): \
         {{\"name\": \"short product name\", \"description\": \"marketplace listing description\", \"price\": 0.00}}",
        if needs_name { "name, " } else { "" },
        if needs_desc { "description, " } else { "" },
        if needs_price { "price" } else { "" },
        settings.language
    );

    // Build API request
    let mut content = vec![serde_json::json!({
        "type": "text",
        "text": prompt
    })];

    for (mime, b64) in &image_contents {
        content.push(serde_json::json!({
            "type": "image_url",
            "image_url": {
                "url": format!("data:{};base64,{}", mime, b64)
            }
        }));
    }

    let payload = serde_json::json!({
        "model": settings.ai_model,
        "messages": [{
            "role": "user",
            "content": content
        }],
        "max_tokens": 500
    });

    let api_url = format!("{}/v1/chat/completions", settings.ai_host.trim_end_matches('/'));

    let client = reqwest::Client::new();
    let result = client
        .post(&api_url)
        .header("Authorization", format!("Bearer {}", settings.ai_token))
        .header("Content-Type", "application/json")
        .json(&payload)
        .send()
        .await;

    match result {
        Ok(response) => {
            if !response.status().is_success() {
                let status = response.status();
                let body = response.text().await.unwrap_or_default();
                if let Ok(mut requests) = state.ai_requests.lock() {
                    if let Some(req) = requests.iter_mut().find(|r| r.id == request_id) {
                        req.status = AiRequestStatus::Failed(
                            format!("API error {}: {}", status, body),
                        );
                    }
                }
                return;
            }

            match response.json::<serde_json::Value>().await {
                Ok(json) => {
                    // Extract content from OpenAI response
                    let content_str = json["choices"][0]["message"]["content"]
                        .as_str()
                        .unwrap_or("");

                    // Try to parse JSON from the response (may have markdown wrapping)
                    let json_str = extract_json(content_str);

                    match serde_json::from_str::<serde_json::Value>(&json_str) {
                        Ok(parsed) => {
                            // Update manifest
                            let manifest_path = Path::new(folder_path).join("manifest.yaml");
                            if let Ok(content) = std::fs::read_to_string(&manifest_path) {
                                if let Ok(mut m) = serde_yaml::from_str::<ArticleManifest>(&content) {
                                    if needs_name {
                                        if let Some(name) = parsed["name"].as_str() {
                                            m.name = name.to_string();
                                        }
                                    }
                                    if needs_desc {
                                        if let Some(desc) = parsed["description"].as_str() {
                                            m.description = desc.to_string();
                                        }
                                    }
                                    if needs_price {
                                        if let Some(price) = parsed["price"].as_f64() {
                                            m.price = Some(price);
                                        }
                                    }

                                    if let Ok(yaml) = serde_yaml::to_string(&m) {
                                        let _ = std::fs::write(&manifest_path, yaml);
                                    }
                                }
                            }

                            if let Ok(mut requests) = state.ai_requests.lock() {
                                if let Some(req) = requests.iter_mut().find(|r| r.id == request_id) {
                                    req.status = AiRequestStatus::Completed;
                                }
                            }
                        }
                        Err(e) => {
                            if let Ok(mut requests) = state.ai_requests.lock() {
                                if let Some(req) = requests.iter_mut().find(|r| r.id == request_id) {
                                    req.status = AiRequestStatus::Failed(
                                        format!("Failed to parse AI response: {}", e),
                                    );
                                }
                            }
                        }
                    }
                }
                Err(e) => {
                    if let Ok(mut requests) = state.ai_requests.lock() {
                        if let Some(req) = requests.iter_mut().find(|r| r.id == request_id) {
                            req.status =
                                AiRequestStatus::Failed(format!("Failed to read response: {}", e));
                        }
                    }
                }
            }
        }
        Err(e) => {
            if let Ok(mut requests) = state.ai_requests.lock() {
                if let Some(req) = requests.iter_mut().find(|r| r.id == request_id) {
                    req.status = AiRequestStatus::Failed(format!("Request failed: {}", e));
                }
            }
        }
    }
}

fn extract_json(text: &str) -> String {
    // Try to extract JSON from markdown code blocks or raw text
    let trimmed = text.trim();

    // Check for ```json ... ``` blocks
    if let Some(start) = trimmed.find("```json") {
        let after = &trimmed[start + 7..];
        if let Some(end) = after.find("```") {
            return after[..end].trim().to_string();
        }
    }

    // Check for ``` ... ``` blocks
    if let Some(start) = trimmed.find("```") {
        let after = &trimmed[start + 3..];
        if let Some(end) = after.find("```") {
            return after[..end].trim().to_string();
        }
    }

    // Check for { ... } in the text
    if let Some(start) = trimmed.find('{') {
        if let Some(end) = trimmed.rfind('}') {
            return trimmed[start..=end].to_string();
        }
    }

    trimmed.to_string()
}

#[tauri::command]
pub async fn get_ai_requests(
    state: tauri::State<'_, AppState>,
) -> Result<Vec<AiRequest>, String> {
    let requests = state.ai_requests.lock().map_err(|e| e.to_string())?;
    Ok(requests.clone())
}
