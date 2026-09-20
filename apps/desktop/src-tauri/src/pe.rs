//! Reading the machine type out of a Windows PE header.
//!
//! HARDENING P0.1 asks for an architecture guard on every binary Prosody
//! spawns. The failure it prevents is specific and has happened to this
//! project once already: a Linux build of the core was staged into the
//! Windows resource folder during packaging work. That produces an error at
//! spawn time (`%1 is not a valid Win32 application`) that says nothing about
//! the cause. Reading two fields of the header says exactly what is wrong.
//!
//! It is also the cheapest way to catch a 32-bit `FL64.exe` that is really
//! `FL.exe` renamed, which would fail far later and more confusingly.

use std::fs::File;
use std::io::{Read, Seek, SeekFrom};
use std::path::Path;

/// `IMAGE_FILE_MACHINE_AMD64`.
const MACHINE_AMD64: u16 = 0x8664;
/// `IMAGE_FILE_MACHINE_ARM64`.
const MACHINE_ARM64: u16 = 0xAA64;
/// `IMAGE_FILE_MACHINE_I386`.
const MACHINE_I386: u16 = 0x014C;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Machine {
    X64,
    Arm64,
    X86,
    Other(u16),
}

impl Machine {
    pub fn label(self) -> String {
        match self {
            Machine::X64 => "64-bit (x64)".to_string(),
            Machine::Arm64 => "64-bit (ARM64)".to_string(),
            Machine::X86 => "32-bit (x86)".to_string(),
            Machine::Other(v) => format!("unrecognised machine type 0x{v:04X}"),
        }
    }

    /// Whether this process can load it. An x64 host runs x64; an ARM64 host
    /// runs ARM64 natively and x64 under emulation, which is fine for a
    /// separate process.
    pub fn runnable_here(self) -> bool {
        matches!(self, Machine::X64 | Machine::Arm64)
    }
}

/// Read the COFF machine type from a PE file.
///
/// Returns `Err` with a plain description when the file is not a PE at all —
/// which is the interesting case, because that is what a Linux ELF binary
/// with a `.exe` name looks like from here.
pub fn machine_type(path: &Path) -> Result<Machine, String> {
    let mut file = File::open(path).map_err(|e| format!("could not read {}: {e}", path.display()))?;

    // DOS header: "MZ", then e_lfanew at offset 0x3C points at the PE header.
    let mut dos = [0u8; 2];
    file.read_exact(&mut dos).map_err(|_| "file is too short to be a program".to_string())?;
    if &dos != b"MZ" {
        return Err(describe_foreign(&dos, path));
    }

    file.seek(SeekFrom::Start(0x3C)).map_err(|e| e.to_string())?;
    let mut offset_bytes = [0u8; 4];
    file.read_exact(&mut offset_bytes).map_err(|_| "no PE header offset".to_string())?;
    let offset = u32::from_le_bytes(offset_bytes) as u64;

    file.seek(SeekFrom::Start(offset)).map_err(|e| e.to_string())?;
    let mut signature = [0u8; 4];
    file.read_exact(&mut signature).map_err(|_| "no PE signature".to_string())?;
    if &signature != b"PE\0\0" {
        return Err("not a Windows program (no PE signature)".to_string());
    }

    let mut machine = [0u8; 2];
    file.read_exact(&mut machine).map_err(|_| "truncated PE header".to_string())?;
    Ok(match u16::from_le_bytes(machine) {
        MACHINE_AMD64 => Machine::X64,
        MACHINE_ARM64 => Machine::Arm64,
        MACHINE_I386 => Machine::X86,
        other => Machine::Other(other),
    })
}

/// Name the format when it is recognisably something else, so the message
/// points at the packaging mistake rather than at the user.
fn describe_foreign(magic: &[u8; 2], path: &Path) -> String {
    let name = path.file_name().unwrap_or_default().to_string_lossy();
    if magic == b"\x7fE" {
        format!("{name} is a Linux (ELF) binary, not a Windows program - the build staged the wrong file")
    } else if magic == b"#!" {
        format!("{name} is a script, not a Windows program")
    } else {
        format!("{name} is not a Windows program")
    }
}

/// Check a binary before spawning it, returning a message fit for the UI.
pub fn check_runnable(path: &Path, role: &str) -> Result<Machine, String> {
    match machine_type(path) {
        Ok(machine) if machine.runnable_here() => Ok(machine),
        Ok(machine) => Err(format!(
            "{role} at {} is {} and cannot run on this 64-bit build of Windows.",
            path.display(),
            machine.label()
        )),
        Err(why) => Err(format!("{role} at {} cannot be used: {why}.", path.display())),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    fn write(dir: &Path, name: &str, bytes: &[u8]) -> std::path::PathBuf {
        let path = dir.join(name);
        let mut f = File::create(&path).unwrap();
        f.write_all(bytes).unwrap();
        path
    }

    /// Smallest byte sequence that is a valid-enough PE for the header read.
    fn pe_with_machine(machine: u16) -> Vec<u8> {
        let mut bytes = vec![0u8; 0x100];
        bytes[0..2].copy_from_slice(b"MZ");
        let pe_offset: u32 = 0x80;
        bytes[0x3C..0x40].copy_from_slice(&pe_offset.to_le_bytes());
        let at = pe_offset as usize;
        bytes[at..at + 4].copy_from_slice(b"PE\0\0");
        bytes[at + 4..at + 6].copy_from_slice(&machine.to_le_bytes());
        bytes
    }

    #[test]
    fn reads_an_x64_binary() {
        let dir = std::env::temp_dir().join("prosody-pe-x64");
        std::fs::create_dir_all(&dir).unwrap();
        let path = write(&dir, "a.exe", &pe_with_machine(MACHINE_AMD64));
        assert_eq!(machine_type(&path).unwrap(), Machine::X64);
        assert!(check_runnable(&path, "core").is_ok());
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn refuses_a_32_bit_binary_by_name() {
        let dir = std::env::temp_dir().join("prosody-pe-x86");
        std::fs::create_dir_all(&dir).unwrap();
        let path = write(&dir, "b.exe", &pe_with_machine(MACHINE_I386));
        let message = check_runnable(&path, "FL Studio").unwrap_err();
        assert!(message.contains("32-bit"), "{message}");
        assert!(message.contains("FL Studio"), "{message}");
        std::fs::remove_dir_all(&dir).ok();
    }

    /// The packaging mistake this guard exists for.
    #[test]
    fn names_a_linux_binary_as_the_build_error_it_is() {
        let dir = std::env::temp_dir().join("prosody-pe-elf");
        std::fs::create_dir_all(&dir).unwrap();
        let path = write(&dir, "prosody-core.exe", b"\x7fELF\x02\x01\x01\x00rest");
        let message = check_runnable(&path, "the Prosody core").unwrap_err();
        assert!(message.contains("Linux"), "{message}");
        assert!(message.contains("staged the wrong file"), "{message}");
        std::fs::remove_dir_all(&dir).ok();
    }
}
