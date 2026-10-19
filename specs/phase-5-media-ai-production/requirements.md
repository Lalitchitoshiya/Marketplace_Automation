# Phase 5 — M&E Hosts, AI Feature Testing, Production: Requirements

**Status:** Draft v0.1 · **Duration:** 10 weeks · **Hosts:** 3ds Max 2024–2027, Maya 2024–2027 (Windows; Linux and macOS optional)

## 1. Goal
1. **Complete host coverage:** every Marketplace desktop host in [host-matrix.md](../00-foundation/host-matrix.md) is supported.
2. Add **AI feature testing**: verify that the plugin does what its listing claims, beyond sanity checks.
3. **Go to production:** automatic trigger from Publisher Corner, dashboard v2, a host-release compatibility sweep, hardening, and a shadow-mode rollout.

## 2. In scope
- New checks: MAX-001…004, MAYA-001…005, LST-004/005, WFL-003, AI-001…003.
- AI Feature Tester service.
- Publisher Corner integration.
- Dashboard v2.
- Compatibility sweep.
- Operations: SLOs, observability, DR, security review.

## 3. Dependencies
| ID | Item |
|---|---|
| D-LIC | 3ds Max, Maya licences |
| D-LLM | Autodesk-approved LLM endpoint (e.g. Claude through an approved enterprise channel) with data-handling approval for submission content and screenshots |
| D-PC | Publisher Corner submission events (webhook or API) + service account; internal review-tool integration point |
| D-SEC | Autodesk security review / penetration test slot before production |

## 4. Requirements (EARS)

### Epic E1 — 3ds Max
**P5-R01 3ds Max package.**
- THE SYSTEM SHALL validate 3ds Max bundles (`AutodeskProduct="3ds Max"`), including:
  - component part types: pre-start-up scripts, post-start-up scripts, macroscripts, plugins, icons;
  - version ranges;
  - module existence (MAN-*).
- For C++ plugins (`.dlo .dlm .dlu .gup .dlx .dle .bmi …`), THE SYSTEM SHALL verify:
  - x64;
  - the required exports (`LibDescription`, `LibNumberClasses`, `LibClassDesc`, `LibVersion`);
  - SDK compatibility with each declared version (MAX-001).

**P5-R02 3ds Max headless sanity.**
- THE SYSTEM SHALL run `3dsmaxbatch.exe` with an MTA probe script (pymxs). It SHALL:
  - verify that the plugin DLLs, scripts and macros loaded (LOD-001, MAX-002);
  - enumerate plugin-contributed classes and macroscripts (CMD-001);
  - instantiate each plugin class (geometry, modifier, material, controller, utility, as applicable) in a sample scene (MAX-003);
  - run each macroscript under watchdog (CMD-002).

**P5-R03 3ds Max GUI & scene round-trip.**
- In GUI mode (`3dsmax.exe` with the probe startup script), THE SYSTEM SHALL inventory menus, toolbars, ribbon and quad-menu additions (UI-001) and exercise them (UI-002/003).
- MAX-004: a scene containing plugin objects SHALL save and reload without errors or missing-plugin warnings while the plugin is installed. It SHALL degrade with a standard missing-DLL notice (no crash) after uninstall.

### Epic E2 — Maya
**P5-R04 Maya package.**
- THE SYSTEM SHALL validate:
  - module files (`.mod`: version/platform filters, paths exist);
  - bundles (`AutodeskProduct="Maya"`);
  - Python plugins (`initializePlugin` / `uninitializePlugin` present, `maya_useNewAPI` where using API 2.0);
  - C++ `.mll` (x64, Maya library imports for the version) (MAYA-001, BIN-010).

**P5-R05 Maya headless sanity.**
- Using `mayapy` + `maya.standalone`, with an isolated `MAYA_APP_DIR` and module path, THE SYSTEM SHALL:
  - `loadPlugin` each plugin (LOD-001);
  - list registered commands and node types via `pluginInfo` (CMD-001);
  - call each command with no or default arguments under watchdog and classify the outcome: a usage error is acceptable, a crash or uncaught non-`RuntimeError` exception is not (CMD-002);
  - `createNode` each plugin node type in a sample scene (MAYA-002);
  - `unloadPlugin` cleanly after `file -new` (MAYA-003).

**P5-R06 Maya scene round-trip & GUI.**
- MAYA-004: a scene with plugin nodes SHALL save (`.ma` and `.mb`) and reopen with identical node counts and attributes.
- In GUI mode (`maya.exe`), THE SYSTEM SHALL inventory menus, shelves and windows added by the plugin through `lsUI` and Qt introspection (UI-001), and exercise menu items and shelf buttons (UI-002/003).
- MAYA-005: the plugin does not add to `userSetup` or modify `Maya.env` outside its module, and does not register script jobs that persist after unload.

### Epic E3 — AI Feature Tester
**P5-R07 Claim extraction (AI-001).**
- WHEN a job has listing text, THE SYSTEM SHALL extract **testable feature claims** with an LLM. Inputs are the description, documentation URLs reachable over HTTPS and screenshot captions. Each claim SHALL carry: an ID, text, a source quote, mapped inventory elements (commands / UI), and testability (`testable` / `not_testable` + reason).
- Each claim SHALL quote its source text verbatim. Claims whose source quote does not appear in the inputs SHALL be discarded (anti-hallucination).

**P5-R08 Scenario synthesis (WFL-003).**
- For each testable claim, THE SYSTEM SHALL generate a DSL scenario that references **only** commands, UI elements and samples present in the job inventory and sample library.
- Generated scenarios SHALL be schema-validated and linted before execution. Invalid ones SHALL be regenerated at most twice and then marked `not_testable`.

**P5-R09 Agentic exploration (AI-002).**
- WHEN a claim cannot be expressed in the DSL (for example, dialog-heavy workflows), THE SYSTEM SHALL run a computer-use agent **inside the Run's VM**. The agent observes screenshots and the UIA tree, acts with mouse and keyboard, and has a budget: max steps (default 40), max time (default 10 min) and max tokens.
- The agent's full trajectory (screenshots, actions, reasoning summary) SHALL be stored as evidence.

**P5-R10 Judgement (AI-003).**
- THE SYSTEM SHALL judge each claim from the evidence as `supported`, `contradicted` or `inconclusive`, with a confidence score.
- `contradicted` with confidence ≥ threshold → `NEEDS_REVIEW` (AI-003). `supported` → `PASS` (`source: ai`). Otherwise → `WARN` / `INFO`.
- AI results SHALL never produce `FAIL` or `BLOCKER` (Constitution §7).

**P5-R11 Listing consistency (LST-004/005).**
- THE SYSTEM SHALL assess description quality and consistency with the observed inventory (LST-004). It SHALL also compare listing screenshots with captured UI screenshots by visual similarity plus an LLM judge (LST-005). Both are WARN-level only.

**P5-R12 Promotion to deterministic regression.**
- WHEN a reviewer marks a generated scenario as correct, THE SYSTEM SHALL save it to `/scenarios/<app_id>/` as a deterministic scenario. It SHALL then be executed for every future submission of the app.

**P5-R13 AI safety.**
- Listing text, documentation and plugin UI text SHALL be treated as **untrusted data** in prompts: delimited, and never followed as instructions.
- The agent SHALL have no access to secrets beyond the Run's leased test account, no network beyond the sandbox egress policy, and an action allow-list (no OS settings, no file deletion outside the run dir).
- All prompts and responses SHALL be logged with the job and kept under the retention policy.
- Only the D-LLM endpoint SHALL be used.

**P5-R14 AI evaluation.**
- THE SYSTEM SHALL include an AI evaluation set: ≥30 apps with reviewer-labelled claims and outcomes. It SHALL report:
  - claim recall (≥70%);
  - hallucinated-finding rate (≤10%);
  - judgement agreement;
  - cost per job.
- These metrics SHALL be re-run on every model or prompt change.

### Epic E4 — Production integration
**P5-R15 Publisher Corner trigger.**
- WHEN a desktop submission or update is created or changed in Publisher Corner, THE SYSTEM SHALL create a Job automatically, using the submission package and listing data, within 5 minutes.
- THE SYSTEM SHALL post the report link and recommendation to the internal review record. It SHALL NOT notify the publisher or change publication state (Constitution §1).

**P5-R16 Publisher-facing export.**
- A reviewer SHALL be able to export a **sanitised** findings summary for the publisher **only after recording a final decision** on the submission.
- The export SHALL contain only the findings the reviewer selects, rewritten or approved in the reviewer's words, with optional evidence excerpts (e.g. an error message or screenshot).
- The export SHALL NOT contain:
  - the MTA recommendation;
  - check IDs, severities, thresholds or allow-lists;
  - tool, probe or environment names;
  - findings the reviewer did not select;
  - internal notes, infrastructure details or other publishers' data.
- THE SYSTEM SHALL NOT offer any publisher-facing view, API or notification (Constitution §11).

**P5-R17 Host-release compatibility sweep.**
- WHEN a new host version image is added (e.g. AutoCAD 2028 beta), THE SYSTEM SHALL re-run the latest approved version of every app declaring that host, and produce a compatibility report per app and an aggregate report. This supports proactive publisher outreach.

**P5-R18 Dashboard v2.**
- The dashboard SHALL add:
  - reviewer assignment and SLA timers;
  - saved filters;
  - the compatibility sweep view;
  - the AI claim view (claims → evidence → verdict, with an accept / reject / promote action);
  - a cost view (VM minutes, LLM tokens per job);
  - audit log search.

### Epic E5 — Hardening & rollout
**P5-R19 Reliability.**
- SLOs:
  - job start ≤10 min after submission (P95);
  - full report ≤2 h for a 4-version matrix (P95);
  - infrastructure `ERROR` rate ≤3% of Runs;
  - control-plane availability 99.5%.

**P5-R20 Observability.**
- THE SYSTEM SHALL provide OpenTelemetry traces across intake → runs → report, metrics dashboards (queue depth, VM pool utilisation, licence seats, error rates), and alerts on SLO burn.

**P5-R21 Security & compliance.**
- Before production go-live, THE SYSTEM SHALL pass:
  - the Autodesk security review and penetration test;
  - RBAC review;
  - data retention enforcement;
  - backup and restore drill;
  - a DR plan (RPO 24 h, RTO 8 h).

**P5-R22 Rollout.**
- Rollout SHALL proceed in stages:
  1. **Shadow mode** (≥4 weeks): MTA runs on all desktop submissions, and reviewers work as before and record agreement.
  2. **Assisted mode:** reviewers start from the MTA report.
  3. **Default mode:** the MTA report is mandatory input for every desktop review.
- Each stage gate requires G1–G5 ([product-vision.md](../00-foundation/product-vision.md)) to be met on that stage's data.

**P5-R23 Handover.**
- THE TEAM SHALL deliver:
  - runbooks (VM pool, image rebuild, licence issues, stuck jobs);
  - the add-a-host guide v2;
  - an add-a-check guide;
  - a scenario authoring guide for reviewers;
  - training sessions for the Marketplace team.

## 5. Non-functional
| ID | Requirement |
|---|---|
| P5-N01 | AI cost ≤ configured budget per job (default cap set with Autodesk), enforced with hard stop |
| P5-N02 | 3ds Max / Maya headless Run ≤20 min per version for ≤50 commands/classes |
| P5-N03 | Capacity: ≥50 desktop submissions/day at the 4-version matrix (sized with Autodesk volumes) |

## 6. Open questions
| ID | Question |
|---|---|
| P5-Q01 | Publisher Corner integration surface (webhook vs polling, data model) — Autodesk |
| P5-Q02 | LLM endpoint, data residency and approval for sending screenshots / binaries metadata — Autodesk legal/security |
| P5-Q03 | 3ds Max SDK binary-compatibility ranges per release (verify) |
| P5-Q04 | Linux/macOS coverage for Maya — required or not? |
| P5-Q05 | Is the compatibility sweep allowed to use pre-release (beta) host builds? |
