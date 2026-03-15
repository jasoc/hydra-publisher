use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Article {
    pub id: String,
    pub name: String,
    pub description: String,
    pub price: Option<f64>,
    pub photos: Vec<String>,
    pub videos: Vec<String>,
    pub folder_path: String,
    #[serde(default)]
    pub category: Option<String>,
    #[serde(default)]
    pub condition: Option<String>,
}

/// Written to manifest.yaml inside each article folder
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ArticleManifest {
    pub version: u32,
    pub id: String,
    pub name: String,
    pub description: String,
    pub price: Option<f64>,
    pub photos: Vec<String>,
    pub videos: Vec<String>,
    #[serde(default)]
    pub category: Option<String>,
    #[serde(default)]
    pub condition: Option<String>,
}

impl ArticleManifest {
    pub fn new(id: String, name: String, photos: Vec<String>) -> Self {
        Self {
            version: 1,
            id,
            name,
            description: String::new(),
            price: None,
            photos,
            videos: Vec::new(),
            category: None,
            condition: None,
        }
    }

    pub fn to_article(&self, folder_path: String) -> Article {
        Article {
            id: self.id.clone(),
            name: self.name.clone(),
            description: self.description.clone(),
            price: self.price,
            photos: self.photos.clone(),
            videos: self.videos.clone(),
            folder_path,
            category: self.category.clone(),
            condition: self.condition.clone(),
        }
    }
}
