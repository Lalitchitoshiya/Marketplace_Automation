# Phase 1 — Execution Plan (15 Steps)

This plan turns [tasks.md](tasks.md) into 15 ordered steps. Each step ends with something we can **demo or test**, and must be done before the next one starts, unless the step is marked *parallel*.

Requirements: [requirements.md](requirements.md) · Design: [design.md](design.md)

---

## 0. Prerequisite check (done 2026-10-19 on the dev machine)

| # | Prerequisite | Status | Notes / action |
|---|---|---|---|
| 1 | Windows 11 x64 | ✅ | Dev machine |
| 2 | AutoCAD 2026 + `accoreconsole.exe` | ✅ | `C:\Program Files\Autodesk\AutoCAD 2026` |
| 3 | AutoCAD 2025 | ❌ not installed | Phase 1 runs **2026 only** until 2025 is installed. Static checks still cover 2025 (version rules don't need the product). |
| 4 | AutoCAD 2024 (.NET Framework 4.8 build) | ❌ not installed | Optional. Needed only if the corpus has net48 plugins to test dynamically. |
| 5 | AutoCAD API DLLs (`AcCoreMgd`, `AcDbMgd`, `AcMgd`, `AdWindows`) | ✅ | Present in the install folder; used as compile references |
| 6 | .NET SDK | ✅ 10.0.400 | Builds `net8.0-windows` plugins (verified with spike build). Build shows MSB3277 reference-version warnings → pin references in step 4. |
| 7 | Python 3.12 | ✅ 3.12.13 | Installed via `uv python install 3.12` |
| 8 | Git | ✅ 2.53 | Repository not initialised yet → step 4 |
| 9 | Microsoft Defender CLI (`MpCmdRun.exe`) | ✅ | |
| 10 | Unattended AutoCAD licence | ⚠ to verify | Core console starts with the current user's sign-in. Behaviour without an interactive login is untested (step 2). Autodesk dependency **D-LIC**. |
| 11 | Clean AutoCAD profile | ⚠ | The machine's default profile is **Civil 3D** (Civil 3D modules load at core-console startup). Every run must use `/product ACAD` + `/isolate`. |
| 12 | Dedicated, non-domain test machine | ⚠ | We are on a developer machine. OK for **our own** synthetic plugins. Real third-party plugins must wait for a dedicated machine (security guardrail, [security-and-isolation.md](../00-foundation/security-and-isolation.md) §3). |
| 13 | Autodesk manual review checklist | ⏳ pending | Needed by step 15 (ideally step 5). |
| 14 | Real corpus plugins with review verdicts (≥8) | ⏳ pending | Needed by step 15 |

### Facts already confirmed by the spike (step 2, partial)
- `accoreconsole.exe` switches in 2026: `/i`, `/s`, `/product`, `/l`, `/isolate <userid> <userDataFolder>`, `/readonly`, `/p`, `/loadmodule`, `/supportfilesmap`.
- Console output is **UTF-16LE**.
- Started without a script, it stays at the `Command:` prompt and does not exit by itself. The runner must always end with `QUIT` and keep a watchdog.

---

## Overview

```
Week 1   ① Prereqs  ② Console spike  ③ Command-lookup spike
Week 2   ④ Repo & CI  ⑤ Models/config  ⑥ Intake & Input Kit
Week 3   ⑦ Extraction  ⑧ Manifest checks  ⑨ Binary inspection
Week 3-4 ⑩ Signing/malware/listing  →  ★ M1: static report
Week 4-5 ⑪ Probe  ⑫ Core-console runner & load  ⑬ Smoke tests & broken plugins → ★ M2
Week 6   ⑭ Scenarios & HTML report  ⑮ Corpus run & demo → ★ Phase 1 exit
```

---

## Step 1: Prerequisites & test machine
**Tasks:** P1-T02 · **Week:** 1
- Install Python 3.12 via `uv`; record tool versions in `docs/workstation.md`.
- Configure WER LocalDumps for `accoreconsole.exe` (admin) so crashes produce dump files.
- Request a dedicated non-domain test machine and AutoCAD 2025 from Autodesk / IT.

**Done when:** `docs/workstation.md` lists every prerequisite with status, and the open items have owners.

## Step 2: AcCoreConsole spike *(in progress)*
**Tasks:** P1-T03 · **Week:** 1
Run the spike plugins (`spikes/p1-t03-accoreconsole/`) and answer:
1. Load a .NET plugin with `NETLOAD` from a script, and with `/loadmodule`.
2. What happens on an exception, an input prompt, `stdin` closed, a hang, and a crash? Record the exit codes and output.
3. Do the prompt and command events fire in the core console?
4. Does a UI-dependent (`AcMgd`) plugin load or fail, and with what message?
5. Is `TRUSTEDPATHS` settable from a script? What does `SECURELOAD` do?
6. Does the core console auto-load bundles from ApplicationPlugins?
7. How does licensing behave in an isolated profile?

**Done when:** findings are written into [ADR-0003](../adr/ADR-0003-accoreconsole-for-phase-1.md) "Findings", and design.md / hosts.yaml are corrected if anything differs.

## Step 3: Command-lookup spike *(parallel with step 2)*
**Tasks:** P1-T04 · **Week:** 1
- Find a reliable way to check that a command exists at runtime: the internal `Utils.IsCommandDefined`, `(getcname)`, or the "Unknown command" event.
- Produce `data/autocad/2026/commands.txt`, the list of built-in commands, for the collision check (CMD-003).

**Done when:** the lookup method is chosen and documented, and the command list is generated.

## Step 4: Repository, tooling & CI
**Tasks:** P1-T05 · **Week:** 2
- `git init`; layout per [architecture.md](../00-foundation/architecture.md) §4.
- Python project (`uv`, Typer CLI skeleton `mta --version`), ruff, mypy, pytest.
- C# solution: `MtaInspect`, `AcProbe`, `SyntheticPlugins`. Shared `Directory.Build.props` with pinned AutoCAD reference paths per version (fixes MSB3277).
- CI pipeline: lint, type-check and unit tests on every commit.

**Done when:** `mta --version` works, `dotnet build` is clean, and CI is green.

## Step 5: Data models, schemas & configuration
**Tasks:** P1-T06, P1-T07 · **Week:** 2
- Pydantic models plus JSON Schemas for Submission, Job, Run, CheckResult and Report.
- Config files with loaders and validation:
  - `config/hosts.yaml` (seeded with the facts from steps 2–3);
  - `checks.yaml`;
  - `thresholds.yaml`;
  - `probe_identity.yaml` (neutral probe names).

**Done when:** schema tests pass, and a sample `report.json` validates.

## Step 6: Intake, artifact store & Input Kit
**Tasks:** P1-T08, P1-T34 · **Week:** 2
- `mta kit init`, `mta kit validate`, and `mta run --kit` / `mta run <package>` (intake only for now).
- Content-addressed artifact store (SHA-256).
- Document text extraction (PDF, DOCX, MD, TXT, HTML) and the command-mention index.

**Done when:** a sample kit is created, validated and stored, with hashes recorded.

## Step 7: Safe package extraction
**Tasks:** P1-T09 · **Week:** 3
- ZIP extraction protected against zip-slip, zip bombs and symlinks.
- MSI administrative extraction plus reading the MSI tables (`CustomAction` inventory).
- Checks PKG-001…003.

**Done when:** unit tests pass on malicious-archive fixtures, and a real MSI extracts correctly.

## Step 8: Bundle & manifest checks
**Tasks:** P1-T10 · **Week:** 3
- Locate `*.bundle`; parse `PackageContents.xml` safely.
- Checks PKG-004…006 and MAN-001…007, with per-component runtime requirements.

**Done when:** the rules pass their unit tests against good and broken manifest fixtures.

## Step 9: Binary inspection (`mta-inspect`)
**Tasks:** P1-T11, P1-T12, P1-T15 · **Week:** 3
- C# tool that reads DLLs **without loading them**. It extracts:
  - target framework and references;
  - `[CommandMethod]` commands and flags;
  - the `IExtensionApplication` class;
  - P/Invoke calls, URLs and risky API use;
  - obfuscation hints.
- ARX native import check.
- Checks BIN-001…009 (including the "needs GUI" classification) and CMD-003.

**Done when:** the spike plugins are correctly described (commands, .NET 8, x64). `SpikeUiPlugin` is classified core-console compatible, per F14/F27; it was originally expected to be GUI-required, which the spike disproved. GUI-required detection (palette, ribbon, WPF, WinForms) is proven with a fixture assembly.

## Step 10: Signing, malware & listing checks → ★ Milestone M1
**Tasks:** P1-T13, P1-T14, P1-T16 · **Week:** 3–4
- Authenticode checks (SIG-001/002) and the Defender scan (SIG-003), which gates the dynamic phase.
- Listing checks LST-001…003.
- `mta inspect <package>` produces a full **static-only `report.json`**.

**Done when (M1):** static reports are produced for the spike plugins and 3–5 public Marketplace AutoCAD apps, and reviewed with the team.

## Step 11: The probe (`AcProbe`)
**Tasks:** P1-T17 · **Week:** 4
- Core-console-safe probe (`AcCoreMgd` + `AcDbMgd` only). Builds on the spike plugin.
- Event writer (NDJSON, per [probe-protocol.md](../00-foundation/probe-protocol.md)).
- Hooks for exceptions, assembly loads, command and prompt events.
- Probe commands: load, enumerate, mark, assert, end. Names come from `probe_identity.yaml`.

**Done when:** loading the probe alone in the core console produces a clean event file (`probe.start` … `probe.shutdown`).

## Step 12: Core-console runner, baseline & component loading
**Tasks:** P1-T18…T21, P1-T24 · **Week:** 4–5
- Run directory and isolated profile; script builder; `/product ACAD`.
- Runner: launch, UTF-16 output capture, watchdog, process-tree kill, dump detection.
- Baseline launch (probe only) plus infrastructure-error detection (licence and startup problems → `ERROR`, not `FAIL`).
- Component loading (.NET / ARX / LISP), checks LOD-001…003.
- `mta doctor` command.

**Done when:** the spike plugin loads and is reported, `SpikeUiPlugin` shows `NEEDS_REVIEW (requires GUI)`, and `mta doctor` passes on this machine.

## Step 13: Command checks, smoke tests & broken test plugins → ★ Milestone M2
**Tasks:** P1-T22, P1-T23, P1-T25 · **Week:** 5
- Runtime command check (CMD-001).
- Smoke-run every command:
  - batch mode first, then per-command isolation after any anomaly;
  - outcome classification: completed, awaiting input, exception, timeout, crash.
- Checks CMD-002/004 and RUN-001…003.
- Synthetic defect plugins SD-01…SD-11 and SD-16, from the spike code.

**Done when (M2):** each synthetic plugin triggers **exactly** its expected check, and SD-01 is all green.

## Step 14: Scenarios, recommendation & HTML report
**Tasks:** P1-T26…T29 · **Week:** 6
- Scenario YAML runner (open, run, assert, save_as, script) and `mta scenario new` / `from-features`.
- Recommendation engine and exit codes.
- Single-file offline `report.html`:
  - banner;
  - version matrix;
  - findings with evidence;
  - command table;
  - inventory;
  - listing screenshots.

**Done when:** one end-to-end `mta run --kit` produces both reports, and a reviewer can understand the result without help.

## Step 15: Corpus run, tuning & Phase 1 demo → ★ Phase 1 exit
**Tasks:** P1-T01, P1-T30…T33 · **Week:** 6
- Corpus runner and accuracy metrics (recall, false positives, agreement, determinism).
- Run on the real Autodesk corpus **on the dedicated test machine** ×3, then tune thresholds and fix false alarms.
- Demo to the Autodesk Marketplace team; retrospective; update the Phase 2 specs.

**Done when:** exit criteria E1.1–E1.4 ([roadmap.md](../00-foundation/roadmap.md)) are met.

---

## Dependencies on Autodesk

| Needed for step | Item |
|---|---|
| 2 / 12 | Unattended licensing confirmation (D-LIC) |
| 1 / 15 | Dedicated non-domain test machine; AutoCAD 2025 install |
| 5 (ideally) / 15 (latest) | Manual review checklist (D-CHECKLIST) |
| 15 | ≥8 real plugin submissions with verdicts (D-CORPUS) |

## Progress tracker

| Step | Status |
|---|---|
| 1 Prerequisites | ✅ done: [docs/workstation.md](../../docs/workstation.md). Open with owners: AutoCAD 2025, WER dumps (admin), dedicated machine, Autodesk inputs |
| 2 Console spike | ✅ done: 21 findings in ADR-0003. Open: autoloader (F16), unattended licence (F21) → dedicated machine |
| 3 Command-lookup spike | ✅ done: `getcname` lookup, collision behaviour, 506-command list for 2026 (ADR-0003 F22–F26). List moves to `data/autocad/2026/commands.txt` in step 4. |
| 4 Repo & CI | ✅ done: git repo, `mta --version`, ruff/mypy/pytest green, `dotnet/Mta.slnx` builds with 0 warnings (MSB3277 fixed), SD-01 builds, CI workflow written (not yet run on a remote) |
| 5 Models & config | ✅ done: Pydantic models + 5 generated JSON Schemas (drift-tested), sample report validates, 4 config files with validated loader and cross-checks, `mta config validate` / `mta schema export\|check`, 40 tests (98% coverage) |
| 6 Intake & Input Kit | ✅ done: `mta kit init/validate`, `mta run --kit` / `mta run <pkg>` (intake only), Defender scan before parsing, content-addressed store, PDF/DOCX/HTML/MD text extraction + command-mention index, 84 tests. Demo on the real SD-01 bundle. Kit pre-fill of products/commands follows in steps 8–9; `scenario from-features` and screenshots in the report in step 14. |
| 7 Extraction | ✅ done: safe ZIP extraction (traversal, drive/ADS, reserved names, symlinks, encryption, case duplicates, ratio bomb, limits, long paths; nothing left on failure), MSI tables via `msi.dll` read-only + custom-action inventory, guarded `msiexec /a` (refused when admin sequences run code), PKG-001…003 written to `checks/static-package.json`, payload hashed and stored, 135 tests. Demo: SD-01 packaged as a real MSI (embedded cabinet) extracts byte-identical; a zip-slip ZIP gets PKG-001 FAIL. |
| 8 Manifest checks | ✅ done: bundle locator, defusedxml parser (DTD/entities refused, case-insensitive names), per-component RuntimeRequirements → host versions (`bundle.json`), PKG-004…006 and MAN-001…004/006/007 (MAN-005 needs step 9), `kit init` pre-fill (version, title, publisher, products, commands; MSI tables only before the scan), 180 tests. Demo: SD-01 passes every rule and maps to AutoCAD 2025/2026. |
| 9 Binary inspection | ✅ done: `mta-inspect` (C#, metadata only; commands with every `CommandMethod` overload, flags, `CommandClass` registration, extension apps, P/Invoke, URLs, type/member refs, obfuscation, `--enum`), ARX imports via pefile, BIN-001…009 per host version, CMD-003, MAN-005 drift, `config/static_rules.yaml`, verified `CommandFlags` table, `kit init` pre-fills binary commands. Tests: 15 xUnit on fixtures (fake `AcCoreMgd`, no AutoCAD needed), 215 Python. Demo: the spike plugins and SD-01 are correctly described. `SpikeUiPlugin` is core-console compatible (F27, which corrects the original expectation). |
| 10 Signing/malware/listing → M1 | ⬜ |
| 11 Probe | ⬜ |
| 12 Runner & loading | ⬜ |
| 13 Smoke & synthetic plugins → M2 | ⬜ |
| 14 Scenarios & report | ⬜ |
| 15 Corpus & demo → exit | ⬜ |
