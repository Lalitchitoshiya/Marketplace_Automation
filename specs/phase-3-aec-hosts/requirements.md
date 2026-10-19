# Phase 3 — AEC Hosts (Revit, Navisworks, Robot): Requirements

**Status:** Draft v0.1 · **Duration:** 8 weeks · **Hosts:** Revit 2024–2027, Navisworks Manage/Simulate 2024–2027, Robot Structural Analysis Professional 2024–2027

## 1. Goal
1. Freeze **Adapter SDK v1**, extracted from the AutoCAD implementation, so that new hosts plug in without orchestrator changes.
2. Deliver Revit, Navisworks and Robot adapters with sanity, UI, workflow and behaviour coverage equivalent to Phase 2.

## 2. In scope
- Adapter SDK v1 with:
  - the Python base classes;
  - `Mta.Probe.Core` (a C# shared library);
  - a GUI runner library;
  - a monitoring pipeline;
  - a conformance suite;
  - an "Add a host" guide.
- New checks: MAN-008, BIN-011, REV-001…007, NAV-001…003, RSA-001…002 (added to [check-catalog.md](../00-foundation/check-catalog.md) in task P3-T01).
- Sample model library for AEC.

## 3. Dependencies
- D-LIC for Revit, Navisworks and Robot.
- Images: `rvt<year>`, `nav<year>`, `rsa<year>`.
- Autodesk-provided Revit corpus (≥30 add-ins with verdicts).

## 4. Requirements (EARS)

### Epic E1 — Adapter SDK v1
**P3-R01 SDK extraction.**
- THE SYSTEM SHALL provide these shared building blocks:
  - `DotNetStaticAnalysis` (BIN-001…009, BIN-011, parameterised by host API assembly names from `hosts.yaml`);
  - `GuiSession` (launch, dialog watcher, video, resource sampler);
  - `MonitorPipeline` (Sysmon, baseline subtraction, allow-lists);
  - `InstallerFlow` (INS, UNI);
  - `Mta.Probe.Core` (event writer, exception attribution, plan reader, resource metrics), multi-targeted `net48;net8.0-windows`.
- The AutoCAD adapter SHALL be refactored onto the SDK with no change in corpus results (regression gate).

**P3-R02 Plug-in registration.**
- Adapters SHALL be discovered through Python entry points (`mta.adapters`). Adding a host SHALL NOT require changes to the orchestrator, engine or report code. This is verified by adding the Navisworks adapter without touching those modules.

**P3-R03 Conformance suite.**
- Every adapter SHALL pass the shared conformance suite with the host-specific SD-01…SD-11 plugins.

**P3-R04 Shared-dependency conflict check (BIN-011).**
- THE SYSTEM SHALL compare versions of commonly shared third-party assemblies shipped in the package with the versions shipped by the host for the declared version. Examples: `Newtonsoft.Json`, `System.*` out-of-band packages, `SQLite`, `log4net`.
- WHEN a package ships a lower major version than the host, or a binding conflict is likely, THE SYSTEM SHALL emit WARN.

### Epic E2 — Revit
**P3-R05 Manifest validation (MAN-001, MAN-008).**
- THE SYSTEM SHALL validate every `.addin` file. The checks are:
  - schema;
  - `Type` (Application / Command / DBApplication);
  - `Assembly` path resolvable;
  - `AddInId` a GUID, unique across the package and not equal to known IDs in the corpus;
  - `FullClassName` exists and implements the matching interface (`IExternalApplication`, `IExternalCommand`, `IExternalDBApplication`);
  - `VendorId` present.
- THE SYSTEM SHALL also accept bundles with `PackageContents.xml` where `AutodeskProduct="Revit"`.

**P3-R06 Revit static rules.**
- REV-001: every `IExternalCommand` class has a `[Transaction]` attribute. (BLOCKER: Revit refuses to run commands without one.)
- REV-002: an `IUpdater` registration is detected, so check whether it is optional. Non-optional updaters cause warnings for users without the add-in. (MAJOR, confirmed dynamically.)
- REV-007: an `IExternalCommandAvailability` class referenced by the manifest exists.

**P3-R07 Revit launch & load.**
- THE SYSTEM SHALL launch `Revit.exe` with an isolated profile, deploy the add-in through its native mechanism (MSI → `Addins\<year>` / bundle), and verify:
  - LOD-004: the add-in appears in `LoadedApplications`, and there is no "Add-In failed to initialise" dialog or journal entry;
  - LOD-006;
  - the startup time delta.

**P3-R08 Revit UI & commands.**
- THE SYSTEM SHALL inventory add-in ribbon tabs, panels and buttons (baseline diff).
- For each `PushButton`, THE SYSTEM SHALL invoke the command through `PostCommand` with the command ID resolved from the ribbon item. It SHALL record the outcome against each sample model in the configured context set: an empty project, an architectural model, a structural model, an MEP model, and a family document if `Type` applies.
- THE SYSTEM SHALL capture and auto-dismiss Revit task dialogs through `DialogBoxShowing`, recording each one as `dialog.shown`.

**P3-R09 Revit document hygiene.**
- REV-003: opening a sample model with the add-in loaded SHALL NOT mark the document modified (unless declared).
- REV-004: after each command, there is no open transaction or transaction group, and no failure-processing exception.
- REV-005: on a worksharing central model, *Synchronize with Central* succeeds after running each command (scenario template).
- REV-006: model open time delta vs baseline ≤ threshold.
- REV-002 (dynamic): registered updaters are listed through `UpdaterRegistry`, and the system checks `IsUpdaterOptional`.

**P3-R10 Revit journals.**
- THE SYSTEM SHALL collect the Revit journal file of every Run and parse it for errors, exceptions and add-in failures as secondary evidence.

**P3-R11 Revit scenarios.**
- The scenario DSL SHALL support Revit assertions `element_count {category, op, value}`, `parameter_value {element_query, name, value}`, `view_exists` and `sheet_count`.

### Epic E3 — Navisworks
**P3-R12 Navisworks plugins.**
- THE SYSTEM SHALL detect Navisworks plugins (`[Plugin]`-attributed classes deriving from `AddInPlugin`, `DockPanePlugin`, `EventWatcherPlugin`, `ToolPlugin`, `CommandHandlerPlugin`, etc.) and validate the plugin folder / bundle layout (NAV-001).
- THE SYSTEM SHALL drive Navisworks through the Automation API (hidden Roamer) to:
  - open sample NWD/NWC files;
  - enumerate `PluginRecords`, check that every plugin loads (`LoadPlugin`), and emit NAV-002;
  - execute each `AddInPlugin` through its execute entry point, with outcome capture (CMD-002).
- GUI mode SHALL cover ribbon / dock panes (UI-001…003) using the SDK `GuiSession`.
- NAV-003: exporters / file readers declared by the plugin process the sample file without exception.

### Epic E4 — Robot Structural Analysis
**P3-R13 Robot add-ins.**
- THE SYSTEM SHALL detect Robot add-ins (COM-visible classes implementing `IRobotAddIn`) and validate COM registration in the installer (RSA-001).
- THE SYSTEM SHALL launch Robot through RobotOM with `Visible = false`, load a sample structural model, and call the add-in's lifecycle and command entry points (`Connect`, `DoCommand` for each declared command ID, `Disconnect`) under watchdog. It SHALL record outcomes (RSA-002, CMD-002).

### Epic E5 — Behaviour, matrix, reporting
**P3-R14 Parity.** All Phase 2 capabilities (INS, UNI, NET, FS, RUN, matrix, dashboard, regression diff) SHALL apply to the three hosts through the SDK.

**P3-R15 Host-aware report.** The report SHALL group results by host and version, and show the host-specific inventory: Revit add-ins and updaters, Navisworks plugin records, Robot add-in commands.

### Epic E6 — Corpus
**P3-R16** Corpus: ≥30 Revit add-ins, ≥5 Navisworks plugins, ≥3 Robot add-ins with manual verdicts, plus synthetic SDs per host.

## 5. Non-functional
| ID | Requirement |
|---|---|
| P3-N01 | Revit Run (1 version, ≤30 commands, 4 sample models) ≤45 min |
| P3-N02 | Adding a new host adapter skeleton using the guide takes ≤1 day for an engineer (measured with the Navisworks adapter) |
| P3-N03 | AutoCAD corpus results unchanged after the SDK refactor (100%) |

## 6. Open questions
| ID | Question |
|---|---|
| P3-Q01 | Exact format of the custom-control `RevitCommandId` string per version; does `PostCommand` work reliably from an Idling-loop driver? (spike) |
| P3-Q02 | Revit 2026+ add-in dependency isolation: manifest settings and effect on BIN-011 (verify) |
| P3-Q03 | Use APS Design Automation for Revit for DB-only add-ins (`IExternalDBApplication`) as a faster path? |
| P3-Q04 | Robot add-in registration mechanism and command ID enumeration (verify) |
