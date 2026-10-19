# Phase 1 — AutoCAD Headless Sanity: Design

## 1. Overview
```
mta run MyTools.msi --listing listing.yaml
   │
   ├─ intake ─────────── Submission, SHA-256, artifact store (./mta-data/artifacts)
   ├─ static ─────────── extract → bundle/manifest → mta-inspect (C#) → signing → Defender → listing
   │                       └── produces: PackageInfo (components, commands, frameworks, gui_required…)
   ├─ plan ───────────── versions = declared ∩ installed ; runs = [(autocad, v, headless)]
   ├─ for each run:
   │    baseline launch (probe only) ─► if fails → all dynamic = ERROR
   │    batch run (load → enumerate → smoke) ─► anomaly? → per-command isolation
   │    scenario runs (one process per scenario)
   ├─ engine ─────────── probe events + console logs + dumps → CheckResults (rules)
   └─ report ─────────── report.json (schema-validated) + report.html
```

## 2. Modules (`src/mta`)
| Module | Key types / functions |
|---|---|
| `cli/` | Typer app: `run`, `inspect`, `doctor`, `scenario new`, `corpus run`, `report open` |
| `intake/` | `build_submission(path, listing) -> Submission`, `ArtifactStore.put(bytes|path) -> ArtifactRef` |
| `static/extract.py` | `safe_extract_zip`, `extract_package -> PackageExtraction` (payload + PKG-001…003 results) |
| `static/msi.py` | `msi_read_tables` (ctypes on `msi.dll`, read-only; `msilib` is gone from Python 3.13), `custom_action_inventory`, `msi_admin_extract` (`msiexec /a /qn`, guarded, see §2.1) |
| `static/bundle.py` | `find_bundles`, `parse_package_contents -> BundleManifest` (defusedxml), `component_versions` (per-component RuntimeRequirements → host versions) |
| `static/bundle_checks.py` | `analyze_bundle` → PKG-004…006, MAN-001…007, `bundle.json` |
| `static/stage.py` | `run_static_stage`: extraction → bundle → inspection; writes the job's `checks/static-*.json` |
| `intake/prefill.py` | `kit init` pre-fill from the manifest (no `msiexec` before the malware scan) |
| `static/dotnet.py` | Wraps `mta-inspect.exe` → `AssemblyReport` (Pydantic, contract-checked) |
| `static/binary_checks.py` | `analyze_binaries` → BIN-001…009, CMD-003, MAN-005; `inspection.json` with the per-component GUI classification |
| `static/native.py` | `pefile`-based PE machine and import table reading for ARX/DBX/CRX (`acdbNN.dll` → API major) |
| `static/signing.py` | Calls PowerShell `Get-AuthenticodeSignature` (JSON out) per file |
| `static/malware.py` | `MpCmdRun.exe -Scan -ScanType 3 -File <dir> -DisableRemediation` and parses the exit code / output |
| `static/listing.py` | HTTPS GET of the privacy URL (no redirect to http), MX lookup (`dnspython`) |
| `adapters/base/` | Contract `Protocol`s from [host-adapter-contract.md](../00-foundation/host-adapter-contract.md) |
| `adapters/autocad/` | `AutoCadAdapter`, `ScriptBuilder`, `CoreConsoleRunner`, `ConsoleLogParser` |
| `engine/` | `rules/*.py`: one function per check ID, mapping facts to `CheckResult`; `recommend()` |
| `scenario/` | DSL parser (pydantic models), AutoCAD step translator |
| `report/` | `json_writer`, Jinja2 `report.html.j2`, embedded CSS/JS (no CDN) |
| `corpus/` | Runner, comparator, metrics |

### 2.1 Package extraction (P1-R04)
The payload goes to `jobs/<job>/payload/`. Every file in it is hashed and stored, and listed in `payload-files.json`. Results are written to `checks/static-package.json`.

| Kind | PKG-001 (safe extraction) | PKG-002 (payload) | PKG-003 (MSI admin extract) |
|---|---|---|---|
| `.bundle` folder | Links are already rejected by kit validation; the folder is copied | bundle present | SKIPPED |
| ZIP | `safe_extract_zip`, with declared and actual limits; on failure the partial output is deleted | `*.bundle` or a payload extension | SKIPPED |
| MSI | The limits are applied to the admin-extracted tree | same rule | PASS / FAIL (msiexec error) / NEEDS_REVIEW (admin custom actions) / ERROR (busy, timeout, policy) |

**MSI custom-action types:** the base type is `Type & 7`.
- Code-executing types: 1 DLL, 2 EXE, 5 JScript, 6 VBScript, 7 nested install.
- Base type 3 (data only): 19 error, 35 set directory, 51 set property.

`msiexec /a` runs only when no code-executing action is scheduled in `AdminExecuteSequence` or `AdminUISequence`. Running `/qn` skips the UI sequence anyway. The `InstallExecuteSequence` actions do not run during an admin install, but they are inventoried, because Phase 2 runs the real install in the sandbox.

**msiexec exit codes:**

| Exit code | Result |
|---|---|
| 0, 3010 | PASS |
| 1618 (busy), 1625 (policy), timeout | ERROR |
| anything else | FAIL, with the tail of the verbose log as evidence |

## 3. mta-inspect (C# CLI, `dotnet/src/MtaInspect`)
- Built for .NET 8. Uses `System.Reflection.Metadata` + `PEReader`. **No `Assembly.Load`.**
- Usage: `mta-inspect <file>...`, `--files-from <list>` (used by `static/dotnet.py`), `--enum <dll> <Type>` (dumps an enum's constants, e.g. `CommandFlags` → `data/autocad/2026/commandflags.json`), `--version`. Per-file problems are reported in `error`; the exit code stays 0.
- Output: a JSON array of `AssemblyReport`. The contract is `Report.cs`, mirrored by the Pydantic model in `static/dotnet.py` with `extra="forbid"`, so drift fails loudly:
```json
{"path":"…","is_managed":true,"machine":"I386","architecture":"anycpu","mixed_mode":false,
 "assembly_name":"MyTools","assembly_version":"2.3.0.0","target_framework":".NETCoreApp,Version=v8.0",
 "references":[{"name":"AcDbMgd","version":"25.0.0.0"}],
 "commands":[{"global_name":"ACME_DIMALL","local_name":null,"group":"ACME","flags":2,"type":"Acme.Tools.Commands","method":"DimAll","registered":true}],
 "lisp_functions":[],"command_classes":["Acme.Tools.Commands"],"extension_app_attributes":["Acme.Tools.App"],
 "extension_app_types":["Acme.Tools.App"],"pinvokes":[{"dll":"user32.dll","entry":"FindWindowW"}],
 "urls":["https://api.acme.example/v1"],"type_refs":["…"],"member_refs":["System.Diagnostics.Process::Start"],
 "obfuscation":{"suspected":false,"signals":[]},"error":null}
```
- **Command discovery:** decodes `CustomAttribute` blobs whose constructor type is `Autodesk.AutoCAD.Runtime.CommandMethodAttribute`, for every overload. The leading strings are `(global)`, `(group, global)` or `(group, global, localId)`; the first Int32 is `CommandFlags`. If `[assembly: CommandClass]` is present, commands in other types get `registered: false`, because AutoCAD only scans the listed types.
- **Flags:** the raw value is decoded in Python through `hosts.yaml` `command_flags_file`. That table was read from `AcCoreMgd.dll` metadata (ADR-0003 F27).
- **Risky APIs and URLs:** `mta-inspect` reports all member references, type references and user-string URLs. Which ones are risky is policy: `config/static_rules.yaml`.
- **Obfuscation:** a strong signal is an obfuscator marker type. Weak signals are more than 30% unreadable or 1–2 character names, and a module initializer. "Suspected" means one strong signal or two weak ones. A suspected file's other static results get confidence 0.6.
- **Tests:** xUnit tests use fixtures (`dotnet/tests/fixtures`), including a fake `AcCoreMgd` with the real type names, so CI needs no AutoCAD.

## 4. Version compatibility rules (BIN-001/002)
From `hosts.yaml`:
- Runtime: `net48` hosts accept `.NETFramework,Version=v4.x` (x ≤ 8). `net8.0-windows` hosts accept `.NETCoreApp,Version=v8.0` and **reject** .NET Framework assemblies that reference AutoCAD APIs.
- API major version: `AcDbMgd` reference major `24` → R24.x (2021–2024), `25` → R25.x (2025+). A reference major greater than the host's major is a FAIL. A lower major across the R24→R25 boundary is a FAIL (binary break). Within the same major it is a PASS.
- ARX: import `acdbNN.dll` where NN must equal the host major.

## 5. AutoCAD adapter

### 5.1 Run directory layout
```
runs/<run_id>/
  profile/                 ← isolated user profile root
  plugin/                  ← bundle copy (deployment folder; used for exception attribution)
  probe/                   ← MtaProbe.AutoCAD.dll (net48 or net8 build per version)
  probe-plan.json
  probe-events.ndjson
  console.stdout.log       ← raw AcCoreConsole output (UTF-16 decoded)
  scripts/*.scr
  artifacts/
  dumps/
```

### 5.2 AcProbe (`src/probes/AcProbe`, multi-target `net48;net8.0-windows`)
- References only `AcCoreMgd` and `AcDbMgd` (core-console safe). It implements `IExtensionApplication`.
- On `Initialize`, it reads `MTA_RUN_DIR`, opens the event writer and hooks:
  - `AppDomain.AssemblyLoad` → `assembly.load`;
  - `AppDomain.UnhandledException` → `exception.unhandled`;
  - `AppDomain.FirstChanceException`, filtered to assemblies under `plugin/` → `exception.first_chance` (rate-limited) and a per-command exception buffer;
  - `Application.DocumentManager` / `DocumentCollection.DocumentLockModeChanged` + `Editor` prompt events (`PromptingForString`, `…Point`, `…Selection`, `…Keyword`, …) → `prompts_seen`;
  - `Document.CommandWillStart` / `CommandEnded` / `CommandCancelled` / `CommandFailed` → command outcome.
- Commands exposed by the probe (prefixed so they cannot collide):

| Command | Action |
|---|---|
| `MTAPROBE_LOAD` | For each component in the plan: .NET → `ExtensionLoader.Load(path)`; ARX → `SystemObjects.DynamicLinker.LoadModule(path, false, false)`. Wraps each load in try/catch with timing → `component.load.*` events. LISP components are loaded by script lines (`(load "…")`) that the probe brackets with markers. |
| `MTAPROBE_ENUM` | Emits `command.registered` for each expected command that is defined. Definition test: `(getcname "<name>")` evaluated via script, plus the internal API if the spike confirms it (P1-Q05). |
| `MTAPROBE_MARK` | `MTAPROBE_MARK <begin|end> <command>`: brackets smoke invocations in the event stream. |
| `MTAPROBE_ASSERT` | Executes one scenario assertion (entity counts via a model-space iteration in a read transaction, layer/block table lookups, sysvar). |
| `MTAPROBE_END` | Flushes and emits `probe.shutdown`. |

### 5.3 ScriptBuilder (generated `.scr`)
Batch smoke script (conceptual; facts from [ADR-0003](../adr/ADR-0003-accoreconsole-for-phase-1.md) findings F3–F7, F13, F18):
```
FILEDIA 0
CMDECHO 1
(setvar "TRUSTEDPATHS" "<run>/plugin/...;<run>/probe")   ; F13: keep SECURELOAD=1
NETLOAD
<run>\probe\<probe>.dll                     ; probe FIRST (F11: catches Initialize exceptions)
NETLOAD
<run>\plugin\...\MyTools.dll                ; one NETLOAD per .NET component
(load "<run>/plugin/.../tool.lsp")          ; per LISP component, bracketed by MARK
MTAPROBE_ENUM                               ; + (getcname "<cmd>") per expected command (F18)
MTAPROBE_MARK begin ACME_DIMALL
ACME_DIMALL
<smoke.inputs lines, default none>          ; optional answers from scenario / features
(command)                                   ; F5: cancels any active prompt, harmless otherwise
(command)
MTAPROBE_MARK end ACME_DIMALL
…
MTAPROBE_END
QUIT
Y                                           ; F7
```
Rules:
- The script is written with **LF line endings only** (F3).
- **Never** use bare blank lines as "Enter" after a command: at `Command:` they repeat the previous command (F4).
- `TRUSTEDPATHS` is used instead of `SECURELOAD 0`, so the security behaviour matches what customers see (F12, F13).
- `.NET` components are loaded with `NETLOAD` (`/loadmodule` does not load .NET, F15). The probe's `MTAPROBE_LOAD` (via `ExtensionLoader.Load`) remains an option if timing per component is needed.

### 5.4 CoreConsoleRunner
- Command: `accoreconsole.exe /i <sample.dwg> /s <script.scr> /product ACAD /l en-US /isolate <user> <run>\profile` (switches confirmed by spike, F1). `/product ACAD` alone does not prevent vertical modules from loading on machines with verticals installed (F17). The baseline launch records which modules load.
- Environment: `MTA_RUN_DIR`. stdin closed. Closing stdin does **not** end a waiting prompt (F6), so the watchdog is mandatory.
- Watchdog: per-script timeout = Σ(per-step timeouts) + startup allowance. On expiry it kills the process tree (`psutil`).
- Captures stdout to `console.stdout.log`. AcCoreConsole writes UTF-16LE, so the runner decodes it.
- Crash detection: exit code ≠ 0, a missing `probe.shutdown`, or a new file in `dumps/` (WER LocalDumps for `accoreconsole.exe`, configured by `mta doctor --fix`).

### 5.5 Smoke strategy
1. **Batch** all commands in one process (fast path).
2. If the batch shows an anomaly, the runner determines the last `MARK begin` without a matching `end`, attributes the anomaly to that command, and starts **per-command** processes for the commands that remain. Anomalies are: crash, timeout, or event-sequence gap.
3. Outcome classification per command:

| Signals | Outcome |
|---|---|
| `end` marker, `CommandEnded`, no plugin exception | `completed` |
| `CommandCancelled` by our `(command)` after ≥1 prompt event | `awaiting_input` (PASS: interactive, needs scenario coverage) |
| `CommandCancelled` / `CommandFailed` without plugin exception and without prompts | `cancelled` (PASS) |
| Plugin first-chance exception, then process exit `0xC0000005` (F8) | `exception` (CMD-002 FAIL, stack from probe) |
| Plugin first-chance exception, process continues | `exception` (caught by plugin? → WARN if repeated, RUN-005) |
| Killed by watchdog, no prompt active | `timeout` (CMD-004) |
| Process exit `0x80131623` (FailFast, F9) or other non-zero exit without plugin exception | `crash` (RUN-001) |

A **script abort** is detected when the process exits (code 0 included, F22) while `MARK begin` / `end` pairs are missing for later commands. The last command with `begin` but no `end` gets outcome `aborted_script` (PASS + note "cancelling this command ends the script: it runs native commands internally"). The remaining commands are re-run in a new process.

Because an unhandled exception in a command **terminates the core console** (F8), a batch run ends at the first failing command. The runner then starts a new process for the commands that remain (§5.5 step 2). This is the expected path, not an edge case.

### 5.6 Baseline launch
For each version, the runner starts the probe only, without the plugin. If this fails, every dynamic check for that version is `ERROR` with the reason `baseline failed`, and the console log excerpt is attached as evidence. The runner also records a licence-error detection (regex list in `data/autocad/console_errors.yaml`).

### 5.7 Exception attribution
A stack frame belongs to the plugin if its module path is under `runs/<id>/plugin/`. For console-only exception text, the runner matches type names against the namespaces discovered by mta-inspect.

## 6. Check engine
- Each rule is a pure function: `def check_cmd_002(facts: RunFacts, cfg: CheckCfg) -> list[CheckResult]`.
- `RunFacts` is assembled from the parsed events, console log, dump list and `PackageInfo`.
- Severity defaults come from [check-catalog.md](../00-foundation/check-catalog.md), and `config/checks.yaml` can override them.
- Unit tests feed recorded `probe-events.ndjson` fixtures. No AutoCAD is needed in CI.

## 7. Reporting
- `report.json` is validated against `schemas/report.schema.json` before it is written.
- `report.html` is a single file with inline CSS/JS, and works offline. It has these sections:
  1. Banner: recommendation, reasons, app, version, duration.
  2. Matrix: version × family status chips.
  3. Findings: FAIL / NEEDS_REVIEW first, each expandable with evidence.
  4. Command table: rows are commands; columns are versions, showing the outcome and duration.
  5. Package inventory: components, frameworks, signatures, URLs.
  6. Raw logs: links.

## 8. Configuration files
```yaml
# config/thresholds.yaml
coreconsole: {startup_timeout_s: 90, quit_timeout_s: 30}
load: {per_component_warn_s: 5, per_component_timeout_s: 60}
smoke: {per_command_timeout_s: 20, cancel_lines: 2, batch: true}   # cancel_lines = "(command)" lines after each command (F5)
scenario: {default_timeout_s: 120}
extract: {max_bytes: 2147483648, max_files: 20000, max_compression_ratio: 100, ratio_min_bytes: 1048576, msi_timeout_s: 300}
```

## 9. Error handling
| Situation | Behaviour |
|---|---|
| Probe fails to load | All dynamic checks for the version → `ERROR`. Report suggests running `mta doctor`. |
| Licence prompt detected in console | `ERROR` (D-LIC) |
| Sample drawing missing | Scenario → `SKIPPED` |
| mta-inspect crash on an assembly | That assembly's BIN-* → `ERROR`; other checks continue |

## 10. Security (Phase 1)
- Follow the [security-and-isolation.md](../00-foundation/security-and-isolation.md) §3 guardrail.
- The dynamic phase is gated on SIG-003 `PASS`.
