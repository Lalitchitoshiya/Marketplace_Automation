# ADR-0003: AcCoreConsole as the Phase 1 AutoCAD runtime

**Status:** Accepted (v0.2): spike P1-T03 done, findings below · **Date:** 2026-10-19

## Context
Phase 1 must demonstrate automated sanity testing quickly, on one workstation. Full `acad.exe` automation needs UI handling: dialogs, ribbon, focus. That work is considerably larger.

## Decision
Use `accoreconsole.exe`, AutoCAD's headless console:
- it starts quickly;
- it is script-driven;
- it has no UI to manage.

Its limitations are accepted and made explicit in the report:
- Components depending on UI assemblies (`AcMgd`, `AdWindows`, WPF / WinForms) cannot load. These are classified as GUI-required (BIN-008). A headless load failure caused by a UI dependency → `NEEDS_REVIEW`, not `FAIL`.
- Ribbon, dialogs and the autoloader in GUI mode are deferred to Phase 2.

## Spike P1-T03 must confirm (append findings below)
- Command-line switches per version (`/i`, `/s`, `/l`, `/isolate`, `/product`).
- Behaviour on stdin EOF at an active prompt.
- Autoloader behaviour for ApplicationPlugins bundles in the core console.
- `TRUSTEDPATHS` handling from script.
- Exit codes and WER dump behaviour on crash.
- Output encoding.
- Unattended licensing behaviour.

## Findings (spike run 2026-10-19, AutoCAD 2026 W.164.0.0, .NET 8.0.30)

Spike code and raw results: `spikes/p1-t03-accoreconsole/` (`run_spike.py`, `runs/<experiment>/`).

| # | Topic | Finding | Design impact |
|---|---|---|---|
| F1 | Switches | `/i /s /product /l /isolate <userid> <userDataFolder> /readonly /p /loadmodule /supportfilesmap`. `/?` does **not** print and exit; it starts a session. | `hosts.yaml` switches confirmed. `mta doctor` must not call `/?`. |
| F2 | Output encoding | stdout is **UTF-16LE**. | Runner decodes UTF-16LE. |
| F3 | Script line endings | With CRLF, CR and LF each act as Enter. The extra Enter **repeats the previous command** and corrupts the script. | ScriptBuilder writes **LF only**. |
| F4 | Enter at `Command:` | A blank line at `Command:` repeats the last command. | "N × Enter" smoke inputs are **unsafe**. Replaced by F5. |
| F5 | Cancelling | AutoLISP `(command)` typed at an active prompt cancels the command like ESC (`CommandCancelled` fires, `GetString` → `Cancel`). At `Command:` it is harmless (`nil`). | **Smoke pattern = `<CMD>` followed by `(command)` lines.** No stuck prompts, no repeats. |
| F6 | Script EOF at a prompt | Process **waits forever** (stdin closed does not end it). | Watchdog mandatory. Every script ends with `QUIT` / `Y`. |
| F7 | Quit | `QUIT` → "Really want to discard all changes to drawing? <N>" → `Y` → exit code 0. | Standard script tail. |
| F8 | Exception in a command | Unhandled .NET exception **crashes the process**: exit code `0xC0000005`, no text in console. `FirstChanceException` (filtered to plugin assembly) fires just before. `UnhandledException` does **not** fire. | Exception evidence comes from the probe's first-chance hook. Exit `0xC0000005` after a plugin first-chance exception ⇒ `exception` outcome (CMD-002), not a generic crash. Batch run must continue the remaining commands in a new process. |
| F9 | `Environment.FailFast` | Exit code `0x80131623` (COR_E_FAILFAST). | Map to `crash`. |
| F10 | Hanging command | No output; killed by watchdog. | `timeout` outcome (CMD-004). |
| F11 | Exception in `IExtensionApplication.Initialize` | **No crash and no console message.** The assembly's commands are silently not registered ("Unknown command"). | LOD-001 must use the probe's first-chance hook **and** CMD-001 (commands missing). The probe must be loaded **before** the plugin. |
| F12 | `SECURELOAD` default (1), plugin in untrusted folder | `Unable to load … assembly.` with no prompt, the same text as a genuine failure. | Never leave the plugin folder untrusted. Use F13. |
| F13 | `TRUSTEDPATHS` | `(setvar "TRUSTEDPATHS" "<dir>")` from script works with `SECURELOAD=1`. | ScriptBuilder sets `TRUSTEDPATHS` to the plugin + probe folders (realistic security). |
| F14 | UI assembly (`AcMgd`) plugins | **Load and run in the core console.** `Application.ShowAlertDialog` is logged as `MessageBox` and auto-answered `OK`. | BIN-008 is **not** a load blocker for `AcMgd`. Keep GUI-required classification only for ribbon / WPF / WinForms / palette usage (`AdWindows`, `PaletteSet`, etc.); to be confirmed with a ribbon spike in Phase 2. Message boxes appear as `MessageBox` blocks in console output and are parsed as evidence. |
| F15 | `/loadmodule` with .NET DLL | Does not load .NET assemblies. | Use `NETLOAD` from script. |
| F16 | Autoloader | Bundle in `%APPDATA%\Autodesk\ApplicationPlugins` with `APPDATA` **redirected** to the run folder: not loaded (`APPAUTOLOAD=14`). **Inconclusive**: redirection may not be honoured. | Phase 1 keeps explicit loading. Re-test with real ApplicationPlugins folders on the dedicated test machine. |
| F17 | `/product ACAD` | Did **not** prevent Civil 3D (AECC) modules loading or the C3D template on this machine. | Test machine needs plain AutoCAD (or a profile / template override). Record loaded modules in the baseline launch. |
| F18 | Command existence | `(getcname "X")` returns `_X` if defined, `nil` if not. No public internal `IsCommandDefined` API found. | CMD-001 uses `getcname` (answers P1-Q05 / step 3 lookup method). |
| F19 | Events | `CommandWillStart/Ended/Cancelled/Unknown` and `Editor.PromptingFor*` all fire in the core console. | Probe design confirmed. |
| F20 | Performance | Full start → load → commands → quit: **5–11 s**. Isolation profile creation ≈ 3.7 s. | Per-command isolation is affordable (~6 s / command). |
| F21 | Licensing | Runs worked under the signed-in user with an isolated profile. No licence prompt. Unattended / no-login behaviour **not tested**. | Still open (D-LIC). |
| F22 | Cancelling a **native** command with `(command)` | Cancels the command **and aborts the rest of the script**. AutoCAD then exits with code 0. (With a .NET command's prompt, the script continued: F5.) | Exit 0 is **not** proof of success. The runner uses begin/end markers to find commands that never ran and re-runs them in a new process. Plugin commands that call native commands may trigger this. |
| F23 | Script ends while idle at `Command:` | Process exits by itself with code 0. It waits forever only when a prompt is still active (refines F6). | `QUIT` kept for clarity; watchdog still mandatory. |
| F24 | Command-name collision | A plugin `[CommandMethod("LINE")]` loads with **no warning**. `getcname "LINE"` is unchanged, and typing `LINE` runs **AutoCAD's** LINE: the plugin's command is unreachable. | CMD-003 is a real defect (dead feature). It is detected statically (name in built-in list) **and** at runtime (`getcname` of each plugin command in the baseline launch, before the plugin loads). |
| F25 | Built-in command list | No public or internal API to enumerate commands was found (reflection search returned nothing). `getcname` only knows commands registered in the core console. Demand-loaded and GUI-only commands (`ALIGN`, `APPLOAD`, `ADCENTER`, …) return `nil`. | List = `getcname`-verified candidates from `acad.pgp` + `acad.CUIX` **∪** all `acad.pgp` alias targets → **506 names** for 2026 (`spikes/p1-t04-commands/data/commands-2026.txt`). Not exhaustive; the runtime check in F24 covers the rest. |
| F26 | Command-list generation time | Verifying 935 candidates via one LISP loop: 8–16 s. | Regenerate per version and per image automatically (`mta data gen-commands`). |
| F27 | Compiled references of `SpikeUiPlugin` (step 9, `mta-inspect`) | The project references `AcMgd`, but the DLL only references `accoremgd` and `Acdbmgd`: in AutoCAD 2026 `ApplicationServices.Application` (including `ShowAlertDialog`) binds to `accoremgd`. A project reference leaves no trace unless its types are used. `CommandFlags` values read from `AcCoreMgd.dll` metadata match the documented enum (`data/autocad/2026/commandflags.json`). | BIN-008 classifies from the **compiled** references and type references, never from project files. `SpikeUiPlugin` is correctly core-console compatible (consistent with F14). |
| F28 | `/isolate` with a long run folder (step 11) | Fails at startup: `Copying folder failed (source: …\Roaming\Autodesk\C3D 2026\enu\ …)` then `Failed to create registry keys or files necessary when using the /isolate switch`, exit 1. The copy includes vertical products' deep roaming trees and overflows MAX_PATH. A 138-character root fails; a 36-character root works. The key name format does not matter. | The runner refuses roots longer than `coreconsole.max_profile_path` (80) with a clear error; the default `.mta\` data dir is short. The dedicated test machine should use a short root such as `C:\mta\`. |
| F29 | Crash of `accoreconsole.exe` (step 11 crash test, `SPK_THROW`) | Autodesk's own crash reporter (`CER\senddmp.exe`, `cer_service`) opens an **interactive "Autodesk Civil 3D 2026 Error Report" dialog** on the desktop. It is branded Civil 3D because the core console loads the installed vertical's modules (F17). It says a limited set of crash data is sent to Autodesk. | Unattended runs must not leave dialogs waiting on the desktop or send crash reports about plugins under review (Constitution §11). Step 12 must find a verified way to suppress CER for test runs, or to close it reliably, and add `senddmp.exe` to the runner's cleanup. **Resolved in step 12, verified live:** the chain is `accoreconsole.exe` → `senddmp.exe <pid> <id>` → `cer_dialog.exe --option-file <profile>\Temp\…`. The runner polls the console's descendants every 0.25 s and kills `senddmp.exe` as soon as it appears (before `cer_dialog` opens); after exit it sweeps for `senddmp.exe <console-pid>`. Crash run: `senddmp.exe` killed, no dialog, `0xC0000005` still reported. No documented switch to disable CER was found (the registry holds only usage counters). Whether the upload is fully prevented is unverified, so the network-isolated test VM remains the real guarantee. |
| F30 | Console after a crash, with the crash reporter suppressed (step 12, 4 + 6 repeated runs) | The plugin exception is captured within a second, but the crashed `accoreconsole.exe` often does not exit: 1 of 4 runs waited until the 90 s watchdog, and with a 10 s grace 5 of 6 had to be ended. It apparently waits for the reporter it started. | Once the crash reporter has appeared, the runner allows `coreconsole.crash_exit_grace_s` (10 s), then ends the process tree and records `terminated_after_crash`. The run counts as a crash (`ConsoleRun.crashed`), never as a timeout. Crash runs now take 11–19 s instead of up to the watchdog limit. |
| F31 | AutoCAD 2027 (step 12) | Installed on this machine. `ACADVER` = `26.0`, runtime .NET `10.0.11`, `AcCoreMgd`/`AcDbMgd`/`AcMgd` 26.0.0.0 targeting .NET 10, so the R26 API major is a binary break from R25. The deep doctor check passes every ADR behaviour on 2027 as on 2026. `AcCoreMgd` has an attribute with a null `System.Type` argument, which crashed `mta-inspect` (fixed). | `hosts.yaml` 2027 marked verified. The probe, canary and synthetic plugins are built per API major (`bin/acad25`, `bin/acad26`) by `mta probe build` / `mta corpus build`. |