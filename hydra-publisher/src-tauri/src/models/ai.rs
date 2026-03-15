use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AiRequest {
    pub id: String,
    pub article_id: String,
    pub article_name: String,
    pub description: String,
    pub status: AiRequestStatus,
    pub photo_count: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum AiRequestStatus {
    Pending,
    InProgress,
    Completed,
    Failed(String),
}
