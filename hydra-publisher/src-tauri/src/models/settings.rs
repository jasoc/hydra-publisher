use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AppSettings {
    pub catalog_root: String,
    pub ai_host: String,
    pub ai_token: String,
    pub ai_model: String,
    pub language: String,
    pub recent_folders: Vec<String>,
}

impl Default for AppSettings {
    fn default() -> Self {
        let catalog_root = if cfg!(target_os = "windows") {
            dirs_next::desktop_dir()
                .map(|p| p.join("hydra-publisher").to_string_lossy().to_string())
                .unwrap_or_default()
        } else {
            dirs_next::home_dir()
                .map(|p| p.join("hydra-publisher").to_string_lossy().to_string())
                .unwrap_or_default()
        };

        Self {
            catalog_root,
            ai_host: "https://openrouter.ai/api".to_string(),
            ai_token: String::new(),
            ai_model: "gpt-4o".to_string(),
            language: "en".to_string(),
            recent_folders: Vec::new(),
        }
    }
}
