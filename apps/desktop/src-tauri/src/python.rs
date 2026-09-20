//! Locating and invoking the Python backend.
//!
//! In a packaged build the `flpfinisher` package ships as a bundled resource
//! and runs under whichever Python the machine has. In development it runs
//! straight from the repository, preferring the project virtualenv.
//!
//! Every call is one short-lived process that speaks line-delimited JSON, so a
//! backend crash can never take the window down with it.

use std::path::{Path, PathBuf};
use std::process::Command;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

/// Candidate interpreters, most specific first.
fn interpreter_candidates(root: &Path) -> Vec<PathBuf> {
    let mut out = Vec::new();
    if let Ok(explicit) = std::env::var("PROSODY_PYTHON") {
        out.push(PathBuf::from(explicit));
    }
    out.push(root.join(".venv/Scripts/python.exe"));
    out.push(root.join(".venv/bin/python"));
    out.push(PathBuf::from("py"));
    out.push(PathBuf::from("python"));
    out.push(PathBuf::from("python3"));
    out
}

/// Walk upwards until we find the directory that holds `flpfinisher/`.
///
/// A directory that also has `pyproject.toml` is the development checkout and
/// is preferred: Tauri copies the backend into `target/debug` as a bundled
/// resource at build time, and that copy goes stale the moment anyone edits
/// Python without rebuilding Rust.
fn find_backend_root(start: &Path) -> Option<PathBuf> {
    let mut fallback: Option<PathBuf> = None;
    let mut current = Some(start);
    while let Some(dir) = current {
        if dir.join("flpfinisher/api.py").is_file() {
            if dir.join("pyproject.toml").is_file() {
                return Some(dir.to_path_buf());
            }
            fallback.get_or_insert_with(|| dir.to_path_buf());
        }
        current = dir.parent();
    }
    fallback
}

pub struct Backend {
    pub python: PathBuf,
    pub root: PathBuf,
}

impl Backend {
    /// Resolve the backend.
    ///
    /// Release builds prefer the bundled resource, which is the only copy that
    /// ships. Debug builds prefer the repository checkout, so editing Python
    /// takes effect on the next call instead of the next `cargo build`.
    pub fn resolve(resource_dir: Option<PathBuf>) -> Result<Self, String> {
        let mut bundled: Option<PathBuf> = None;
        if let Some(dir) = resource_dir {
            if dir.join("flpfinisher/api.py").is_file() {
                bundled = Some(dir);
            }
        }

        let mut checkout: Vec<PathBuf> = Vec::new();
        if let Ok(exe) = std::env::current_exe() {
            if let Some(found) = find_backend_root(&exe) {
                checkout.push(found);
            }
        }
        if let Ok(cwd) = std::env::current_dir() {
            if let Some(found) = find_backend_root(&cwd) {
                checkout.push(found);
            }
        }

        let mut roots: Vec<PathBuf> = Vec::new();
        if cfg!(debug_assertions) {
            roots.extend(checkout);
            roots.extend(bundled);
        } else {
            roots.extend(bundled);
            roots.extend(checkout);
        }

        let root = roots
            .into_iter()
            .next()
            .ok_or_else(|| "Could not find the Prosody backend (flpfinisher/).".to_string())?;

        for candidate in interpreter_candidates(&root) {
            let mut command = Command::new(&candidate);
            command.arg("-c").arg("import sys; print(sys.version_info[0])");
            #[cfg(windows)]
            command.creation_flags(CREATE_NO_WINDOW);
            if let Ok(output) = command.output() {
                if output.status.success() {
                    return Ok(Backend { python: candidate, root });
                }
            }
        }

        Err(format!(
            "Python 3 was not found. Install Python 3.10 or newer, or set \
             PROSODY_PYTHON to its path. Looked beside {}.",
            root.display()
        ))
    }

    /// Run one API method. Returns every stdout line for the caller to parse.
    pub fn call(&self, method: &str, payload: &str) -> Result<Vec<String>, String> {
        let mut command = Command::new(&self.python);
        command
            .arg("-m")
            .arg("flpfinisher.api")
            .arg(method)
            .arg(payload)
            .current_dir(&self.root)
            .env("PYTHONUNBUFFERED", "1")
            .env("PYTHONIOENCODING", "utf-8");
        #[cfg(windows)]
        command.creation_flags(CREATE_NO_WINDOW);

        let output = command
            .output()
            .map_err(|e| format!("Could not start the Prosody backend: {e}"))?;

        if !output.status.success() && output.stdout.is_empty() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            return Err(format!(
                "The backend exited with {}: {}",
                output.status,
                stderr.trim()
            ));
        }

        Ok(String::from_utf8_lossy(&output.stdout)
            .lines()
            .map(|l| l.to_string())
            .collect())
    }
}
