//! WebView2 runtime detection.
//!
//! Tauri renders through Edge WebView2. Windows 11 always has it; some
//! Windows 10 machines do not. The installer embeds the bootstrapper, but the
//! portable ZIP cannot install anything — so it has to detect the absence and
//! say so, because without this the window opens completely blank and looks
//! like the app is broken.

#[cfg(windows)]
pub const DOWNLOAD_URL: &str = "https://go.microsoft.com/fwlink/p/?LinkId=2124703";

/// Whether the WebView2 runtime is installed for this machine or this user.
#[cfg(windows)]
pub fn is_installed() -> bool {
    use winreg::enums::{HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE, KEY_READ, KEY_WOW64_32KEY};
    use winreg::RegKey;

    // The runtime registers a per-machine key (32-bit view) and, for per-user
    // installs, the equivalent under HKCU.
    const CLIENTS: &str =
        r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}";

    let machine = RegKey::predef(HKEY_LOCAL_MACHINE)
        .open_subkey_with_flags(CLIENTS, KEY_READ | KEY_WOW64_32KEY);
    let user = RegKey::predef(HKEY_CURRENT_USER).open_subkey(CLIENTS);

    for key in [machine, user].into_iter().flatten() {
        if let Ok(version) = key.get_value::<String, _>("pv") {
            if !version.is_empty() && version != "0.0.0.0" {
                return true;
            }
        }
    }
    false
}

#[cfg(not(windows))]
pub fn is_installed() -> bool {
    // Every other platform uses the system webview, which is always present.
    true
}

/// Tell the user, in a native dialog, that the runtime is missing.
#[cfg(windows)]
pub fn warn_and_exit() -> ! {
    use std::process::Command;
    use std::os::windows::process::CommandExt;

    let message = format!(
        "Prosody needs the Microsoft Edge WebView2 runtime, which is not \
         installed on this computer.\n\n\
         Install it from:\n{DOWNLOAD_URL}\n\n\
         Then start Prosody again."
    );
    // mshta shows a message box without pulling in a UI crate.
    let script = format!(
        "javascript:var s=new ActiveXObject('WScript.Shell');\
         s.Popup(\"{}\",0,\"Prosody\",0x30);close()",
        message.replace('"', "'").replace('\n', "\\n")
    );
    let _ = Command::new("mshta")
        .arg(script)
        .creation_flags(0x0800_0000)
        .status();
    std::process::exit(1);
}

#[cfg(not(windows))]
pub fn warn_and_exit() -> ! {
    eprintln!("A system webview is required.");
    std::process::exit(1);
}
