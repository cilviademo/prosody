//! Asterism desktop shell.
//!
//! The window is a thin orchestrator: it locates the Python backend, forwards
//! API calls to it, streams progress events to the UI, and performs the few
//! things a browser genuinely cannot do - open a file picker, reveal a folder,
//! and launch FL Studio.

mod python;

use python::Backend;
use serde::Serialize;
use std::path::PathBuf;
use std::process::Command;
use tauri::{Emitter, Manager};

#[cfg(windows)]
use std::os::windows::process::CommandExt;
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

#[derive(Serialize, Clone)]
struct Progress {
    stage: String,
    status: String,
    detail: String,
}

fn backend(app: &tauri::AppHandle) -> Result<Backend, String> {
    let resource_dir = app.path().resource_dir().ok();
    Backend::resolve(resource_dir)
}

/// Call a backend method. Progress lines are emitted as `build-progress`
/// events; the final `result` line is returned to the caller.
#[tauri::command]
async fn api(
    app: tauri::AppHandle,
    method: String,
    payload: serde_json::Value,
) -> Result<serde_json::Value, String> {
    let body = serde_json::to_string(&payload).map_err(|e| e.to_string())?;
    let handle = app.clone();

    // Backend calls are blocking; keep them off the UI thread.
    let lines = tauri::async_runtime::spawn_blocking(move || {
        let backend = backend(&handle)?;
        backend.call(&method, &body)
    })
    .await
    .map_err(|e| format!("backend task failed: {e}"))??;

    let mut last: Option<serde_json::Value> = None;
    for line in lines {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        let Ok(value) = serde_json::from_str::<serde_json::Value>(trimmed) else {
            continue;
        };
        match value.get("event").and_then(|v| v.as_str()) {
            Some("progress") => {
                let _ = app.emit(
                    "build-progress",
                    Progress {
                        stage: value["stage"].as_str().unwrap_or_default().to_string(),
                        status: value["status"].as_str().unwrap_or_default().to_string(),
                        detail: value["detail"].as_str().unwrap_or_default().to_string(),
                    },
                );
            }
            Some("result") => last = Some(value),
            _ => {}
        }
    }

    last.ok_or_else(|| "The backend returned no result.".to_string())
}

/// True when the backend can be reached at all - used for the startup check.
#[tauri::command]
async fn backend_status(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    let handle = app.clone();
    let resolved = tauri::async_runtime::spawn_blocking(move || backend(&handle))
        .await
        .map_err(|e| e.to_string())?;
    Ok(match resolved {
        Ok(b) => serde_json::json!({
            "ok": true,
            "python": b.python.to_string_lossy(),
            "root": b.root.to_string_lossy(),
        }),
        Err(e) => serde_json::json!({ "ok": false, "error": e }),
    })
}

/// Reveal a file or folder in Explorer.
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

    // No configured path: let the OS open the .flp with its default handler.
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

/// Read a small file (preview audio) as bytes for the in-app player.
#[tauri::command]
fn read_media(path: String) -> Result<Vec<u8>, String> {
    let target = PathBuf::from(&path);
    let size = std::fs::metadata(&target).map_err(|e| e.to_string())?.len();
    // Guard against loading an enormous render into the webview.
    if size > 200 * 1024 * 1024 {
        return Err("This file is too large to preview in the app.".to_string());
    }
    std::fs::read(&target).map_err(|e| e.to_string())
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            api,
            backend_status,
            reveal,
            open_in_fl,
            read_media
        ])
        .run(tauri::generate_context!())
        .expect("error while running Asterism");
}
