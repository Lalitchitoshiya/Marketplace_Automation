# Phase 2 — AutoCAD Complete: Design

## 1. Deployment view
```
┌──────────────────────────── Control plane (Linux or Windows server) ─────────────────────────┐
│ FastAPI (REST + OIDC) ─ PostgreSQL (jobs, runs, results, overrides) ─ Redis + RQ/Celery queue │
│ Dashboard (FastAPI + Jinja2 + HTMX, video.js)       Artifact store (Blob/S3, SHA-256 keys)     │
│ Scheduler: image capacity, licence seats, priority                                            │
└───────────────┬──────────────────────────────────────────────────────────────────────────────┘
                │ gRPC/HTTPS (mTLS)
┌───────────────▼────────────── Hyper-V host(s) ───────────────────────────────────────────────┐
│ mta-hostd (Windows service)                                                                   │
│   ├─ VM pool manager  (New-VM from image, Checkpoint-VM, Restore-VMSnapshot)                  │
│   ├─ PowerShell Direct session to guest (no guest network needed)                             │
│   └─ Copy-VMFile in / Copy-Item -FromSession out                                              │
│                                                                                               │
│   VM (acad2026-win11-vN) ── vSwitch "mta-isolated" ── egress gateway (DNS log + proxy) ─ LIC  │
│     mta-agent (python, invoked per Run via PS Direct)                                         │
│     AutoCAD 2026 · MtaProbe.bundle (GUI+core) · Sysmon · ffmpeg · FlaUI runner                │
└───────────────────────────────────────────────────────────────────────────────────────────────┘
```

## 2. Image pipeline
- **Packer** (Hyper-V builder) + PowerShell provisioning, in `infra/images/<image>/`:
  - Windows 11 Enterprise LTSC (or 11 Ent) with updates frozen per image version;
  - Autodesk product silent install using Autodesk deployment packages, plus the update/hotfix list;
  - Sysmon with `infra/sysmon/mta-sysmon.xml`;
  - .NET runtimes, Python, mta-agent, ffmpeg, FlaUI runner;
  - MtaProbe bundles;
  - sample library;
  - WER LocalDumps configured for `acad.exe`, `accoreconsole.exe` and `msiexec.exe`;
  - Defender real-time protection **on**. This is deliberate: it catches what customers would hit.
- After provisioning, the pipeline warms the host once (first-run completed, licence activated) and creates the `clean` checkpoint.
- **Image smoke test:** run the SD-01 conformance plugin. The image is published only if green.

## 3. Run sequence (GUI, per version)
```
hostd: acquire VM → Restore-VMSnapshot clean → start → wait agent ready (PS Direct)
copy: package, run plan, scenarios → C:\mta\run\
agent:
  1 snapshot FS+registry (scoped: ProgramData, Program Files, %APPDATA%, %LOCALAPPDATA%, HKLM\SOFTWARE, HKCU\Software)
  2 start Sysmon session marker, ffmpeg recording
  3 baseline GUI launch (no plugin) → UI baseline, startup time, activity baseline  [cached per image version]
  4 msiexec /i /qn /l*v  → INS-*
  5 launch acad.exe /nologo /p <isolated profile> [/product X] with LOGFILEMODE=1
  6 probe: wait host.ready → load report (autoloader) → enumerate commands → UI inventory
  7 smoke (GUI): per command via probe (SendStringToExecute + prompt cancel) with dialog watcher
  8 UI exercise: per ribbon item → probe-invoke; per panel ≥1 → FlaUI real click
  9 scenarios (gui/any)
 10 AUDIT → CMD-005; resource samples → RUN-004
 11 quit → RUN-003; collect dumps, logs, Sysmon EVTX, video, screenshots
 12 msiexec /x /qn → UNI-001; snapshot diff → UNI-002; relaunch host → UNI-003
copy out artifacts → hostd → artifact store
hostd: power off → Restore-VMSnapshot clean → return to pool
```

## 4. Probe in GUI mode (`MtaProbe.AutoCAD.Gui`)
- References `AcMgd` and `AdWindows` in addition to the core probe.
- **Load ordering** (P2-Q01): primary approach is registry demand-load (`LOADCTRLS=2`, load on startup) for the probe. The probe also scans `AppDomain.GetAssemblies()` on init to retro-record assemblies loaded earlier. The command-line log (`LOGFILEMODE`) captures autoloader error messages as secondary evidence.
- **Ribbon inventory:** `Autodesk.Windows.ComponentManager.Ribbon.Tabs` → `Panels` → `Source.Items` (recursive for split buttons and rows). Each item records: `Id`, `Text`, `CommandParameter`, the command handler type, whether it has an image, and its automation ID. The inventory is diffed against the baseline inventory (P2-R10).
- **Other UI:** CUIx partial menus loaded (via `Application.MenuGroups`), palette sets (`PaletteSet` created after load: hook via a window-creation watcher in FlaUI), context menus (`Application.AddDefaultContextMenuExtension` cannot be enumerated → static detection from mta-inspect references).
- **Invocation:** `doc.SendStringToExecute("<cmd> ", true, false, false)` from the application context. A prompt watcher cancels active prompts after `smoke.prompt_cancel_after_s` by posting `\x03\x03` (ESC ESC) through `SendStringToExecute` on the next idle, or through FlaUI key input.

## 5. Dialog watcher (FlaUI runner, out-of-process)
- Subscribes to UIA `WindowOpened` for the acad process tree.
- For each new top-level or modal window:
  1. Wait for render (≥500 ms stable).
  2. Take a screenshot.
  3. Run a blank check (pixel variance).
  4. Emit `dialog.shown`.
  5. Classify the window:
     - an error dialog (`Unhandled exception`, `.NET Framework`, `Error`, `FATAL ERROR`);
     - an add-in load error;
     - a nag dialog;
     - the plugin UI.
  6. Close it: Cancel → Esc → close button, in that order.
- Classification uses title/text regexes in `data/autocad/dialogs.yaml`.

## 6. Behaviour monitoring
- **Sysmon events** used:
  - 1 (process create);
  - 3 (network connect);
  - 11 / 23 (file create / delete);
  - 12 / 13 / 14 (registry);
  - 22 (DNS query).
- Collection: export `Microsoft-Windows-Sysmon/Operational` EVTX for the Run window → parse on the host (`python-evtx`) → `ActivityRecord`s.
- **Attribution:** the process tree rooted at `acad.exe` (and `msiexec.exe` for the install window). Subtract the baseline signature set (normalised paths with user and run-ID placeholders).
- **Egress gateway** (small Linux VM): dnsmasq logging all queries, plus a forward proxy (Squid) logging CONNECT host:port and any plain HTTP. NET-002 FAILs on any plain HTTP request that carries a payload, or on any non-443 TLS-less port seen in Sysmon event 3.
- **Allow-lists** (`config/allowlists/autocad.yaml`): writable paths, registry keys and child processes. Example writable paths:
  - the plugin's own `ApplicationPlugins` folder;
  - `%APPDATA%\<Vendor>`;
  - `%LOCALAPPDATA%\<Vendor>`;
  - `%TEMP%`;
  - AutoCAD support/profile keys under HKCU.

## 7. Vertical support
- Images:
  - `c3d<year>` (Civil 3D includes Map 3D);
  - `plant<year>`;
  - `acadtoolset<year>` (Electrical, Mechanical, MEP, Architecture via the AutoCAD "toolset" product switches);
  - `advsteel<year>`.
- `hosts.yaml` vertical entries carry: the product switch, vertical API assembly names, and vertical sample documents (e.g. Civil surface DWG).
- Detection rules in `static/verticals.py`: binary references → vertical IDs; manifest `Platform`/`SeriesMin` + `AutodeskProduct` attributes → vertical IDs.

## 8. Entitlement (ENT-*)
- ENT-001: mta-inspect detects references or URLs for the Autodesk Entitlement API (`apps.autodesk.com/webservices/checkentitlement`, or the configured list).
- ENT-002: a run executes with the env var `MTA_UNENTITLED=1`, and the egress gateway blocks the entitlement host. Pass criteria: no crash, and a dialog or command-line message is observed. Otherwise the result is `NEEDS_REVIEW` (manual).

## 9. Service & data model additions
- PostgreSQL tables:
  - `submission`, `job`, `run`, `check_result`, `artifact`;
  - `override`;
  - `image`, `vm`;
  - `audit_event`.
- The queue uses one queue per image family. Workers run on hostd and pull Runs matching their images.
- **Re-run semantics:** a new Job linked to the same Submission (`rerun_of`). Reports keep both.

## 10. Dashboard v1 pages
1. **Queue:** jobs with state, age, app, recommendation chip.
2. **Report:** the Phase 1 report layout plus:
   - an evidence side-panel;
   - a video player with bookmarks generated from event timestamps (`command.invoke.begin`, `dialog.shown`, `exception.*`);
   - an override button per finding.
3. **App history:** submissions of the same app, regression diff (P2-R25).
4. **Metrics:** throughput, P50/P95 durations, override rate per check, corpus accuracy trend.

## 11. Regression diff
The diff compares `inventory` (commands, UI, network domains, files written) and the `(check_id, subject, version) → status` maps between the current job and the latest *approved* job of the same app.
