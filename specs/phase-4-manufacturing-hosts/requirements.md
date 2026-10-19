# Phase 4 — Manufacturing Hosts (Inventor, Fusion, Vault, Alias): Requirements

**Status:** Draft v0.1 · **Duration:** 8 weeks · **Hosts:**
- Inventor 2024–2027
- Fusion (rolling production build; Windows, plus a macOS spike)
- Vault Professional client 2024–2027, with a server fixture
- Alias 2024–2027 (stretch)

## 1. Goal
Bring the manufacturing hosts onto Adapter SDK v1. Phase 4 introduces three things earlier phases did not need:
1. A **Python-language** plugin ecosystem (Fusion).
2. A **server-dependent** host (Vault).
3. A **rolling-release, sign-in-required** host (Fusion).

## 2. In scope
- New checks: BIN-010, INV-001…004, FUS-001…005, VLT-001…006, ALS-001…002 (added to the catalog in P4-T01).
- Python static analysis toolkit (shared with Phase 5 3ds Max and Maya).
- Vault server fixture with fast reset.
- Test-account and secret management for sign-in-required hosts.

## 3. Dependencies
| ID | Item |
|---|---|
| D-LIC | Inventor, Vault, Alias licences; **Fusion test accounts** (≥4 concurrent, non-personal, MFA-exempt or automation-capable, per Autodesk policy) |
| D-VAULT | Vault Professional server installation media + SQL Server licence for the fixture VM |
| D-MAC | (Spike only) Apple hardware for macOS VMs, if Autodesk confirms Mac coverage is required |

## 4. Requirements (EARS)

### Epic E1 — Inventor
**P4-R01 Inventor manifest & static.**
- THE SYSTEM SHALL validate Inventor `.addin` manifests (INV-001):
  - schema;
  - `ClassId` / `ClientId` GUIDs;
  - `Assembly` path;
  - `SupportedSoftwareVersion*` range vs the declared versions;
  - `LoadOnStartUp` / `LoadBehavior` values.
- THE SYSTEM SHALL verify that the class implements `Inventor.ApplicationAddInServer`. It SHALL also verify the interop reference version (`Autodesk.Inventor.Interop`) vs the host version (BIN-002).

**P4-R02 Inventor load.**
- THE SYSTEM SHALL launch Inventor (Visible configurable) and attach through COM.
- THE SYSTEM SHALL locate the add-in in `ApplicationAddIns` by ClassId and verify that `Activated == true` after startup (LOD-004). It SHALL record activation errors (INV-002).

**P4-R03 Inventor commands & UI.**
- THE SYSTEM SHALL enumerate `ControlDefinitions` whose `ClientId` equals the add-in's ClientId (CMD-001), and ribbon controls referencing them per environment: Part, Assembly, Drawing, Presentation, Sheet Metal, ZeroDoc (UI-001).
- For each control definition, and for each document environment in which it is `Enabled`, THE SYSTEM SHALL open the matching sample document and call `Execute2(true)` under watchdog. Open command dialogs SHALL be terminated, and the outcome recorded (CMD-002, INV-003).

**P4-R04 Inventor document hygiene.**
- INV-004: add-in activation SHALL NOT dirty opened sample documents or change application options persistently (option snapshot before / after).

### Epic E2 — Fusion
**P4-R05 Fusion package & manifest.**
- THE SYSTEM SHALL validate Fusion add-in packaging (FUS-001):
  - the bundle / installer places the add-in in a location Fusion loads;
  - the `.manifest` JSON is valid (`autodeskProduct`, `type`, `id`, `version`, `supportedOS`, `runOnStartup`);
  - the entry file exists: `<Name>.py` defining `run` / `stop`, or a C++ `.dll`.

**P4-R06 Python static analysis (BIN-010).**
- For Python plugins, THE SYSTEM SHALL check the following **without executing plugin code**:
  - syntax validity for the host's Python version (`compile()` in the matching interpreter);
  - imports resolvable from the host Python, the vendored `lib/` folders or the stdlib;
  - absence of runtime `pip install`, and `subprocess` / `os.system` use (WARN);
  - deprecated `adsk` API usage, from a list maintained per release;
  - hard-coded URLs (BIN-006).

**P4-R07 Fusion sign-in & version.**
- THE SYSTEM SHALL launch Fusion signed in with a pooled test account whose secret is fetched from the vault at run time. It SHALL record the Fusion build number in the Run.
- WHEN sign-in fails, THE SYSTEM SHALL mark the Run `ERROR` (infrastructure), not `FAIL`.

**P4-R08 Fusion load & commands.**
- Through a harness add-in (`MtaFusionProbe`, Python, `runOnStartup`), THE SYSTEM SHALL:
  - verify that the add-in started (FUS-002);
  - enumerate command definitions and toolbar controls the add-in created, as a diff against the baseline (CMD-001, UI-001);
  - execute each command definition, terminate the active command after the timeout, and record the outcome (CMD-002).
- WHEN a Fusion message box containing a Python traceback appears, THE SYSTEM SHALL classify it as a plugin exception (FUS-003) and attach the traceback text.

**P4-R09 Fusion lifecycle.**
- FUS-004: stopping the add-in (`stop`) removes its UI elements and command definitions (no leftovers after stop).
- FUS-005: the add-in is compatible with the current production Fusion build. Every corpus Fusion app SHALL be re-tested automatically when the image's Fusion build changes (scheduled regression).

**P4-R10 macOS spike (optional).**
- THE TEAM SHALL deliver a feasibility report for running the Fusion adapter on macOS VMs (static + load + command smoke). The report SHALL include cost and a recommendation.

### Epic E3 — Vault
**P4-R11 Vault server fixture.**
- THE SYSTEM SHALL provide a Vault server VM fixture (ADMS + SQL) with a seeded test vault containing:
  - folders;
  - Inventor / AutoCAD files with references;
  - lifecycle definitions;
  - categories;
  - users.
- It SHALL reset to a clean checkpoint in ≤10 min, between jobs or per Run (configurable).

**P4-R12 Vault static.**
- THE SYSTEM SHALL validate the `.vcet.config` and extension layout (VLT-002). It SHALL also verify that `[assembly: ApiVersion]` matches each declared Vault version (VLT-001, BLOCKER: Vault refuses to load mismatched extensions) and that `[assembly: ExtensionId]` is present and unique.

**P4-R13 Vault Explorer extensions.**
- THE SYSTEM SHALL log in to Vault Explorer with a fixture account and verify that the extension loaded (no extension-load error dialog: LOD-006).
- THE SYSTEM SHALL execute the extension's commands on the configured selection types (file, folder, item, change order) via the UI, and record outcomes (VLT-003).

**P4-R14 Vault event handlers & jobs.**
- WHEN the extension implements web-service event handlers, THE SYSTEM SHALL perform standard operations and verify that each succeeds (or is blocked only with a declared message) without exceptions (VLT-005). The operations are: check-out, check-in, lifecycle change, rename, move, delete.
- WHEN the extension implements a Job Processor handler, THE SYSTEM SHALL queue a job of each declared type, run the Job Processor and verify that the job completes (VLT-004).
- VLT-006: the extension does not degrade login time beyond the threshold.

### Epic E4 — Alias (stretch)
**P4-R15 Alias.**
- THE SYSTEM SHALL validate Alias plugin binaries (x64, Alias library import versions) (ALS-001).
- THE SYSTEM SHALL load each plugin through the Plug-in Manager in GUI automation, record the load result and new menu items, and exercise the menu items (ALS-002).

### Epic E5 — Cross-cutting
**P4-R16 Secrets.**
- Test credentials SHALL be stored in a secret vault (Azure Key Vault / HashiCorp Vault), injected only for the Run, and redacted from logs and reports. Accounts SHALL be pooled and leased exclusively per Run.

**P4-R17 Parity.**
- INS, UNI, NET, FS, RUN, the matrix, the dashboard and regression diff SHALL apply to all Phase 4 hosts.

**P4-R18 Corpus.**
- ≥15 Inventor, ≥10 Fusion, ≥5 Vault and ≥2 Alias (stretch) apps with verdicts, plus synthetic SDs per host. The Fusion SDs SHALL include a Python traceback, a missing vendored lib and a leftover UI after stop.

## 5. Non-functional
| ID | Requirement |
|---|---|
| P4-N01 | Inventor Run (1 version, ≤40 commands, 5 environments) ≤45 min |
| P4-N02 | Vault fixture reset ≤10 min; concurrent Vault Runs isolated (separate vaults or serialised) |
| P4-N03 | Fusion scheduled regression completes for the whole Fusion corpus within 24 h of a Fusion build change |
| P4-N04 | Zero credential leakage in reports and logs (automated secret scanning of artifacts) |

## 6. Open questions
| ID | Question |
|---|---|
| P4-Q01 | Fusion automation account policy (MFA, session lifetime, offline mode duration) — Autodesk |
| P4-Q02 | Fusion: does a bundle from ApplicationPlugins load identically to the AddIns folder? Which does the Marketplace installer use? (verify) |
| P4-Q03 | Vault `ApiVersion` value per release (verify) and the Vault client .NET runtime per release (verify) |
| P4-Q04 | Is Mac coverage required for Fusion (and later Maya)? — Autodesk |
| P4-Q05 | Alias plugin loading by command line or environment variable instead of the Plug-in Manager UI (verify) |
