//! Prosody desktop shell.
//!
//! The window is a thin orchestrator. It resolves where files live, starts the
//! Prosody core and completes the ping handshake, forwards API calls to it, and
//! performs the few things a browser genuinely cannot: open a file picker,
//! reveal a folder, and launch FL Studio.
//!
//! Startup order matters and is fixed:
//!   1. WebView2 check (without it the window is simply blank)
//!   2. portable-mode check
//!   3. create directories
//!   4. start the core and ping it
//! A failure at step 4 leaves the window up with a diagnostics payload rather
//! than a blank frame or a crash.

mod core;
mod paths;
mod webview2;

use std::path::PathBuf;
use std::process::Command;
use std::sync::Mutex;
use std::time::Duration;

use serde::Serialize;
use serde_json::{json, Value};
use tauri::{Manager, State};

use crate::core::{Core, REQUEST_TIMEOUT};
use crate::paths::Paths;

#[cfg(windows)]
use std::os::windows::process::CommandExt;
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

/// Everything the window needs, resolved once at startup.
struct AppState {
    paths: Paths,
    core: Mutex<Option<Core>>,
    startup_error: Mutex<Option<String>>,
    core_version: Mutex<String>,
}

#[derive(Serialize)]
struct Status {
    ok: bool,
    portable: bool,
    documents: String,
    state: String,
    logs: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    core_version: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    core_executable: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<String>,
}

/// Call a core method. Progress lines are emitted as `build-progress` events.
#[tauri::command]
async fn api(
    app: tauri::AppHandle,
    state: State<'_, AppState>,
    method: String,
    payload: Value,
) -> Result<Value, String> {
    let mut guard = state
        .core
        .lock()
        .map_err(|_| "the core connection is poisoned".to_string())?;
    let core = guard.as_mut().ok_or_else(|| {
        state
            .startup_error
            .lock()
            .ok()
            .and_then(|e| e.clone())
            .unwrap_or_else(|| "The Prosody core is not running.".to_string())
    })?;

    match core.request(Some(&app), &method, payload, REQUEST_TIMEOUT) {
        Ok(value) => Ok(value),
        Err(message) => {
            // A dead core must not look like a failed request forever.
            *state.startup_error.lock().unwrap() = Some(message.clone());
            *guard = None;
            Err(message)
        }
    }
}

/// What the UI asks on boot to decide between the app and a diagnostics screen.
#[tauri::command]
fn backend_status(state: State<'_, AppState>) -> Status {
    let running = state.core.lock().map(|c| c.is_some()).unwrap_or(false);
    let error = state.startup_error.lock().ok().and_then(|e| e.clone());
    let version = state.core_version.lock().ok().map(|v| v.clone()).filter(|v| !v.is_empty());
    let executable = state
        .core
        .lock()
        .ok()
        .and_then(|c| c.as_ref().map(|core| core.executable.to_string_lossy().into_owned()));

    Status {
        ok: running,
        portable: state.paths.portable,
        documents: state.paths.documents.to_string_lossy().into_owned(),
        state: state.paths.state.to_string_lossy().into_owned(),
        logs: state.paths.logs().to_string_lossy().into_owned(),
        core_version: version,
        core_executable: executable,
        error,
    }
}

/// Try to start the core again after a failure, without restarting the app.
#[tauri::command]
async fn restart_core(state: State<'_, AppState>) -> Result<Status, String> {
    {
        let mut guard = state.core.lock().map_err(|_| "poisoned".to_string())?;
        if let Some(mut existing) = guard.take() {
            existing.shutdown();
        }
    }

    let paths = state.paths.clone();
    let started = tauri::async_runtime::spawn_blocking(move || Core::start(&paths, None))
        .await
        .map_err(|e| e.to_string())?;

    match started {
        Ok(core) => {
            *state.core_version.lock().unwrap() = core.version.clone();
            *state.startup_error.lock().unwrap() = None;
            *state.core.lock().unwrap() = Some(core);
        }
        Err(message) => {
            *state.startup_error.lock().unwrap() = Some(message.clone());
            return Err(message);
        }
    }
    Ok(backend_status(state))
}

/// Reveal a file or folder in the system file manager.
#[tauri::command]
fn reveal(path: String) -> Result<(), String> {
    let target = PathBuf::from(&path);
    if !target.exists() {
        return Err(format!("{path} no longer exists."));
    }

    #[cfg(windows)]
    {
        let mut command = Command::new("explorer");
        if target.is_file() {
            command.arg("/select,").arg(&target);
        } else {
            command.arg(&target);
        }
        command.creation_flags(CREATE_NO_WINDOW);
        command.spawn().map_err(|e| e.to_string())?;
        return Ok(());
    }

    #[cfg(target_os = "macos")]
    {
        Command::new("open").arg(&target).spawn().map_err(|e| e.to_string())?;
        return Ok(());
    }

    #[cfg(all(unix, not(target_os = "macos")))]
    {
        let dir = if target.is_file() {
            target.parent().unwrap_or(&target).to_path_buf()
        } else {
            target.clone()
        };
        Command::new("xdg-open").arg(dir).spawn().map_err(|e| e.to_string())?;
        Ok(())
    }
}

/// Launch a generated project in FL Studio.
#[tauri::command]
fn open_in_fl(fl_executable: Option<String>, flp: String) -> Result<(), String> {
    let project = PathBuf::from(&flp);
    if !project.is_file() {
        return Err(format!("{flp} no longer exists."));
    }

    if let Some(exe) = fl_executable.filter(|e| !e.is_empty()) {
        let executable = PathBuf::from(&exe);
        if !executable.is_file() {
            return Err(format!("FL Studio was not found at {exe}."));
        }
        let mut command = Command::new(executable);
        command.arg(&project);
        #[cfg(windows)]
        command.creation_flags(CREATE_NO_WINDOW);
        command
            .spawn()
            .map_err(|e| format!("Could not start FL Studio: {e}"))?;
        return Ok(());
    }

    #[cfg(windows)]
    {
        let mut command = Command::new("cmd");
        command.args(["/C", "start", "", &flp]);
        command.creation_flags(CREATE_NO_WINDOW);
        command.spawn().map_err(|e| e.to_string())?;
        Ok(())
    }
    #[cfg(not(windows))]
    {
        Err("Set your FL Studio path in Settings to open projects.".to_string())
    }
}

/// Read a render back for the in-app preview player.
#[tauri::command]
fn read_media(path: String) -> Result<Vec<u8>, String> {
    let target = PathBuf::from(&path);
    let size = std::fs::metadata(&target).map_err(|e| e.to_string())?.len();
    if size > 200 * 1024 * 1024 {
        return Err("This file is too large to preview in the app.".to_string());
    }
    std::fs::read(&target).map_err(|e| e.to_string())
}

/// Remember window geometry between sessions.
#[tauri::command]
async fn save_window(
    state: State<'_, AppState>,
    width: f64,
    height: f64,
    x: i32,
    y: i32,
) -> Result<(), String> {
    let mut guard = state.core.lock().map_err(|_| "poisoned".to_string())?;
    if let Some(core) = guard.as_mut() {
        let params = json!({
            "settings": { "window": { "width": width, "height": height, "x": x, "y": y } }
        });
        let _ = core.request(None, "settings.set", params, Duration::from_secs(10));
    }
    Ok(())
}

pub fn run() {
    // 1. Without WebView2 the window renders nothing at all; say so instead.
    if !webview2::is_installed() {
        webview2::warn_and_exit();
    }

    // 2 & 3. Resolve the roots (portable mode included) and create them.
    let paths = Paths::resolve();
    if let Err(e) = paths.ensure() {
        eprintln!("could not create application folders: {e}");
    }

    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .setup(move |app| {
            let resource_dir = app.path().resource_dir().ok();

            // 4. Start the core and ping it. A failure here is reported to the
            // UI as a diagnostics payload, never as a blank window.
            let (core, version, error) = match Core::start(&paths, resource_dir) {
                Ok(core) => {
                    let version = core.version.clone();
                    (Some(core), version, None)
                }
                Err(message) => (None, String::new(), Some(message)),
            };

            app.manage(AppState {
                paths: paths.clone(),
                core: Mutex::new(core),
                startup_error: Mutex::new(error),
                core_version: Mutex::new(version),
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            api,
            backend_status,
            restart_core,
            reveal,
            open_in_fl,
            read_media,
            save_window
        ])
        .run(tauri::generate_context!())
        .expect("error while running Prosody");
}
