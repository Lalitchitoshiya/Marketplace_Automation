# Phase 1 — AutoCAD Headless Sanity (POC): Requirements

**Status:** Draft v0.1 · **Duration:** 6 weeks · **Hosts:** AutoCAD 2025, 2026 (2024 if the corpus requires .NET Framework 4.8 coverage)

## 1. Goal
Prove that an AutoCAD plugin submission can be validated end-to-end, with no human at the keyboard, on one Windows workstation. The run must produce a report that a reviewer trusts for the **sanity** layer (package, manifest, binaries, signing, load, commands) and for **basic workflows** (scenarios).

## 2. In scope
- Package kinds: MSI, `.bundle` folder, ZIP containing either.
- Plugin technologies: .NET (primary), ObjectARX `.arx` (load-only), AutoLISP `.lsp/.fas/.vlx` (load-only).
- Execution: **AcCoreConsole** (headless) only.
- Interface: CLI.
- Static checks:
  - PKG-001…006
  - MAN-001…007
  - BIN-001…009
  - SIG-001…003
  - LST-001…003
- Dynamic checks: LOD-001…003, CMD-001…004, WFL-001…002, RUN-001…003.

## 3. Out of scope (later phases)
GUI AutoCAD, ribbon/UI, real MSI install and uninstall, VMs, behaviour monitoring, verticals, dashboard, queue, other hosts, AI.

## 4. Assumptions & dependencies
| ID | Item |
|---|---|
| A-1 | A dedicated non-domain Windows 11 workstation with AutoCAD 2025 and 2026 installed and licensed for unattended use (**D-LIC**). |
| A-2 | Autodesk supplies ≥8 real AutoCAD plugin submissions with manual review verdicts (**D-CORPUS**). |
| A-3 | Autodesk shares the current manual review checklist (**D-CHECKLIST**). |
| A-4 | Listing metadata is supplied manually as `listing.yaml` in Phase 1 (no Publisher Corner API). |

## 5. User stories & acceptance criteria (EARS)

### Epic E1 — Intake
**P1-R01 Run from CLI.** *As a reviewer, I want to run `mta run <package>` so that I get a report without manual steps.*
- WHEN the user runs `mta run <path>` with an MSI, `.bundle` folder or ZIP, THE SYSTEM SHALL create a Job, execute all enabled Phase 1 checks and write `report.json` and `report.html` to the output directory.
- WHEN `--versions` is omitted, THE SYSTEM SHALL test every AutoCAD version that is declared by the package or listing **and** installed on the machine. It SHALL report declared-but-not-installed versions as `SKIPPED` with the reason `host version not available`.
- WHEN `--kit <folder>` is supplied, THE SYSTEM SHALL read the Input Kit ([submission-inputs.md](../00-foundation/submission-inputs.md)) and validate it: `submission.yaml` schema, referenced paths, formats, size limits, and a malware scan of all kit files. IF validation fails, THE SYSTEM SHALL exit with code 2 and a field-level error message.
- WHEN only a package path is supplied, THE SYSTEM SHALL create a minimal kit on the fly.

**P1-R27 Input Kit tooling.**
- WHEN the user runs `mta kit init <folder> --package <pkg>`, THE SYSTEM SHALL create the kit layout and a `submission.yaml` pre-filled with what can be detected from the package: the app id and package kind (step 6); products, versions and commands once manifest and binary inspection exist (steps 8–9).
- WHEN the user runs `mta kit validate <folder>`, THE SYSTEM SHALL report every kit problem without running tests.
- WHEN the user runs `mta scenario from-features <folder>`, THE SYSTEM SHALL generate one draft scenario per `features[]` entry that names commands, using the feature's `sample` if given.
- THE SYSTEM SHALL extract text from `docs/` (PDF, DOCX, MD, TXT, HTML) and report:
  - commands mentioned in the docs or `features[]` that are missing at runtime, as CMD-001 findings;
  - registered commands that are not documented, as INFO.
- THE SYSTEM SHALL show listing screenshots from `media/screenshots/` in the report.

**P1-R02 Content addressing.**
- THE SYSTEM SHALL compute SHA-256 for the package and every extracted file and store them in the artifact store, keyed by hash.

**P1-R03 Environment doctor.**
- WHEN the user runs `mta doctor`, THE SYSTEM SHALL verify:
  - AutoCAD installs and `accoreconsole.exe` for each configured version;
  - `MpCmdRun.exe`;
  - the `mta-inspect` tool;
  - the probe build for each runtime;
  - write access to the run directory;
  - the WER LocalDumps configuration.
  
  It SHALL print pass/fail for each item with a fix hint.
- WHEN the user runs `mta doctor --deep`, THE SYSTEM SHALL also run the **canary plugin** (a known-behaviour plugin derived from the P1-T03 spike) in the core console for each installed version. It SHALL verify that the key behaviours in [ADR-0003](../adr/ADR-0003-accoreconsole-for-phase-1.md) still hold:
  - load with `TRUSTEDPATHS` (F13);
  - command events (F19);
  - prompt cancel with `(command)` (F5);
  - `getcname` lookup (F18);
  - exception capture and crash exit code (F8);
  - watchdog on hang (F10);
  - startup + quit time (F20);
  - no licence prompt (F21).
- Any deviation SHALL be reported as an unhealthy environment.
- WHILE the environment is unhealthy, THE SYSTEM SHALL mark dynamic checks `ERROR`, not `FAIL`.
- The deep check SHALL run automatically before a corpus run and after any host update.

### Epic E2 — Static analysis
**P1-R04 Safe extraction.**
- THE SYSTEM SHALL extract archives with path-traversal, symlink, size (default 2 GB) and file-count (default 20,000) protections (PKG-001).
- THE SYSTEM SHALL check the **declared** sizes before writing anything, and SHALL count the **actual** bytes while writing. It SHALL reject the package (PKG-001 FAIL) for any of these:
  - absolute or drive paths, `..`, `:` (alternate data streams), Windows reserved names (`CON`, `NUL`, …), or trailing dots and spaces;
  - symlink entries;
  - encrypted entries (they cannot be scanned);
  - names that are duplicates when compared case-insensitively;
  - more data than declared;
  - a compression ratio above `extract.max_compression_ratio` for entries larger than `extract.ratio_min_bytes`;
  - total size or file count above the limits.
  A rejected extraction SHALL leave no partial output.
- Nested archives SHALL NOT be extracted. They are listed for the reviewer.
- WHEN the package is an MSI, THE SYSTEM SHALL first read its tables (`Property`, `CustomAction`, the install, admin and UI sequences) directly from the database, without running anything. It SHALL record a `CustomAction` inventory, with each action's code type (DLL / EXE / script / nested install / data-only) and the sequences it appears in.
- WHEN the MSI's `AdminExecuteSequence` or `AdminUISequence` contains no code-executing custom action, THE SYSTEM SHALL perform an administrative extraction (`msiexec /a … /qn`) into the job folder. Otherwise it SHALL NOT run `msiexec` (it would run publisher code outside a sandbox), and PKG-003 = NEEDS_REVIEW. Windows Installer being busy (1618), a timeout or a policy block is ERROR, not FAIL (PKG-003).
- THE SYSTEM SHALL require a deployable payload (PKG-002): a `*.bundle` folder, or at least one file whose extension is in the host's `payload_extensions`.
- Every payload file SHALL be hashed and stored (P1-R02). The payload listing is written to `payload-files.json`.

**P1-R05 Bundle & manifest validation.**
- THE SYSTEM SHALL locate the `*.bundle` root and validate `PackageContents.xml` (PKG-004, MAN-001…007).
- THE SYSTEM SHALL parse XML with external entities and DTDs disabled.
- WHEN a `ComponentEntry` has its own `RuntimeRequirements`, THE SYSTEM SHALL use them, not the package-level ones, to decide which host versions load that component.
- Requirements are resolved per component, most specific first: `ComponentEntry` → `Components` → `ApplicationPackage`. `SeriesMin`/`SeriesMax` (e.g. `R25.0`; `R25` = every R25.x; a missing bound is open) are matched against `hosts.yaml` `internal` versions. `Platform` decides whether the component loads in plain AutoCAD (`AutoCAD`, `AutoCAD*`) or only in verticals. The result is written to `bundle.json` and used by run planning.
- Rules:

  | Check | Rule | Result if broken |
  |---|---|---|
  | PKG-004 | Exactly one top-level `*.bundle` folder, with the manifest file directly inside it | FAIL |
  | MAN-001 | XML well-formed; DTD/entities refused; root `ApplicationPackage`; at least one `ComponentEntry` with `ModuleName`; file ≤ 1 MB | FAIL; MAN-002…007 SKIPPED |
  | MAN-002 | `ProductCode` is a GUID; `AppVersion`, `Name`, `AutodeskProduct` present; `Author` or `CompanyDetails/@Name` present | FAIL, listing what is missing |
  | MAN-003 | The components' version ranges cover every version declared in `products` for the host | FAIL, listing the uncovered years (SKIPPED when nothing is declared) |
  | MAN-004 | Every `ModuleName` exists inside the bundle; paths escaping the bundle are rejected | FAIL per component |
  | MAN-005 | Manifest commands ↔ binary commands drift | Evaluated in step 9 (needs `mta-inspect`) |
  | MAN-006 | `AutodeskProduct`, `ProductType`, `OS` and `SeriesMin`/`SeriesMax` values valid, and `OS` includes `Win64` | FAIL; unknown `Platform` tokens WARN |
  | MAN-007 | Each component's range matches at least one configured host version | FAIL per orphan component |
  | PKG-005 | Script/executable types (`.bat .cmd .ps1 .psm1 .vbs .vbe .js .jse .wsf .scr .hta`) anywhere in the payload that are not a declared `ModuleName` | WARN with the list |
  | PKG-006 | Manifest `AppVersion` (and MSI `ProductVersion`) equal the submission `app_version`, ignoring a leading `v` and trailing `.0` parts | FAIL (SKIPPED when the version is `unknown`) |
- `mta kit init` SHALL pre-fill `app.version`, `title`, `publisher` and `products` from the manifest of a bundle or ZIP, and the version from an MSI's `ProductVersion` (tables only: nothing runs before the intake malware scan). Commands found are listed as a comment to help write `features`.

**P1-R06 .NET binary inspection.**
- THE SYSTEM SHALL inspect every managed assembly **without loading it for execution**. It SHALL extract:
  - target framework;
  - referenced assemblies with versions;
  - `[CommandMethod]` attributes (global name, group, flags);
  - `IExtensionApplication` implementers;
  - `[assembly: CommandClass]` / `[assembly: ExtensionApplication]`;
  - P/Invoke imports;
  - user-string URLs;
  - risky API member references;
  - PE machine type;
  - obfuscation indicators.
- WHEN a target framework is incompatible with a host version's runtime in `hosts.yaml`, THE SYSTEM SHALL emit BIN-001 `FAIL` for that version.
- WHEN an assembly references `AdWindows`, `AcWindows`, WPF or WinForms, or uses palette / ribbon APIs, THE SYSTEM SHALL classify the component as **GUI-required** (BIN-008 `INFO`). It SHALL mark its headless load result as non-blocking (see P1-R13). A reference to `AcMgd` alone does **not** make a component GUI-required: the spike showed `AcMgd` plugins load and run in the core console ([ADR-0003](../adr/ADR-0003-accoreconsole-for-phase-1.md) F14).

**P1-R07 Native ARX inspection.**
- THE SYSTEM SHALL read the PE imports of `.arx`/`.dbx`/`.crx` files and check that the imported AutoCAD DLL major version (e.g. `acdb25.dll`) matches each declared host version (BIN-002) and is x64 (BIN-003).

**P1-R08 Signing & malware.**
- THE SYSTEM SHALL verify Authenticode signatures on all PE files and the MSI (SIG-001, SIG-002).
- THE SYSTEM SHALL scan the extracted payload with Microsoft Defender command-line scanning (SIG-003).
- IF SIG-003 fails, THEN THE SYSTEM SHALL NOT execute any dynamic phase and SHALL set the recommendation to `RECOMMEND_REJECT`.

**P1-R09 Listing checks.**
- WHEN listing metadata is present, THE SYSTEM SHALL execute LST-001…003. Otherwise THE SYSTEM SHALL mark them `SKIPPED`.

**P1-R10 Command collision.**
- THE SYSTEM SHALL compare discovered command names against the built-in command list for each version (`data/autocad/<year>/commands.txt`) (CMD-003).
- In the baseline launch (before the plugin loads), THE SYSTEM SHALL also evaluate `(getcname "<name>")` for every plugin command. A non-nil result is a collision.
- A collision makes the plugin's command unreachable, because the built-in command runs instead ([ADR-0003](../adr/ADR-0003-accoreconsole-for-phase-1.md) F24). It is reported as CMD-003 `FAIL` (MAJOR).
- WHEN the user runs `mta data gen-commands --version <year>`, THE SYSTEM SHALL regenerate `commands.txt` using the method in ADR-0003 F25.

**P1-R11 Static-only mode.**
- WHEN the user runs `mta inspect <package>`, THE SYSTEM SHALL execute only static checks and produce the same report format.

### Epic E3 — Headless dynamic execution (AcCoreConsole)
**P1-R12 Isolated run environment.**
- For every (version) Run, THE SYSTEM SHALL create a fresh run directory and a fresh isolated AutoCAD user profile. The machine's default profile SHALL NOT be modified.

**P1-R13 Component loading.**
- THE SYSTEM SHALL load each applicable component with the loader matching its type: .NET via `ExtensionLoader`, ARX via the dynamic linker, LISP via `load`. It SHALL record success or failure, any exception, and the duration (LOD-001, LOD-002).
- WHEN a GUI-required component fails to load headless with an error caused by a UI-assembly dependency, THE SYSTEM SHALL report LOD-001 as `NEEDS_REVIEW` with the note `requires GUI host — covered in Phase 2`, not `FAIL`.

**P1-R14 Command registration.**
- After loading, THE SYSTEM SHALL verify that each command discovered statically or declared in the manifest is defined in the host (CMD-001).

**P1-R15 Smoke invocation.**
- THE SYSTEM SHALL invoke each registered command on a blank sample drawing. It SHALL follow each command with the configured cancel lines (AutoLISP `(command)`, which cancels an active prompt; never bare Enter, which repeats commands: ADR-0003 F4/F5) and classify the outcome as one of:
  - `completed`
  - `awaiting_input`
  - `exception`
  - `crash`
  - `timeout`
  
  (CMD-002, CMD-004).
- WHEN the outcome is `exception` and the exception is attributed to a plugin assembly, THE SYSTEM SHALL emit CMD-002 `FAIL` (BLOCKER) with the stack trace as evidence.
- WHEN the outcome is `awaiting_input` (the command prompted for input and was cancelled by the cancel lines), THE SYSTEM SHALL emit CMD-002 `PASS` with the note `interactive; needs scenario coverage`.
- WHEN the outcome is `timeout` with no prompt active, THE SYSTEM SHALL emit CMD-004 `FAIL`.
- WHEN running commands in batch mode and an anomaly occurs (crash, timeout), THE SYSTEM SHALL re-run the remaining commands in isolated per-command processes so that one bad command does not hide the others.

**P1-R16 Runtime health.**
- THE SYSTEM SHALL detect host crashes using the exit code, a missing `probe.shutdown` event and WER dump presence (RUN-001).
- THE SYSTEM SHALL detect unhandled and AutoCAD-caught exceptions attributed to plugin assemblies (RUN-002).
- THE SYSTEM SHALL verify that the host quits within the timeout (RUN-003).

**P1-R17 Timeouts.**
- Every dynamic step SHALL have a configurable timeout (`config/thresholds.yaml`). WHEN a timeout is exceeded, THE SYSTEM SHALL kill the process tree and continue with the next step.

**P1-R18 Infrastructure errors.**
- IF the host fails to start for reasons unrelated to the plugin, THEN THE SYSTEM SHALL mark affected checks `ERROR` and SHALL NOT mark them `FAIL`. Examples: licence error text in the console output, or a baseline run without the plugin also failing.
- To support this, THE SYSTEM SHALL perform a **baseline launch** (probe only, no plugin) once per version per job.

### Epic E4 — Scenarios
**P1-R19 Scenario execution.**
- WHEN scenarios exist for the app (`/scenarios/<app_id>/` or `--scenarios`), THE SYSTEM SHALL execute those with `ui_mode` `headless` or `any` for each applicable version, following [scenario-dsl.md](../00-foundation/scenario-dsl.md) (WFL-001, WFL-002).
- Phase 1 SHALL support these verbs: `open`, `new`, `run`, `assert`, `save_as`, `script`.
- Phase 1 SHALL support these assertions: `no_exception`, `outcome`, `file_*`, `entity_count`, `layer_exists`, `block_exists`, `sysvar`.

**P1-R20 Scenario authoring aid.**
- WHEN the user runs `mta scenario new <app_id>`, THE SYSTEM SHALL generate a skeleton YAML that lists discovered commands as commented `run` steps.

### Epic E5 — Reporting
**P1-R21 report.json.**
- THE SYSTEM SHALL write a schema-valid `report.json` (see [data-contracts.md](../00-foundation/data-contracts.md)), including the inventory of components and commands.

**P1-R22 report.html.**
- THE SYSTEM SHALL render a single HTML file, viewable offline, that contains:
  - the recommendation banner and its reasons;
  - a version matrix summary;
  - results grouped by family, with filters (status, severity, version);
  - evidence: log excerpts inline, links to artifacts;
  - the command inventory table with the outcome per version.

**P1-R23 Recommendation.**
- THE SYSTEM SHALL compute the recommendation using the default rule in data-contracts §5, with severities from `config/checks.yaml`.

**P1-R24 Exit codes.**
- `mta run` SHALL exit with:
  - 0 for `RECOMMEND_APPROVE`
  - 10 for `NEEDS_HUMAN`
  - 20 for `RECOMMEND_REJECT`
  - 2 for usage errors
  - 3 for an MTA internal error

### Epic E6 — Corpus & quality
**P1-R25 Corpus runner.**
- WHEN the user runs `mta corpus run`, THE SYSTEM SHALL execute all corpus entries and compare them with `expected.yaml` (manual verdicts / expected checks). It SHALL output recall, false-positive rate, agreement and determinism.

**P1-R26 Synthetic plugins.**
- THE SYSTEM's repository SHALL contain AutoCAD synthetic defect plugins SD-01…SD-11 and SD-16 ([testing-strategy.md](../00-foundation/testing-strategy.md)), built for net48 and net8.0-windows.

## 6. Non-functional requirements
| ID | Requirement |
|---|---|
| P1-N01 | ≤15 min per plugin per version for a plugin with ≤50 commands on the reference workstation (8 cores, 32 GB RAM). |
| P1-N02 | Static analysis of a 200 MB package completes in ≤3 min. |
| P1-N03 | Deterministic checks are reproducible across 3 runs (100%). |
| P1-N04 | Structured JSON logs for every component, with job_id and run_id correlation. |
| P1-N05 | No submission code executes outside AcCoreConsole runs. Static tooling uses metadata-only APIs. |
| P1-N06 | Core Python modules have ≥80% unit-test line coverage. |

## 7. Exit criteria
See [roadmap.md](../00-foundation/roadmap.md) E1.1–E1.4.

## 8. Open questions
| ID | Question | Resolution path |
|---|---|---|
| P1-Q01 | Does AcCoreConsole honour the bundle autoloader, and with which switches? | Spike: **inconclusive** (F16). Re-test on the dedicated machine. |
| P1-Q02 | How does AcCoreConsole behave on stdin EOF while a prompt is active? Exit, hang or cancel? | **Answered:** it waits forever (F6). Cancel with `(command)` (F5). |
| P1-Q03 | Unattended licensing model for AcCoreConsole on the test machine | Autodesk (D-LIC). Works under the signed-in user (F21). |
| P1-Q04 | Exact `/isolate` and profile switches per version | **Answered** for 2026 (F1) |
| P1-Q05 | Source for built-in command lists per version | Lookup method **answered**: `getcname` (F18). The command list still needs generating (step 3). |
| P1-Q06 | Which items of Autodesk's manual checklist are in Phase 1 scope | Workshop P1-T01 |
