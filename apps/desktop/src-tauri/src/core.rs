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

        // Refuse a binary this machine cannot load, and say why. Without this
        // a staging mistake surfaces as "%1 is not a valid Win32 application",
        // which names neither the file nor the cause. Only the frozen core is
        // checked: the development path runs an interpreter the developer
        // chose, and PE headers are a Windows concept.
        #[cfg(windows)]
        if launch.args.is_empty() {
            crate::pe::check_runnable(&launch.program, "The Prosody core")?;
        }

        let mut command = Command::new(&launch.program);
        command
            .args(&launch.args)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .env("PYTHONUNBUFFERED", "1")
            .env("PYTHONIOENCODING", "utf-8")
            // Without this, a Python built before 3.15 uses the machine's ANSI
            // code page for filesystem paths, and a project under a name with
            // any non-Latin-1 character becomes unopenable. HARDENING P0.1.
            .env("PYTHONUTF8", "1")
            .env("PROSODY_HOME", &paths.documents)
            .env("PROSODY_STATE", &paths.state)
            .env(
                "PROSODY_SAFE_MODE",
                if crate::paths::safe_mode_requested() { "1" } else { "0" },
            );
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
        let (found, tried) = packaged_core(resource_dir.as_deref());
        if let Some(found) = found {
            let bin_dir = found.parent().and_then(|p| p.parent()).map(|p| p.join("bin"));
            return Ok(Launch {
                program: found,
                args: vec![],
                working_dir: None,
                bin_dir: bin_dir.filter(|p| p.is_dir()),
            });
        }

        let searched = tried
            .iter()
            .map(|p| format!("  {}", p.display()))
            .collect::<Vec<_>>()
            .join("\n");

        // A release must never reach for a Python on the user's machine. The
        // run-from-source path exists only in a development build, so the
        // PATH lookup below is not merely unused in a release — it is not
        // compiled into one. HARDENING P0.1: the only processes a shipped
        // Prosody may start are its own bundled core, the configured FL64.exe
        // and the shell's file-opener.
        #[cfg(debug_assertions)]
        {
            if let Some(root) = repo_root() {
                if let Some(python) = interpreter(&root) {
                    return Ok(Launch {
                        program: python,
                        args: vec!["-m".into(), "prosody_core".into()],
                        working_dir: Some(root),
                        bin_dir: None,
                    });
                }
            }
        }

        Err(format!(
            "Could not find the Prosody core.\n\nIt ships under \
             resources/prosody-core, beside Prosody.exe. If you moved or \
             extracted only part of the folder, extract it again and keep it \
             together. Looked in:\n{searched}\n\nSet PROSODY_CORE_EXE to the \
             executable to override this search."
        ))
    }
}

fn core_exe_name() -> &'static str {
    if cfg!(windows) { "prosody-core.exe" } else { "prosody-core" }
}

/// Roots the packaged core could live under, most likely first.
fn resource_roots(resource_dir: Option<&Path>) -> Vec<PathBuf> {
    let mut roots: Vec<PathBuf> = Vec::new();
    if let Some(dir) = resource_dir {
        roots.push(dir.to_path_buf());
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(parent) = exe.parent() {
            roots.push(parent.to_path_buf());
            // NSIS installs put resources beside the executable; some layouts
            // nest the binary one level deeper.
            if let Some(grandparent) = parent.parent() {
                roots.push(grandparent.to_path_buf());
            }
        }
    }
    roots.dedup();
    roots
}

/// Find the packaged core, recording every path tried.
///
/// Tauri's placement of a *directory* resource has differed between versions,
/// and this cannot be tested from a non-Windows machine — so rather than
/// betting on one layout, try the plausible ones and then search. Returning
/// the attempted paths matters as much as finding the file: "could not find
/// the core" with no list is the least actionable error a packaged app can
/// give.
fn packaged_core(resource_dir: Option<&Path>) -> (Option<PathBuf>, Vec<PathBuf>) {
    let mut tried: Vec<PathBuf> = Vec::new();
    let exe_name = core_exe_name();

    // An explicit override always wins; it is the escape hatch when a layout
    // surprises us in the field.
    if let Ok(explicit) = std::env::var("PROSODY_CORE_EXE") {
        let candidate = PathBuf::from(explicit);
        tried.push(candidate.clone());
        if candidate.is_file() {
            return (Some(candidate), tried);
        }
    }

    let relatives = [
        "resources/prosody-core",
        "prosody-core",
        "resources/prosody-core/prosody-core",
        "resources",
    ];

    for root in resource_roots(resource_dir) {
        for relative in relatives {
            let candidate = root.join(relative).join(exe_name);
            tried.push(candidate.clone());
            if candidate.is_file() {
                return (Some(candidate), tried);
            }
        }
        // Last resort: a shallow search. Cheap, bounded, and it turns a
        // packaging mistake into a working app instead of a support thread.
        if let Some(found) = search_for(&root, exe_name, 3) {
            return (Some(found), tried);
        }
    }
    (None, tried)
}

/// Depth-limited search for `name` beneath `root`.
fn search_for(root: &Path, name: &str, depth: usize) -> Option<PathBuf> {
    if depth == 0 {
        return None;
    }
    let entries = std::fs::read_dir(root).ok()?;
    let mut directories: Vec<PathBuf> = Vec::new();
    for entry in entries.flatten() {
        let path = entry.path();
        match entry.file_type() {
            Ok(kind) if kind.is_file() => {
                if path.file_name().and_then(|n| n.to_str()) == Some(name) {
                    return Some(path);
                }
            }
            Ok(kind) if kind.is_dir() => directories.push(path),
            _ => {}
        }
    }
    for directory in directories {
        if let Some(found) = search_for(&directory, name, depth - 1) {
            return Some(found);
        }
    }
    None
}

/// Walk upwards for the checkout that holds `prosody_core/__main__.py`.
#[cfg(debug_assertions)]
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

#[cfg(debug_assertions)]
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
