use std::sync::Mutex;
use crate::models::ai::AiRequest;
use crate::models::platform::PublishRecord;

pub struct AppState {
    pub ai_requests: Mutex<Vec<AiRequest>>,
    pub publish_records: Mutex<Vec<PublishRecord>>,
    pub article_counter: Mutex<u32>,
}

impl Default for AppState {
    fn default() -> Self {
        Self {
            ai_requests: Mutex::new(Vec::new()),
            publish_records: Mutex::new(Vec::new()),
            article_counter: Mutex::new(0),
        }
    }
}
