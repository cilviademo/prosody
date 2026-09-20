//! Where Prosody reads and writes on this machine.
//!
//! Two roots, decided here and handed to the core through the environment so
//! there is exactly one place that knows the policy:
//!
//! * documents — `%USERPROFILE%\Documents\Prosody` — the user's exports
//! * state     — `%LOCALAPPDATA%\Prosody` — database, settings, cache, logs
//!
//! Portable mode collapses both into `Data\` beside the executable, so a copy
//! on a USB stick writes nothing to the host profile.

use std::path::PathBuf;

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
            documents: documents_dir().join(APP_DIR),
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
