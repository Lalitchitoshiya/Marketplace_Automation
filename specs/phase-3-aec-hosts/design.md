# Phase 3 — AEC Hosts: Design

## 1. Adapter SDK v1 structure
```
src/mta/adapters/
  base/
    contract.py           ← Protocols (unchanged from P1, now frozen v1)
    dotnet_static.py      ← DotNetStaticAnalysis(host_api_assemblies, ui_assemblies, runtime_map)
    gui_session.py        ← launch, FlaUI watcher bridge, video, resource sampler, quit/kill
    installer_flow.py     ← msiexec install/uninstall + snapshot diff
    monitor.py            ← Sysmon/EVTX parse, baseline subtraction, allow-lists
    conformance/          ← pytest suite parameterised by adapter id
  autocad/  revit/  navisworks/  robot/
src/probes/
  Mta.Probe.Core/         ← event writer, plan reader, exception attribution, metrics (net48;net8.0-windows)
  AcProbe/  RvtProbe/  NavProbe/  RsaDriver/
docs/add-a-host.md        ← step-by-step guide (P3-N02)
```

`pyproject.toml`:
```toml
[project.entry-points."mta.adapters"]
autocad    = "mta.adapters.autocad:AutoCadAdapter"
revit      = "mta.adapters.revit:RevitAdapter"
navisworks = "mta.adapters.navisworks:NavisworksAdapter"
robot      = "mta.adapters.robot:RobotAdapter"
```

## 2. Revit adapter

### 2.1 Static
- `.addin` parser (defusedxml) → `RevitManifest{addins:[{type, assembly, addin_id, full_class_name, vendor_id, availability_class}]}`.
- mta-inspect extension: resolve `FullClassName` in metadata, check its interface implementations (`Autodesk.Revit.UI.IExternalApplication`, etc.), read the `[Transaction]` / `[Regeneration]` attributes, and find `UpdaterRegistry.RegisterUpdater` call sites (member references).
- Host API assemblies: `RevitAPI`, `RevitAPIUI`, `AdWindows`, `UIFramework` (the last two are UI-internal → INFO "uses internal UI API").

### 2.2 RvtProbe (`IExternalApplication`, installed in the image via its own `.addin`)
- `OnStartup`: initialise `Mta.Probe.Core`. Subscribe to:
  - `ControlledApplication.ApplicationInitialized`;
  - `DocumentOpened`;
  - `DocumentChanged` (counts only);
  - `FailuresProcessing`;
  - `UIControlledApplication.DialogBoxShowing` (record + auto-dismiss with the default/cancel result per plan);
  - `Idling`.
- `ApplicationInitialized` → emit `host.ready`, then emit the `LoadedApplications` list (the plugin's applications present?) and the ribbon inventory via `Autodesk.Windows.ComponentManager.Ribbon` with baseline diff.
- **Driver loop:** a state machine runs on `Idling` (one step per Idling tick, `SetRaiseWithoutDelay`). Its states:
  1. `OpenSample(i)` → `uiapp.OpenAndActivateDocument(path)` → record `doc.IsModified` after open (REV-003) and the open time (REV-006).
  2. `Invoke(cmd)` → resolve `RevitCommandId.LookupCommandId(<custom-control id>)`, then `uiapp.PostCommand(id)`. Completion is detected by the next Idling after the `CommandStarted`-equivalent signals plus a transaction-state check. The prompt or modal timeout is handled by the out-of-process FlaUI watcher (Esc / Cancel).
  3. `CheckHygiene` → no open transactions (`doc.IsModifiable == false`) (REV-004); emit `UpdaterRegistry.GetRegisteredUpdaterInfos()` filtered to the plugin's AddInId, with `IsUpdaterOptional` (REV-002).
  4. `CloseSample` → `doc.Close(false)` (needs another document active: keep a blank "anchor" project open).
- **Journal:** `%LOCALAPPDATA%\Autodesk\Revit\Autodesk Revit <year>\Journals\journal.*.txt`, redirected to the run folder where possible. The parser extracts `'E` / `Jrn.` lines with "Exception", "failed to initialize", "External Tools".

### 2.3 Command ID resolution
For ribbon `PushButton`s created by the add-in, the custom control ID is composed from tab, panel and button name. The exact format is confirmed by spike P3-Q01, and the mapping is captured from the ribbon item's `Id` during inventory. Manifest `Type="Command"` entries map to the External Tools drop-down.

### 2.4 Sample model set (`samples/revit/<year>/`)
`empty_arch.rvt`, `small_house.rvt`, `struct_frame.rvt`, `mep_small.rvt`, `central/` (worksharing, file-based central), `family_door.rfa`. Each sample is upgraded per year, and the samples are stored in the image at a fixed path.

### 2.5 Worksharing scenario template (REV-005)
A scenario template `templates/revit/sync_after_each_command.yaml` is instantiated per command: create a local copy → run the command → `SynchronizeWithCentral` → assert `no_exception`.

## 3. Navisworks adapter
- **Static:** `[Plugin("Name","DevId")]` attributes. Base types under `Autodesk.Navisworks.Api.Plugins`. Layout: `<install>\Plugins\<Name>\<Name>.dll` (folder name must match the assembly) or an ApplicationPlugins bundle → NAV-001.
- **Headless driver** (`NavProbe.Driver`, out-of-process .NET app):
  - `Autodesk.Navisworks.Api.Automation.NavisworksApplication` → `OpenFile(sample.nwd)`;
  - an in-process `NavProbe` AddInPlugin enumerates `Application.Plugins.PluginRecords`, calls `LoadPlugin()` for each plugin-owned record and emits events (NAV-002);
  - the driver calls `ExecuteAddInPlugin("<Name>.<DevId>", args…)` for each AddInPlugin (CMD-002) under watchdog.
- **GUI:** `Roamer.exe` through `GuiSession`; the ribbon (`.xaml`/`.name` ribbon definitions in the plugin folder) is parsed statically and compared with the live UIA tree.

## 4. Robot adapter
- **Static:**
  - COM-visible types implementing `RobotOM.IRobotAddIn`;
  - registry entries written by the installer (CLSID, Robot add-in registration key, verify);
  - `GetExpectedVersion` return value vs declared versions.
- **Driver** (`RsaDriver`, out-of-process):
  1. `new RobotApplication { Visible = false }` → `Project.Open(sample.rtd)`.
  2. Instantiate the add-in COM object (`Activator.CreateInstance(Type.GetTypeFromCLSID)`).
  3. Call `Connect(robotApp, addInId, firstTime=true)` → for each command ID reported by the add-in's menu registration → `DoCommand(id)` with watchdog → `Disconnect()`.
  4. Exceptions and HRESULTs → events.
  5. `robotApp.Project.Close()` / `robotApp.Quit(...)`.
- **GUI fallback:** launch `robot.exe` and open the Add-ins menu via FlaUI for UI-001…003.

## 5. Report changes
- Host tabs, each with its inventory section: Revit → add-ins, updaters, ribbon; Navisworks → plugin records; Robot → add-in commands.
- Sample-model columns in the command table (Revit): rows are commands, columns are models × versions.

## 6. Catalog additions (to apply in P3-T01)
| ID | Check | Sev | Src |
|---|---|---|---|
| BIN-011 | Shared third-party assembly version conflict with host | WARN | S |
| REV-001 | IExternalCommand missing `[Transaction]` | BLOCKER | S |
| REV-002 | Non-optional IUpdater registered | MAJOR | S/D |
| REV-003 | Opening a model marks it modified | MAJOR | D |
| REV-004 | Open transaction / failure-processing exception after command | MAJOR | D |
| REV-005 | Sync with Central fails after command | MAJOR | D |
| REV-006 | Model open time delta > threshold | MINOR | D |
| REV-007 | Availability class referenced in manifest missing | MAJOR | S |
| NAV-001 | Plugin folder / assembly naming layout invalid | BLOCKER | S |
| NAV-002 | PluginRecord fails to load | BLOCKER | D |
| NAV-003 | File reader / exporter fails on sample | MAJOR | D |
| RSA-001 | COM registration missing / invalid | BLOCKER | S/D |
| RSA-002 | Add-in Connect / DoCommand fails | BLOCKER | D |
