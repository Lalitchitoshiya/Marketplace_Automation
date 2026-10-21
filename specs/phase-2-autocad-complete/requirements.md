# Phase 2 — AutoCAD Complete: Requirements

**Status:** Draft v0.1 · **Duration:** 8 weeks · **Hosts:** AutoCAD 2024–2027 and its verticals (Civil 3D, Map 3D, Plant 3D, Electrical, Mechanical, MEP, Architecture), plus Advance Steel

## 1. Goal
Cover **everything a reviewer does** for an AutoCAD-family plugin:
- real install and uninstall;
- GUI load through the autoloader;
- ribbon and dialogs;
- workflows;
- behaviour monitoring;
- the full version and vertical matrix.

All of it runs in disposable VMs, behind a queue and a reviewer dashboard.

## 2. In scope
- New checks:
  - INS-001…004, LOD-004…006;
  - CMD-005;
  - UI-001…006;
  - RUN-004…005;
  - NET-001…004;
  - FS-001…005;
  - UNI-001…003;
  - ENT-001…002;
  - SIG-004.
- Sandbox: Hyper-V VM pool with golden images.
- REST API, job queue, dashboard v1, SSO.
- Regression diff between versions of the same app.

## 3. Dependencies
| ID | Item |
|---|---|
| D-LIC | Unattended licences for AutoCAD 2024–2027 + verticals inside VMs (network licence server or internal entitlement) |
| D-INFRA | Hyper-V host(s): ≥ 64 cores / 256 GB RAM / 4 TB NVMe for 8 concurrent VMs, isolated VLAN |
| D-IDP | Autodesk OIDC client for dashboard SSO |
| D-STORE | Approved artifact storage (Azure Blob / S3 / on-prem) |

## 3a. Carried over from Phase 1 (retrospective, step 15)
Facts and debts found in Phase 1 that this phase must respect. Sources are ADR-0003 F1–F31 and the step tracker.

| # | Phase 1 learning | Consequence for Phase 2 |
|---|---|---|
| L1 | AutoCAD's API major is a binary break: R25 (2025/2026, .NET 8) and R26 (2027, .NET 10). AutoCAD 2027 is already released (F31). | Golden images per version. The probe and corpus are built per major (`mta probe build`, `mta corpus build`). The version matrix (P2-R19) includes 2027 from day one. |
| L2 | A crash starts Autodesk's crash reporter (dialog plus upload); the crashed console then often never exits (F29, F30). | VM network isolation (P2-R04) must block crash-report uploads. GUI runs (`acad.exe`) must suppress the same reporter. The post-crash grace kill also applies to GUI hosts. |
| L3 | `/isolate` fails with long run paths, because vertical products' roaming folders overflow MAX_PATH (F28). | Guest run roots stay short (`C:\mta\`). |
| L4 | The autoloader in the core console was inconclusive (F16). | P2-R08 must verify autoloading in the GUI host, and use it as LOD-004. |
| L5 | GUI-only plugins (ribbon, palettes) give LOD-001 NEEDS_REVIEW headless (SD-17). | Phase 2 GUI runs must turn these into real LOD/UI results; SD-17 is the regression case. |
| L6 | A false PASS happened when the loader reported success without loading anything (recursive TRUSTEDPATHS). | Every load result needs independent evidence (the probe's `loaded`). Keep this for `.addin`/GUI loaders. |
| L7 | Shipped copies of host DLLs were analysed as plugin code (SD-08). | Behaviour monitoring (P2-R15) must attribute activity of host-shipped DLLs to the host, not the publisher. |
| L8 | The synthetic corpus can only be signed with an untrusted certificate (P1-Q07). | A trusted test code-signing certificate is needed before signing checks can be fully green in the corpus. |
| L9 | WER LocalDumps needs administrator rights and is not configured on developer machines. | Golden images configure LocalDumps (P2-R02). |
| L10 | Bot protection answers automated HTTP checks with 403 (LST-001). | Dashboard (P2-R24): show "check in a browser" findings as reviewer tasks. |



### Epic E1 — Sandbox
**P2-R01 Disposable VMs.**
- WHEN a Run starts, THE SYSTEM SHALL acquire a VM from the pool for the required image. Examples: `acad2026-win11`, `c3d2026-win11`.
- The VM SHALL be in a clean checkpoint state. THE SYSTEM SHALL revert it to that checkpoint after the Run, whatever the Run's outcome.
- IF a revert fails, THEN THE SYSTEM SHALL quarantine the VM and alert.

**P2-R02 Golden images as code.**
- VM images SHALL be built reproducibly from code (Packer + PowerShell DSC/scripts). Each image includes:
  - the host product(s) and updates;
  - the probe bundles;
  - mta-agent, Sysmon, the recording tools;
  - the sample library.
- Every image SHALL carry a version tag that is recorded in each Run.

**P2-R03 Host ↔ guest channel without guest networking.**
- THE SYSTEM SHALL control VMs and copy files using a channel that does not depend on guest networking (Hyper-V PowerShell Direct / `Copy-VMFile`).

**P2-R04 Network isolation.**
- Guest network traffic SHALL be limited to the licence server and a recording egress path. No other internal network SHALL be reachable.
- WHEN `--offline` is set for a Run, THE SYSTEM SHALL disable egress entirely (used for NET-004).

**P2-R05 Pool & scheduling.**
- THE SYSTEM SHALL schedule Runs subject to these limits:
  - per-image VM capacity;
  - licence seat limits per product;
  - job priority (new submission > update > corpus).
- WHEN a VM fails to boot or the agent is unresponsive for 3 minutes, THE SYSTEM SHALL retry once on another VM and then mark the Run `ERROR`.

### Epic E2 — Install / uninstall
**P2-R06 Real installation.**
- THE SYSTEM SHALL install MSI packages silently with verbose logging (`msiexec /i <pkg> /qn /l*v`). It SHALL evaluate INS-001…004.
- WHEN the package is a bare `.bundle` or ZIP, THE SYSTEM SHALL deploy it to `%ProgramData%\Autodesk\ApplicationPlugins` and mark INS-001 as `SKIPPED (no installer)`.

**P2-R07 Uninstall verification.**
- After testing, THE SYSTEM SHALL uninstall the product and check UNI-001…003. It SHALL do this by diffing the file-system and registry snapshots taken pre-install and post-uninstall, with user data allow-listed, and by launching the host one more time.

### Epic E3 — GUI execution
**P2-R08 GUI launch & autoloader.**
- THE SYSTEM SHALL launch the full host (`acad.exe`, with the vertical product switch where applicable) with an isolated profile and command-line logging enabled.
- THE SYSTEM SHALL verify that the plugin's components were loaded **by the host's native loader** without manual loading (LOD-004).

**P2-R09 Startup health.**
- THE SYSTEM SHALL detect error and warning dialogs during startup (LOD-006, UI-004).
- THE SYSTEM SHALL measure the startup time delta against the baseline launch for the same image (LOD-005).

**P2-R10 UI inventory.**
- THE SYSTEM SHALL inventory plugin-contributed UI: ribbon tabs, panels, buttons, drop-downs, menus, toolbars, palettes and context menus. It SHALL attribute each element to the plugin by diffing it against the baseline UI, and SHALL emit `ui.element` events (UI-001, UI-006).

**P2-R11 UI exercise.**
- For each plugin ribbon button or menu item, THE SYSTEM SHALL trigger it, capture any dialog (screenshot), close it via Cancel / Esc / the close button, and record the outcome (UI-002, UI-003).
- THE SYSTEM SHALL trigger at least one element per panel through **real input** (FlaUI click), not through the API.

**P2-R12 Evidence capture.**
- In GUI mode, THE SYSTEM SHALL record a screen video of each Run and capture screenshots on every dialog, exception and failed assertion.

**P2-R13 GUI scenarios.**
- THE SYSTEM SHALL execute scenarios with `ui_mode: gui`, supporting the additional verbs `click`, `dialog`, `wait` and `screenshot`, and the assertions `dialog_shown` and `screenshot_not_blank`.

**P2-R14 High-DPI pass (optional).**
- WHEN `hidpi: true` is configured for a job, THE SYSTEM SHALL repeat the UI inventory and exercise at 150% scaling and evaluate UI-005.

### Epic E4 — Behaviour monitoring
**P2-R15 Activity capture.**
- THE SYSTEM SHALL capture the following for the host process tree and the installer:
  - process creation;
  - file create / modify / delete;
  - registry set / delete;
  - DNS queries;
  - network connections.
  
  Capture uses Sysmon (plus ETW where needed) and is collected per Run.

**P2-R16 Baseline subtraction.**
- THE SYSTEM SHALL subtract activity observed in the baseline Run (host without the plugin) on the same image. This attributes behaviour to the plugin.

**P2-R17 Behaviour rules.**
- THE SYSTEM SHALL evaluate NET-001…003 and FS-001…005 against allow-lists in `config/allowlists/<host>.yaml` and the listing's `external_domains`.

**P2-R18 Resource health.**
- THE SYSTEM SHALL sample private bytes, handle count and GDI/USER objects every 2 s during smoke and UI exercise, and evaluate RUN-004 and RUN-005.

### Epic E5 — Matrix & verticals
**P2-R19 Version matrix.**
- THE SYSTEM SHALL run every declared version in parallel VMs and present a matrix in the report.

**P2-R20 Verticals.**
- WHEN the package or binaries target a vertical, THE SYSTEM SHALL run on that vertical's image. Targeting is indicated by:
  - manifest `Platform`/product attributes;
  - references to vertical APIs (e.g. `AeccDbMgd`, `AecBaseMgd`, `PnP3dObjectsMgd`, `ManagedMapApi`, Advance Steel API).
- WHEN the listing declares a vertical that the binaries do not support, or vice versa, THE SYSTEM SHALL report LST-003.

**P2-R21 Document integrity.**
- After smoke and scenarios, THE SYSTEM SHALL run `AUDIT` on the working drawing and evaluate CMD-005.

### Epic E6 — Licensing behaviour
**P2-R22 Entitlement.**
- For paid or trial listings, THE SYSTEM SHALL check ENT-001 statically. It SHALL run the plugin in an unentitled state and verify ENT-002: the plugin shows a licence message or limits functionality, and does not crash.

### Epic E7 — Service, dashboard, regression
**P2-R23 REST API.**
- THE SYSTEM SHALL expose these endpoints:
  - `POST /submissions` (multipart package + listing JSON)
  - `GET /jobs/{id}`
  - `GET /jobs/{id}/report`
  - `POST /jobs/{id}/rerun`
  - `GET /artifacts/{sha}`
  
  They SHALL be documented with OpenAPI and authenticated with OIDC bearer tokens.

**P2-R24 Dashboard v1.**
- Reviewers SHALL be able to:
  - see the queue and job states;
  - open the report with an evidence viewer (images, video with event-time bookmarks, logs);
  - filter findings;
  - override a CheckResult with a mandatory reason;
  - trigger a re-run.
- Access SHALL be restricted by role: reviewer, lead, admin.

**P2-R25 Regression diff.**
- WHEN a submission has a previous submission for the same app, THE SYSTEM SHALL show a diff covering:
  - new, removed and changed commands and UI;
  - new network domains and file and registry behaviour;
  - checks that changed status.

**P2-R26 Override analytics.**
- THE SYSTEM SHALL compute the override rate per check ID weekly. This feeds the false-positive metric (G5).

### Epic E8 — Corpus
**P2-R27 Corpus extension.**
- The corpus SHALL grow to ≥40 AutoCAD-family plugins: ≥25 real, covering ≥3 verticals, plus SD-12…15 for AutoCAD.

## 5. Non-functional
| ID | Requirement |
|---|---|
| P2-N01 | 4-version matrix wall-clock ≤30 min (P50) with 4 parallel VMs |
| P2-N02 | VM revert + ready ≤3 min |
| P2-N03 | Zero sandbox escapes in the security corpus (EICAR, persistence, network scan, VM-detection samples) |
| P2-N04 | API availability 99% during business hours (internal service) |
| P2-N05 | Dashboard P95 page load ≤2 s for a report with 500 findings |
| P2-N06 | Artifact retention configurable (default 180 days); audit log retained 2 years |

## 6. Open questions
| ID | Question |
|---|---|
| P2-Q01 | Most reliable way to load AcProbe before third-party bundles in GUI mode: registry demand-load, a probe bundle with load order, or `/b` startup script plus retroactive `AppDomain.GetAssemblies()` scan? (spike P2-T03) |
| P2-Q02 | Vertical launch switches and licence features per vertical (verify) |
| P2-Q03 | Can licence state be toggled per Run for ENT-002, or do we need a separate unentitled image? |
| P2-Q04 | Hosting: on-prem Hyper-V or Azure (nested virtualisation / Dv5 with Hyper-V)? |
