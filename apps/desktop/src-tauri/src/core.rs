//! The long-lived Prosody core process, and the stdio protocol it speaks.
//!
//! One child process for the session, not one per call. Requests are JSON
//! lines on stdin; responses and progress events are JSON lines on stdout,
//! correlated by `id`.
//!
//! Why stdio rather than a localhost HTTP server: no port to collide with, no
//! firewall prompt the first time the app runs, and the child dies with the
//! parent instead of outliving it.
//!
//! A reader thread parses every line into a channel, which is what gives every
//! wait a real timeout. A core that stops answering must look different from
//! one that is merely slow.

use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError};
use std::time::{Duration, Instant};

use serde::Serialize;
use serde_json::{json, Value};
use tauri::{AppHandle, Emitter};

use crate::paths::Paths;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

/// Detach from any console so no window flashes when the core starts.
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

/// The startup contract: spawn, ping, answer within this long.
pub const PING_TIMEOUT: Duration = Duration::from_secs(10);

/// Long enough for an FL render of a heavy project.
pub const REQUEST_TIMEOUT: Duration = Duration::from_secs(60 * 30);

#[derive(Serialize, Clone)]
struct Progress {
    stage: String,
    status: String,
    detail: String,
}

pub struct Core {
    child: Child,
    stdin: ChildStdin,
    lines: Receiver<Value>,
    next_id: u64,
    pub executable: PathBuf,
    pub version: String,
}

impl Core {
    /// Spawn the core and complete the ping handshake.
    pub fn start(paths: &Paths, resource_dir: Option<PathBuf>) -> Result<Self, String> {
        let launch = Launch::resolve(resource_dir)?;

        let mut command = Command::new(&launch.program);
        command
            .args(&launch.args)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .env("PYTHONUNBUFFERED", "1")
            .env("PYTHONIOENCODING", "utf-8")
            .env("PROSODY_HOME", &paths.documents)
            .env("PROSODY_STATE", &paths.state);
        if let Some(dir) = &launch.working_dir {
            command.current_dir(dir);
        }
        if let Some(bin) = &launch.bin_dir {
            command.env("PROSODY_BIN", bin);
        }
        #[cfg(windows)]
        command.creation_flags(CREATE_NO_WINDOW);

        let mut child = command.spawn().map_err(|e| {
            format!("Could not start the Prosody core ({}): {e}", launch.program.display())
        })?;

        let stdin = child.stdin.take().ok_or("the core gave no stdin")?;
        let stdout = child.stdout.take().ok_or("the core gave no stdout")?;

        let (tx, lines) = mpsc::channel();
        std::thread::spawn(move || {
            for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                if let Ok(value) = serde_json::from_str::<Value>(&line) {
                    if tx.send(value).is_err() {
                        break;
                    }
                }
            }
        });

        // Drain stderr so a chatty core cannot fill its pipe buffer and block.
        if let Some(errors) = child.stderr.take() {
            std::thread::spawn(move || {
                for line in BufReader::new(errors).lines().map_while(Result::ok) {
                    eprintln!("[core] {line}");
                }
            });
        }

        let mut core = Core {
            child,
            stdin,
            lines,
            next_id: 1,
            executable: launch.program,
            version: String::new(),
        };

        let reply = core
            .request(None, "ping", json!({}), PING_TIMEOUT)
            .map_err(|e| format!("The Prosody core did not answer: {e}"))?;
        core.version = reply
            .get("version")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string();
        Ok(core)
    }

    /// Send one request and wait for its response, relaying progress events.
    pub fn request(
        &mut self,
        app: Option<&AppHandle>,
        method: &str,
        params: Value,
        timeout: Duration,
    ) -> Result<Value, String> {
        let id = self.next_id;
        self.next_id += 1;

        let line = json!({ "id": id, "method": method, "params": params });
        writeln!(self.stdin, "{line}").map_err(|e| format!("could not write to the core: {e}"))?;
        self.stdin
            .flush()
            .map_err(|e| format!("could not flush to the core: {e}"))?;

        let deadline = Instant::now() + timeout;
        loop {
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return Err(format!("no response to {method} within {timeout:?}"));
            }
            match self.lines.recv_timeout(remaining) {
                Ok(value) => {
                    // Ignore anything not addressed to this request.
                    if value.get("id").and_then(Value::as_u64) != Some(id) {
                        continue;
                    }
                    if value.get("event").and_then(Value::as_str) == Some("progress") {
                        if let Some(handle) = app {
                            let _ = handle.emit(
                                "build-progress",
                                Progress {
                                    stage: string_at(&value, "stage"),
                                    status: string_at(&value, "status"),
                                    detail: string_at(&value, "detail"),
                                },
                            );
                        }
                        continue;
                    }
                    return Ok(value);
                }
                Err(RecvTimeoutError::Timeout) => {
                    return Err(format!("no response to {method} within {timeout:?}"))
                }
                Err(RecvTimeoutError::Disconnected) => {
                    return Err("the Prosody core stopped unexpectedly".to_string())
                }
            }
        }
    }

    pub fn shutdown(&mut self) {
        let _ = writeln!(self.stdin, "{}", json!({ "id": 0, "method": "shutdown" }));
        let _ = self.stdin.flush();
        std::thread::sleep(Duration::from_millis(120));
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

impl Drop for Core {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

fn string_at(value: &Value, key: &str) -> String {
    value.get(key).and_then(Value::as_str).unwrap_or_default().to_string()
}

/// How to launch the core: the packaged binary, or Python from a checkout.
struct Launch {
    program: PathBuf,
    args: Vec<String>,
    working_dir: Option<PathBuf>,
    bin_dir: Option<PathBuf>,
}

impl Launch {
    fn resolve(resource_dir: Option<PathBuf>) -> Result<Self, String> {
        // A release always ships the frozen core beside the executable.
        if let Some(found) = packaged_core(resource_dir.as_deref()) {
            let bin_dir = found.parent().and_then(|p| p.parent()).map(|p| p.join("bin"));
            return Ok(Launch {
                program: found,
                args: vec![],
                working_dir: None,
                bin_dir: bin_dir.filter(|p| p.is_dir()),
            });
        }

        // Development: run the package straight from the repository.
        let root = repo_root().ok_or_else(|| {
            "Could not find the Prosody core. A packaged build ships it under \
             resources/prosody-core; a development build needs the repository."
                .to_string()
        })?;
        let python = interpreter(&root).ok_or_else(|| {
            format!(
                "Python 3 was not found. Install Python 3.10 or newer, or set \
                 PROSODY_PYTHON to its path. Looked beside {}.",
                root.display()
            )
        })?;
        Ok(Launch {
            program: python,
            args: vec!["-m".into(), "prosody_core".into()],
            working_dir: Some(root),
            bin_dir: None,
        })
    }
}

fn core_exe_name() -> &'static str {
    if cfg!(windows) { "prosody-core.exe" } else { "prosody-core" }
}

/// `resources/prosody-core/prosody-core[.exe]`, next to the app or in resources.
fn packaged_core(resource_dir: Option<&Path>) -> Option<PathBuf> {
    let mut roots: Vec<PathBuf> = Vec::new();
    if let Some(dir) = resource_dir {
        roots.push(dir.to_path_buf());
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(parent) = exe.parent() {
            roots.push(parent.to_path_buf());
        }
    }
    for root in roots {
        for relative in ["resources/prosody-core", "prosody-core"] {
            let candidate = root.join(relative).join(core_exe_name());
            if candidate.is_file() {
                return Some(candidate);
            }
        }
    }
    None
}

/// Walk upwards for the checkout that holds `prosody_core/__main__.py`.
fn repo_root() -> Option<PathBuf> {
    let mut fallback: Option<PathBuf> = None;
    for start in [std::env::current_exe().ok(), std::env::current_dir().ok()]
        .into_iter()
        .flatten()
    {
        let mut current = Some(start.as_path());
        while let Some(dir) = current {
            if dir.join("prosody_core/__main__.py").is_file() {
                // A directory with pyproject.toml is the checkout, not a
                // build-time copy of it that goes stale on the next edit.
                if dir.join("pyproject.toml").is_file() {
                    return Some(dir.to_path_buf());
                }
                fallback.get_or_insert_with(|| dir.to_path_buf());
            }
            current = dir.parent();
        }
    }
    fallback
}

fn interpreter(root: &Path) -> Option<PathBuf> {
    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Ok(explicit) = std::env::var("PROSODY_PYTHON") {
        candidates.push(PathBuf::from(explicit));
    }
    candidates.push(root.join(".venv/Scripts/python.exe"));
    candidates.push(root.join(".venv/bin/python"));
    candidates.push(PathBuf::from("python"));
    candidates.push(PathBuf::from("python3"));

    for candidate in candidates {
        let mut probe = Command::new(&candidate);
        probe.arg("-c").arg("import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)");
        #[cfg(windows)]
        probe.creation_flags(CREATE_NO_WINDOW);
        if let Ok(status) = probe.status() {
            if status.success() {
                return Some(candidate);
            }
        }
    }
    None
}
