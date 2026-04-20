use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use crate::models::article::Article;

const PYTHON_REQUEST_TIMEOUT_SECS: u64 = 300;
const PYTHON_CONNECT_TIMEOUT_SECS: u64 = 10;

/// Manages the lifecycle of the Python provider server process.
pub struct PythonBridge {
    process: Child,
    port: u16,
}

impl PythonBridge {
    /// Bootstrap the virtual environment (create + install deps), then spawn
    /// the provider server.  Blocks until the server prints `LISTENING:<port>`.
    ///
    /// * `python_dir`   — directory containing `server.py` and `requirements.txt`
    /// * `app_data_dir` — persistent app data directory (venv lives here)
    pub fn start(python_dir: &str, app_data_dir: &str) -> Result<Self, String> {
        let venv_dir = Path::new(app_data_dir).join("python-venv");
        bootstrap_venv(&venv_dir, python_dir)?;

        let python_exe = venv_python(&venv_dir);
        let script = Path::new(python_dir).join("server.py");

        eprintln!("[hydra] python_exe: {:?} (exists={})", python_exe, python_exe.exists());
        eprintln!("[hydra] script:     {:?} (exists={})", script, script.exists());
        eprintln!("[hydra] PATH:       {:?}", std::env::var("PATH").unwrap_or_default());

        // Inherit the current PATH so chromium/chromedriver are findable when
        // the process is spawned from inside Tauri (which may have a stripped env).
        let path_env = std::env::var("PATH").unwrap_or_default();

        let mut child = Command::new(&python_exe)
            .arg(script.to_string_lossy().as_ref())
            .arg("--port")
            .arg("0")
            .env("PATH", &path_env)
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .map_err(|e| format!("Failed to start Python server ({python_exe:?}): {e}"))?;

        let stdout = child
            .stdout
            .take()
            .ok_or("Python server did not open stdout")?;
        let mut reader = BufReader::new(stdout);
        let mut line = String::new();
        reader
            .read_line(&mut line)
            .map_err(|e| format!("Failed to read Python server port: {e}"))?;

        let port: u16 = line
            .trim()
            .strip_prefix("LISTENING:")
            .ok_or_else(|| format!("Unexpected Python server output: {line:?}"))?
            .parse()
            .map_err(|e| format!("Could not parse port from Python server: {e}"))?;

        eprintln!("[hydra] Python server listening on port {port}");

        // Forward any further stdout from the Python server to our stderr
        // so provider print() and selenium errors are visible in the Tauri logs.
        std::thread::spawn(move || {
            let mut buf = String::new();
            while reader.read_line(&mut buf).unwrap_or(0) > 0 {
                eprint!("[python] {buf}");
                buf.clear();
            }
        });

        Ok(Self { process: child, port })
    }

    /// Send a publish or update request to the Python server.
    pub fn call(
        &self,
        provider_id: &str,
        method: &str,
        article: &Article,
    ) -> Result<(), String> {
        let body = serde_json::to_string(article)
            .map_err(|e| format!("Failed to serialize article: {e}"))?;
        let response = self.post(provider_id, method, &body)?;
        if response.status().is_success() {
            Ok(())
        } else {
            let err = self.extract_error(response);
            eprintln!("[hydra] provider call failed: {err}");
            Err(err)
        }
    }

    /// Send arbitrary JSON to a provider method and return the response body.
    pub fn call_json(
        &self,
        provider_id: &str,
        method: &str,
        body: &serde_json::Value,
    ) -> Result<serde_json::Value, String> {
        let body_str = serde_json::to_string(body)
            .map_err(|e| format!("Failed to serialize JSON: {e}"))?;
        let response = self.post(provider_id, method, &body_str)?;
        if response.status().is_success() {
            let text = response.text().unwrap_or_default();
            serde_json::from_str(&text)
                .map_err(|e| format!("Failed to parse response JSON: {e}"))
        } else {
            let err = self.extract_error(response);
            eprintln!("[hydra] provider call failed: {err}");
            Err(err)
        }
    }

    /// Return the list of provider IDs that have an active Selenium session.
    pub fn get_sessions(&self) -> Result<Vec<String>, String> {
        let url = format!("http://127.0.0.1:{}/sessions", self.port);
        let client = reqwest::blocking::Client::new();
        let resp = client
            .get(&url)
            .timeout(std::time::Duration::from_secs(10))
            .send()
            .map_err(|e| format!("Python bridge HTTP request failed: {e}"))?;
        let json: serde_json::Value = resp
            .json()
            .map_err(|e| format!("Failed to parse sessions response: {e}"))?;
        let sessions = json["sessions"]
            .as_array()
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(|s| s.to_string()))
                    .collect()
            })
            .unwrap_or_default();
        Ok(sessions)
    }

    /// Kill the Selenium session for `provider_id`.
    pub fn kill_session(&self, provider_id: &str) -> Result<(), String> {
        let url = format!("http://127.0.0.1:{}/sessions/{}", self.port, provider_id);
        let client = reqwest::blocking::Client::new();
        let resp = client
            .delete(&url)
            .timeout(std::time::Duration::from_secs(15))
            .send()
            .map_err(|e| format!("Python bridge HTTP request failed: {e}"))?;
        if resp.status().is_success() || resp.status().as_u16() == 404 {
            Ok(())
        } else {
            Err(self.extract_error(resp))
        }
    }

    fn post(
        &self,
        provider_id: &str,
        method: &str,
        body: &str,
    ) -> Result<reqwest::blocking::Response, String> {
        let url = format!("http://127.0.0.1:{}/{}/{}", self.port, provider_id, method);
        eprintln!("[hydra] -> POST {url}");
        let client = reqwest::blocking::Client::builder()
            .connect_timeout(std::time::Duration::from_secs(PYTHON_CONNECT_TIMEOUT_SECS))
            .timeout(std::time::Duration::from_secs(PYTHON_REQUEST_TIMEOUT_SECS))
            .build()
            .map_err(|e| format!("Failed to build Python bridge HTTP client: {e}"))?;

        let response = client
            .post(&url)
            .header("Content-Type", "application/json")
            .body(body.to_string())
            .send()
            .map_err(|e| format!("Python bridge HTTP request failed for {url}: {e}"))?;

        eprintln!("[hydra] <- POST {url} [{}]", response.status());
        Ok(response)
    }

    fn extract_error(&self, response: reqwest::blocking::Response) -> String {
        let status = response.status();
        let text = response.text().unwrap_or_default();
        let msg = serde_json::from_str::<serde_json::Value>(&text)
            .ok()
            .map(|v| {
                let error = v["error"].as_str().unwrap_or("Unknown Python error");
                if let Some(tb) = v["traceback"].as_str() {
                    format!("{error}\n{tb}")
                } else {
                    error.to_string()
                }
            })
            .unwrap_or(text);
        format!("Python provider error (HTTP {status}): {msg}")
    }

    fn stop(&self) {
        let url = format!("http://127.0.0.1:{}/stop", self.port);
        let _ = reqwest::blocking::Client::new()
            .post(&url)
            .timeout(std::time::Duration::from_secs(5))
            .send();
    }
}

impl Drop for PythonBridge {
    fn drop(&mut self) {
        // Try to stop gracefully without blocking (fire-and-forget).
        // Using spawn to avoid blocking in async/drop context.
        let url = format!("http://127.0.0.1:{}/stop", self.port);
        std::thread::spawn(move || {
            let _ = reqwest::blocking::Client::new()
                .post(&url)
                .timeout(std::time::Duration::from_secs(3))
                .send();
        });
        let _ = self.process.kill();
    }
}

// ---------------------------------------------------------------------------
// Venv helpers
// ---------------------------------------------------------------------------

/// Create the virtual-environment if it does not exist, then install
/// (or update) packages from `<python_dir>/requirements.txt`.
fn bootstrap_venv(venv_dir: &Path, python_dir: &str) -> Result<(), String> {
    let system_python = system_python_exe();

    if !venv_dir.exists() {
        eprintln!("[hydra] Creating Python venv at {}", venv_dir.display());
        let status = Command::new(&system_python)
            .args(["-m", "venv", &venv_dir.to_string_lossy()])
            .status()
            .map_err(|e| format!("Failed to run '{system_python}': {e}"))?;
        if !status.success() {
            return Err(format!(
                "Failed to create venv at {}: exit code {:?}",
                venv_dir.display(),
                status.code()
            ));
        }
    }

    let requirements = Path::new(python_dir).join("requirements.txt");
    if requirements.exists() {
        eprintln!("[hydra] Installing Python dependencies from {}", requirements.display());
        let pip = venv_pip(venv_dir);
        let status = Command::new(&pip)
            .args([
                "install",
                "-r",
                &requirements.to_string_lossy(),
            ])
            .status()
            .map_err(|e| format!("Failed to run pip ({pip:?}): {e}"))?;
        if !status.success() {
            return Err(format!(
                "pip install failed (exit code {:?}); check requirements.txt",
                status.code()
            ));
        }
    }

    Ok(())
}

/// Path to the system Python interpreter (`python3` or `python`).
fn system_python_exe() -> String {
    if which("python3") {
        "python3".to_string()
    } else {
        "python".to_string()
    }
}

fn venv_python(venv_dir: &Path) -> PathBuf {
    if cfg!(windows) {
        venv_dir.join("Scripts").join("python.exe")
    } else {
        venv_dir.join("bin").join("python3")
    }
}

fn venv_pip(venv_dir: &Path) -> PathBuf {
    if cfg!(windows) {
        venv_dir.join("Scripts").join("pip.exe")
    } else {
        venv_dir.join("bin").join("pip")
    }
}

/// Return true if `exe` is found on PATH.
fn which(exe: &str) -> bool {
    Command::new(exe)
        .arg("--version")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}
