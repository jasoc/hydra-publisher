use serde::{Deserialize, Serialize};
use crate::models::article::Article;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PlatformInfo {
    pub id: String,
    pub name: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PublishRecord {
    pub article_id: String,
    pub platform_id: String,
    pub status: PublishStatus,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum PublishStatus {
    NotPublished,
    Publishing,
    Published,
    Failed(String),
}

pub trait Platform: Send + Sync {
    fn id(&self) -> &str;
    fn name(&self) -> &str;
    fn publish(&self, article: &Article) -> Result<(), String>;
}

pub struct TestPlatform;

impl Platform for TestPlatform {
    fn id(&self) -> &str {
        "test"
    }

    fn name(&self) -> &str {
        "Test Platform"
    }

    fn publish(&self, article: &Article) -> Result<(), String> {
        println!(
            "[TestPlatform] Publishing article: {} (id: {}), {} photos",
            article.name,
            article.id,
            article.photos.len()
        );
        Ok(())
    }
}
