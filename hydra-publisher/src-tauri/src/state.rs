use std::sync::{Arc, Mutex};
use crate::models::ai::AiRequest;
use crate::models::platform::PublishRecord;
use crate::models::python_bridge::PythonBridge;

pub struct AppState {
    pub ai_requests: Mutex<Vec<AiRequest>>,
    pub publish_records: Mutex<Vec<PublishRecord>>,
    pub article_counter: Mutex<u32>,
    /// Shared Python server process; started lazily on the first Python-backed
    /// platform call and kept alive until the process exits.
    pub python_bridge: Arc<Mutex<Option<PythonBridge>>>,
}

impl Default for AppState {
    fn default() -> Self {
        Self {
            ai_requests: Mutex::new(Vec::new()),
            publish_records: Mutex::new(Vec::new()),
            article_counter: Mutex::new(0),
            python_bridge: Arc::new(Mutex::new(None)),
        }
    }
}
