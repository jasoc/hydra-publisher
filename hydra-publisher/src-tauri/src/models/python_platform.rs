use std::sync::{Arc, Mutex};
use crate::models::article::Article;
use crate::models::platform::Platform;
use crate::models::python_bridge::PythonBridge;

/// Generic wrapper for any Python-backed provider.
///
/// Adding a new Python provider requires only:
///  1. A new `<id>.py` in `resources/python/providers/`
///  2. Registration in `server.py`'s PROVIDERS dict
///  3. A `PythonPlatform::new(id, name, ...)` entry in `get_platforms()`
pub struct PythonPlatform {
    platform_id: String,
    platform_name: String,
    bridge: Arc<Mutex<Option<PythonBridge>>>,
    python_dir: String,
    app_data_dir: String,
}

impl PythonPlatform {
    pub fn new(
        platform_id: String,
        platform_name: String,
        bridge: Arc<Mutex<Option<PythonBridge>>>,
        python_dir: String,
        app_data_dir: String,
    ) -> Self {
        Self {
            platform_id,
            platform_name,
            bridge,
            python_dir,
            app_data_dir,
        }
    }

    fn ensure_bridge(&self) -> Result<(), String> {
        let mut guard = self
            .bridge
            .lock()
            .map_err(|e| format!("Python bridge mutex poisoned: {e}"))?;
        if guard.is_none() {
            *guard = Some(PythonBridge::start(&self.python_dir, &self.app_data_dir)?);
        }
        Ok(())
    }

    fn call(&self, method: &str, article: &Article) -> Result<(), String> {
        self.ensure_bridge()?;
        let guard = self
            .bridge
            .lock()
            .map_err(|e| format!("Python bridge mutex poisoned: {e}"))?;
        guard
            .as_ref()
            .expect("bridge was just started")
            .call(&self.platform_id, method, article)
    }
}

impl Platform for PythonPlatform {
    fn id(&self) -> &str {
        &self.platform_id
    }

    fn name(&self) -> &str {
        &self.platform_name
    }

    fn publish(&self, article: &Article) -> Result<(), String> {
        self.call("publish", article)
    }

    fn update(&self, article: &Article) -> Result<(), String> {
        self.call("update", article)
    }
}
