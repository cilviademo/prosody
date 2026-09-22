//! Where Prosody reads and writes on this machine.
//!
//! Two roots, decided here and handed to the core through the environment so
//! there is exactly one place that knows the policy:
//!
//! * documents — `Documents\Prosody`, or `%USERPROFILE%\Prosody` when Documents
//!   is inside a sync client's folder — the user's exports
//! * state     — `%LOCALAPPDATA%\Prosody` — database, settings, cache, logs
//!
//! Portable mode collapses both into `Data\` beside the executable, so a copy
//! on a USB stick writes nothing to the host profile.

use std::path::{Path, PathBuf};

pub const APP_DIR: &str = "Prosody";
pub const PORTABLE_FLAG: &str = "portable.flag";

#[derive(Debug, Clone)]
pub struct Paths {
    pub documents: PathBuf,
    pub state: PathBuf,
    pub portable: bool,
}

impl Paths {
    /// Resolve the roots. Portable mode wins if the flag file is present.
    pub fn resolve() -> Self {
        if let Some(dir) = portable_data_dir() {
            return Paths { documents: dir.clone(), state: dir, portable: true };
        }
        Paths {
            documents: user_root(&documents_dir()),
            state: state_dir().join(APP_DIR),
            portable: false,
        }
    }

    pub fn logs(&self) -> PathBuf {
        self.state.join("Logs")
    }

    pub fn exports(&self) -> PathBuf {
        self.documents.join("Exports")
    }

    pub fn projects(&self) -> PathBuf {
        self.documents.join("Projects")
    }

    /// Create everything up front so a first run never fails mid-build.
    pub fn ensure(&self) -> std::io::Result<()> {
        for dir in [
            self.exports(),
            self.projects(),
            self.state.join("Cache"),
            self.logs(),
        ] {
            std::fs::create_dir_all(dir)?;
        }
        Ok(())
    }
}

/// `Data/` beside the executable, when `portable.flag` sits next to it.
pub fn portable_data_dir() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let dir = exe.parent()?;
    if dir.join(PORTABLE_FLAG).is_file() {
        return Some(dir.join("Data"));
    }
    None
}

fn documents_dir() -> PathBuf {
    #[cfg(windows)]
    {
        if let Ok(profile) = std::env::var("USERPROFILE") {
            return PathBuf::from(profile).join("Documents");
        }
    }
    home().join("Documents")
}

fn state_dir() -> PathBuf {
    #[cfg(windows)]
    {
        if let Ok(local) = std::env::var("LOCALAPPDATA") {
            return PathBuf::from(local);
        }
        return home().join("AppData").join("Local");
    }
    #[cfg(target_os = "macos")]
    {
        return home().join("Library").join("Application Support");
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        if let Ok(xdg) = std::env::var("XDG_DATA_HOME") {
            return PathBuf::from(xdg);
        }
        home().join(".local").join("share")
    }
}

fn home() -> PathBuf {
    #[cfg(windows)]
    {
        if let Ok(profile) = std::env::var("USERPROFILE") {
            return PathBuf::from(profile);
        }
    }
    std::env::var("HOME").map(PathBuf::from).unwrap_or_else(|_| PathBuf::from("."))
}

/// Whether this session may only look, never touch (HARDENING P0.2).
///
/// Three ways in, because the situation it exists for is "the app will not
/// start and I cannot use it to change a setting":
///
///   * `--safe` on the command line, for anyone comfortable with a shortcut
///   * a `safemode.flag` file beside the executable, which needs no terminal
///   * Shift held at launch, which needs nothing at all
///
/// The answer is computed once and handed to the core in its environment, so
/// the whole process tree agrees.
pub fn safe_mode_requested() -> bool {
    if std::env::args().any(|a| a == "--safe" || a == "/safe") {
        return true;
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            if dir.join("safemode.flag").exists() {
                return true;
            }
        }
    }
    shift_held()
}

#[cfg(windows)]
fn shift_held() -> bool {
    // GetAsyncKeyState's high bit is "down right now". Reading it this early
    // catches a Shift held through the splash, which is when a user who has
    // just had a failed launch would be holding it.
    const VK_SHIFT: i32 = 0x10;
    unsafe extern "system" {
        fn GetAsyncKeyState(key: i32) -> i16;
    }
    unsafe { (GetAsyncKeyState(VK_SHIFT) as u16 & 0x8000) != 0 }
}

#[cfg(not(windows))]
fn shift_held() -> bool {
    false
}


/// `<documents>/Prosody`, unless Documents is inside a sync client's folder.
///
/// OneDrive redirects Documents into its own tree on most Windows 11 setups.
/// Stems are large, sync clients lock files they are uploading, and a user's
/// renders should not race their cloud quota, so the default moves to
/// `<profile>/Prosody`, which no client syncs. The core applies the same rule
/// (`workspace.default_user_root`); the two must agree, because the shell is
/// what tells the core where to write (TESTING_HANDOFF P1.4).
pub fn user_root(documents: &Path) -> PathBuf {
    let sync_roots: Vec<PathBuf> = ["OneDrive", "OneDriveConsumer", "OneDriveCommercial"]
        .iter()
        .filter_map(|var| std::env::var_os(var).map(PathBuf::from))
        .collect();
    if is_cloud_synced(documents, &sync_roots) {
        if let Some(home) = home_dir() {
            return home.join(APP_DIR);
        }
    }
    documents.join(APP_DIR)
}

/// The pure rule, separated so it can be tested without touching the environment.
pub fn is_cloud_synced(path: &Path, sync_roots: &[PathBuf]) -> bool {
    let lower = path.to_string_lossy().to_lowercase();
    if sync_roots.iter().any(|root| {
        let r = root.to_string_lossy().to_lowercase();
        !r.is_empty() && lower.starts_with(&r)
    }) {
        return true;
    }
    // Split on both separators: a Windows path examined on another platform
    // (the tests) has no components, and a Windows client can be given a
    // forward-slash path by the user.
    lower
        .split(['\\', '/'])
        .any(|part| part.starts_with("onedrive") || part == "dropbox")
}

fn home_dir() -> Option<PathBuf> {
    std::env::var_os("USERPROFILE")
        .or_else(|| std::env::var_os("HOME"))
        .map(PathBuf::from)
}

#[cfg(test)]
mod cloud_tests {
    use super::*;

    #[test]
    fn a_redirected_documents_folder_is_recognised_by_the_client_root() {
        let roots = vec![PathBuf::from("C:\\Users\\marcm\\OneDrive")];
        assert!(is_cloud_synced(Path::new("C:\\Users\\marcm\\OneDrive\\Documents"), &roots));
    }

    #[test]
    fn a_plain_documents_folder_is_not() {
        let roots = vec![PathBuf::from("C:\\Users\\marcm\\OneDrive")];
        assert!(!is_cloud_synced(Path::new("C:\\Users\\marcm\\Documents"), &roots));
        assert!(!is_cloud_synced(Path::new("/home/user/Documents"), &[]));
    }

    #[test]
    fn a_onedrive_component_counts_even_without_the_variable() {
        assert!(is_cloud_synced(Path::new("D:\\OneDrive - Contoso\\Documents"), &[]));
        assert!(is_cloud_synced(Path::new("/Users/x/Dropbox/Documents"), &[]));
    }
}
