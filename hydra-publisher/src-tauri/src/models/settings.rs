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
    #[serde(default)]
    pub ebay_token: String,
    #[serde(default)]
    pub ebay_marketplace_id: String,
    #[serde(default)]
    pub ebay_fulfillment_policy_id: String,
    #[serde(default)]
    pub ebay_payment_policy_id: String,
    #[serde(default)]
    pub ebay_return_policy_id: String,
    #[serde(default)]
    pub ebay_category_id: String,
    #[serde(default)]
    pub fb_email: String,
    #[serde(default)]
    pub fb_password: String,
    #[serde(default = "default_enabled_platforms")]
    pub enabled_platforms: Vec<String>,
}

fn default_enabled_platforms() -> Vec<String> {
    vec!["test".to_string(), "facebook_marketplace".to_string()]
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
            ebay_token: String::new(),
            ebay_marketplace_id: "EBAY_IT".to_string(),
            ebay_fulfillment_policy_id: String::new(),
            ebay_payment_policy_id: String::new(),
            ebay_return_policy_id: String::new(),
            ebay_category_id: String::new(),
            fb_email: String::new(),
            fb_password: String::new(),
            enabled_platforms: default_enabled_platforms(),
        }
    }
}
