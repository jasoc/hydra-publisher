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
                    // Check if article needs AI fill (missing name, description, price, category, or condition)
                    let needs_name = manifest.name.starts_with("Article ");
                    let needs_desc = manifest.description.is_empty();
                    let needs_price = manifest.price.is_none() || manifest.price == Some(0.0);
                    let needs_category = manifest.category.as_ref().map_or(true, |c| c.is_empty());
                    let needs_condition = manifest.condition.as_ref().map_or(true, |c| c.is_empty());

                    if needs_name || needs_desc || needs_price || needs_category || needs_condition {
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
        if manifest.category.as_ref().map_or(true, |c| c.is_empty()) {
            missing.push("category");
        }
        if manifest.condition.as_ref().map_or(true, |c| c.is_empty()) {
            missing.push("condition");
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
            prompt: String::new(),
            raw_response: String::new(),
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
    let needs_category = manifest.category.as_ref().map_or(true, |c| c.is_empty());
    let needs_condition = manifest.condition.as_ref().map_or(true, |c| c.is_empty());

    let language_name = match settings.language.as_str() {
        "it" => "Italian",
        "fr" => "French",
        "de" => "German",
        "es" => "Spanish",
        "pt" => "Portuguese",
        _ => "English",
    };

    let prompt = format!(
        "You are helping list a used item for sale on an online marketplace. \
         Look at the photos and provide the following fields that are currently missing: \
         {}{}{}{}{}. \
         Respond in {}. \
         For \"category\", pick EXACTLY one from this list: \
         [\"Attrezzi\", \"Arredamento\", \"Articoli per la casa\", \"Giardino\", \"Elettrodomestici\", \
         \"Videogiochi\", \"Libri, film e musica\", \"Borse e valigie\", \
         \"Abbigliamento e scarpe da donna\", \"Abbigliamento e scarpe da uomo\", \
         \"Gioielli e accessori\", \"Salute e bellezza\", \"Articoli per animali\", \
         \"Neonati e bambini\", \"Giocattoli e videogiochi\", \"Elettronica e computer\", \
         \"Cellulari\", \"Biciclette\", \"Arte e artigianato\", \
         \"Sport e attività all'aperto\", \"Ricambi auto\", \"Strumenti musicali\", \
         \"Articoli d'antiquariato e da collezione\", \"Mercatino dell'usato\", \"Varie\", \"Veicoli\"]. \
         For \"condition\", pick EXACTLY one from: \
         [\"Nuovo\", \"Usato - Come nuovo\", \"Usato - Buono\", \"Usato - Accettabile\"]. \
         Return ONLY a JSON object with these keys (include all even if some already exist): \
         {{\"name\": \"short product name\", \"description\": \"marketplace listing description\", \
         \"price\": 0.00, \"category\": \"exact category from list\", \"condition\": \"exact condition from list\"}}",
        if needs_name { "name, " } else { "" },
        if needs_desc { "description, " } else { "" },
        if needs_price { "price, " } else { "" },
        if needs_category { "category, " } else { "" },
        if needs_condition { "condition" } else { "" },
        language_name
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

    // Store the prompt in the request for debugging
    if let Ok(mut requests) = state.ai_requests.lock() {
        if let Some(req) = requests.iter_mut().find(|r| r.id == request_id) {
            req.prompt = format!(
                "{}\n\n[{} image(s) attached]\nModel: {}\nEndpoint: {}",
                prompt,
                image_contents.len(),
                settings.ai_model,
                api_url
            );
        }
    }

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

                    // Store the raw response for debugging
                    if let Ok(mut requests) = state.ai_requests.lock() {
                        if let Some(req) = requests.iter_mut().find(|r| r.id == request_id) {
                            req.raw_response = content_str.to_string();
                        }
                    }

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
                                    if needs_category {
                                        if let Some(cat) = parsed["category"].as_str() {
                                            m.category = Some(cat.to_string());
                                        }
                                    }
                                    if needs_condition {
                                        if let Some(cond) = parsed["condition"].as_str() {
                                            m.condition = Some(cond.to_string());
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
                    // Store raw body for debugging when JSON parsing of the whole response fails
                    if let Ok(mut requests) = state.ai_requests.lock() {
                        if let Some(req) = requests.iter_mut().find(|r| r.id == request_id) {
                            req.raw_response = format!("(response was not valid JSON: {})", e);
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

#[tauri::command]
pub async fn regenerate_article_fields(
    state: tauri::State<'_, AppState>,
    app: AppHandle,
    article_id: String,
    folder_path: String,
) -> Result<String, String> {
    let store = app.store("settings.json").map_err(|e| e.to_string())?;
    let settings: AppSettings = match store.get("settings") {
        Some(value) => serde_json::from_value(value.clone()).map_err(|e| e.to_string())?,
        None => AppSettings::default(),
    };

    if settings.ai_token.is_empty() {
        return Err("AI token not configured. Please set it in Settings.".to_string());
    }

    let manifest_path = Path::new(&folder_path).join("manifest.yaml");
    if !manifest_path.exists() {
        return Err("Article manifest not found".to_string());
    }

    let content = std::fs::read_to_string(&manifest_path).map_err(|e| e.to_string())?;
    let manifest: ArticleManifest = serde_yaml::from_str(&content).map_err(|e| e.to_string())?;

    let request_id = uuid::Uuid::new_v4().to_string();
    let photo_count = manifest.photos.len();

    let ai_request = AiRequest {
        id: request_id.clone(),
        article_id: article_id.clone(),
        article_name: manifest.name.clone(),
        description: format!("Regenerating all fields for {} ({} photos)", manifest.name, photo_count),
        status: AiRequestStatus::Pending,
        photo_count,
        prompt: String::new(),
        raw_response: String::new(),
    };

    {
        let mut requests = state.ai_requests.lock().map_err(|e| e.to_string())?;
        requests.push(ai_request);
    }

    let app_clone = app.clone();
    let request_id_clone = request_id.clone();
    tokio::spawn(async move {
        let state = app_clone.state::<AppState>();
        process_regenerate(&state, &settings, &request_id_clone, &manifest, &folder_path).await;
    });

    Ok(request_id)
}

async fn process_regenerate(
    state: &AppState,
    settings: &AppSettings,
    request_id: &str,
    manifest: &ArticleManifest,
    folder_path: &str,
) {
    // Reuse the same processing but force all fields
    if let Ok(mut requests) = state.ai_requests.lock() {
        if let Some(req) = requests.iter_mut().find(|r| r.id == request_id) {
            req.status = AiRequestStatus::InProgress;
        }
    }

    let folder = Path::new(folder_path);
    let mut image_contents: Vec<(String, String)> = Vec::new();

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

    let language_name = match settings.language.as_str() {
        "it" => "Italian",
        "fr" => "French",
        "de" => "German",
        "es" => "Spanish",
        "pt" => "Portuguese",
        _ => "English",
    };

    let prompt = format!(
        "You are helping list a used item for sale on an online marketplace. \
         Look at the photos and provide: name, description, price, category, condition. \
         Respond in {}. \
         For \"category\", pick EXACTLY one from this list: \
         [\"Attrezzi\", \"Arredamento\", \"Articoli per la casa\", \"Giardino\", \"Elettrodomestici\", \
         \"Videogiochi\", \"Libri, film e musica\", \"Borse e valigie\", \
         \"Abbigliamento e scarpe da donna\", \"Abbigliamento e scarpe da uomo\", \
         \"Gioielli e accessori\", \"Salute e bellezza\", \"Articoli per animali\", \
         \"Neonati e bambini\", \"Giocattoli e videogiochi\", \"Elettronica e computer\", \
         \"Cellulari\", \"Biciclette\", \"Arte e artigianato\", \
         \"Sport e attività all'aperto\", \"Ricambi auto\", \"Strumenti musicali\", \
         \"Articoli d'antiquariato e da collezione\", \"Mercatino dell'usato\", \"Varie\", \"Veicoli\"]. \
         For \"condition\", pick EXACTLY one from: \
         [\"Nuovo\", \"Usato - Come nuovo\", \"Usato - Buono\", \"Usato - Accettabile\"]. \
         Return ONLY a JSON object with these keys: \
         {{\"name\": \"short product name\", \"description\": \"marketplace listing description\", \
         \"price\": 0.00, \"category\": \"exact category from list\", \"condition\": \"exact condition from list\"}}",
        language_name
    );

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

    if let Ok(mut requests) = state.ai_requests.lock() {
        if let Some(req) = requests.iter_mut().find(|r| r.id == request_id) {
            req.prompt = format!(
                "{}\n\n[{} image(s) attached]\nModel: {}\nEndpoint: {}",
                prompt, image_contents.len(), settings.ai_model, api_url
            );
        }
    }

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
                        req.status = AiRequestStatus::Failed(format!("API error {}: {}", status, body));
                    }
                }
                return;
            }

            match response.json::<serde_json::Value>().await {
                Ok(json) => {
                    let content_str = json["choices"][0]["message"]["content"]
                        .as_str()
                        .unwrap_or("");

                    if let Ok(mut requests) = state.ai_requests.lock() {
                        if let Some(req) = requests.iter_mut().find(|r| r.id == request_id) {
                            req.raw_response = content_str.to_string();
                        }
                    }

                    let json_str = extract_json(content_str);

                    match serde_json::from_str::<serde_json::Value>(&json_str) {
                        Ok(parsed) => {
                            let manifest_path = Path::new(folder_path).join("manifest.yaml");
                            if let Ok(content) = std::fs::read_to_string(&manifest_path) {
                                if let Ok(mut m) = serde_yaml::from_str::<ArticleManifest>(&content) {
                                    if let Some(name) = parsed["name"].as_str() {
                                        m.name = name.to_string();
                                    }
                                    if let Some(desc) = parsed["description"].as_str() {
                                        m.description = desc.to_string();
                                    }
                                    if let Some(price) = parsed["price"].as_f64() {
                                        m.price = Some(price);
                                    }
                                    if let Some(cat) = parsed["category"].as_str() {
                                        m.category = Some(cat.to_string());
                                    }
                                    if let Some(cond) = parsed["condition"].as_str() {
                                        m.condition = Some(cond.to_string());
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
                            req.raw_response = format!("(response was not valid JSON: {})", e);
                            req.status = AiRequestStatus::Failed(format!("Failed to read response: {}", e));
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
