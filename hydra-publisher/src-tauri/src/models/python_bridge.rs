use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use crate::models::article::Article;

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

        let mut child = Command::new(&python_exe)
            .arg(script.to_string_lossy().as_ref())
            .arg("--port")
            .arg("0")
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

        // Drain any further stdout in the background so the process never blocks.
        std::thread::spawn(move || {
            let mut buf = String::new();
            while reader.read_line(&mut buf).unwrap_or(0) > 0 {
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
        let url = format!("http://127.0.0.1:{}/{}/{}", self.port, provider_id, method);
        let body = serde_json::to_string(article)
            .map_err(|e| format!("Failed to serialize article: {e}"))?;

        let client = reqwest::blocking::Client::new();
        let response = client
            .post(&url)
            .header("Content-Type", "application/json")
            .body(body)
            .timeout(std::time::Duration::from_secs(300)) // allow long Selenium interactions
            .send()
            .map_err(|e| format!("Python bridge HTTP request failed: {e}"))?;

        if response.status().is_success() {
            Ok(())
        } else {
            let status = response.status();
            let text = response.text().unwrap_or_default();
            let msg = serde_json::from_str::<serde_json::Value>(&text)
                .ok()
                .and_then(|v| v["error"].as_str().map(|s| s.to_string()))
                .unwrap_or(text);
            Err(format!("Python provider error (HTTP {status}): {msg}"))
        }
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
        self.stop();
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
                "--quiet",
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
