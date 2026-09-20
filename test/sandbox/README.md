# Clean-Windows test harness

Two environments, because they answer different questions.

## Windows Sandbox — "does it start on a machine with nothing on it?"

`prosody.wsb`. No Python, Node, Rust, Git or FL Studio, and no guaranteed
WebView2. Networking is disabled in the config so the offline requirement is
tested rather than assumed.

It cannot answer anything about FL Studio, because FL Studio is not there. That
is a feature: it is the only cheap way to see the no-FL path exactly as a user
without FL sees it.

## A second local Windows account — "does it work with FL Studio?"

Everything that needs FL runs on the studio PC, in a second local account with
no dev tools on `PATH`. If a second account is impossible, run from a
PowerShell whose `PATH` has been reduced to `C:\Windows\System32`:

```powershell
$env:PATH = "C:\Windows\System32"
& "$env:LOCALAPPDATA\Programs\Prosody\Prosody.exe"
```

## Recording results

One folder per attempt under `docs/evidence/<yyyy-mm-dd>/`, containing whatever
you actually saw: screenshots, the System Check report (Settings → System check
→ Copy report), and `%LOCALAPPDATA%\Prosody\Logs\core.log` if anything failed.

A step is only WORKING in `CURRENT_STATUS.md` if there is evidence here for it.
