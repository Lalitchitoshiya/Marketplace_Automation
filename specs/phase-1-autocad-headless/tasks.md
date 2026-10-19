# Phase 1 — Tasks

Legend: `[ ]` todo · `[~]` in progress · `[x]` done. **Req** = requirement IDs satisfied. **DoD** = definition of done.

## Sprint 0 — Discovery (week 1)
- [ ] **P1-T01** Workshop with Autodesk: walk through the manual checklist, time 5 real reviews (baseline for G1), agree corpus and verdict format. *Req:* A-2, A-3, P1-Q06. *DoD:* `corpus/expected/*.yaml` template agreed; baseline hours recorded in `docs/baseline.md`.
- [~] **P1-T02** Prepare the reference workstation: AutoCAD 2025/2026 (+2024 optional), unattended licensing, Defender, WER LocalDumps, non-domain. *Req:* A-1. *DoD:* checklist in `docs/workstation.md`.
- [x] **P1-T03** **Spike: AcCoreConsole behaviour.** Confirm:
  - switches (`/i /s /l /isolate`);
  - stdin EOF behaviour at an active prompt;
  - `TRUSTEDPATHS` via script;
  - autoloader honoured or not;
  - exit codes on crash;
  - stdout encoding;
  - `ExtensionLoader.Load` behaviour for UI-dependent assemblies.
  
  *Req:* P1-Q01, P1-Q02, P1-Q04. *DoD:* findings in `adr/ADR-0003` addendum, and `hosts.yaml` values verified.
- [x] **P1-T04** **Spike: built-in command lists + runtime command lookup.** *Req:* P1-Q05, P1-R10, P1-R14. *DoD:* `data/autocad/<year>/commands.txt` and the chosen lookup method documented.

## Sprint 1 — Skeleton & static analysis (weeks 2–3)
- [x] **P1-T05** Repo scaffold: Python package, Typer CLI, ruff/mypy/pytest, C# solution, CI pipeline (Windows runner). *Req:* Constitution §12.
- [x] **P1-T06** Data models + JSON schemas (Submission, Job, Run, CheckResult, Report) + schema tests. *Req:* P1-R21.
- [x] **P1-T07** Config loader: `hosts.yaml`, `checks.yaml`, `thresholds.yaml` with validation. *Req:* Constitution §5.
- [x] **P1-T08** Intake + content-addressed artifact store. *Req:* P1-R01, P1-R02.
- [x] **P1-T09** Safe extraction (ZIP, MSI admin extract, MSI table read). Unit tests with zip-slip and zip-bomb fixtures. *Req:* P1-R04 (PKG-001…003).
- [x] **P1-T10** Bundle locator + `PackageContents.xml` parser and rules MAN-001…007, PKG-004…006. *Req:* P1-R05.
- [x] **P1-T11** `mta-inspect` C# tool: TFM, references, CommandMethod decoding, ExtensionApplication, P/Invoke, URLs, risky APIs, obfuscation heuristics. xUnit tests on sample assemblies. *Req:* P1-R06.
- [x] **P1-T12** Rules BIN-001…009 (incl. GUI-required classification) and ARX PE import checks. *Req:* P1-R06, P1-R07.
- [ ] **P1-T13** Signing (SIG-001/002) + Defender (SIG-003) + dynamic-phase gate. *Req:* P1-R08.
- [ ] **P1-T14** Listing checks LST-001…003 + listing schema. *Req:* P1-R09.
- [x] **P1-T15** CMD-003 collision rule. *Req:* P1-R10.
- [ ] **P1-T16** `mta inspect` end-to-end static report (JSON only). *Req:* P1-R11. **Milestone M1: static-only report on 5 corpus apps.**

## Sprint 2 — Headless execution (weeks 4–5)
- [ ] **P1-T17** AcProbe: project (multi-target), event writer, hooks, `MTAPROBE_*` commands. *Req:* P1-R13…R16.
- [ ] **P1-T18** ScriptBuilder + run-directory layout + isolated profile. *Req:* P1-R12.
- [ ] **P1-T19** CoreConsoleRunner: launch, watchdog, stdout capture/decoding, process-tree kill, dump detection. *Req:* P1-R16, P1-R17.
- [ ] **P1-T20** Baseline launch + infrastructure-error classification (licence regexes). *Req:* P1-R18.
- [ ] **P1-T21** Component loading + LOD-001…003 rules (incl. GUI-required → NEEDS_REVIEW). *Req:* P1-R13.
- [ ] **P1-T22** Command enumeration + CMD-001. *Req:* P1-R14.
- [ ] **P1-T23** Smoke invocation: batch → per-command isolation fallback, outcome classification, CMD-002/004, RUN-001…003. *Req:* P1-R15, P1-R16.
- [ ] **P1-T24** `mta doctor` (+ `--fix` for WER LocalDumps) and `mta doctor --deep` with the canary plugin (from spike code) replaying ADR-0003 findings. *Req:* P1-R03.
- [ ] **P1-T25** Synthetic plugins SD-01…11, SD-16 (net48 + net8). *Req:* P1-R26. **Milestone M2: SD corpus green (each SD triggers exactly its expected check).**

## Sprint 3 — Scenarios, reporting, corpus (week 6)
- [ ] **P1-T26** Scenario DSL parser (pydantic) + AutoCAD step translator + `MTAPROBE_ASSERT`. *Req:* P1-R19.
- [ ] **P1-T27** `mta scenario new` skeleton generator. *Req:* P1-R20.
- [ ] **P1-T28** Recommendation engine + exit codes. *Req:* P1-R23, P1-R24.
- [ ] **P1-T29** `report.html` template (banner, matrix, findings, command table, inventory). *Req:* P1-R22.
- [~] **P1-T34** Input Kit: `submission.yaml` schema, `mta kit init/validate`, `--kit` intake, doc text extraction (pdfplumber, python-docx), command-mention index, `scenario from-features`, screenshots in report. *Req:* P1-R01, P1-R27.
- [ ] **P1-T30** Corpus runner + metrics. *Req:* P1-R25.
- [ ] **P1-T31** Write scenarios for ≥5 real corpus apps with Autodesk reviewers. *Req:* P1-R19.
- [ ] **P1-T32** Full corpus run ×3 (determinism), tune thresholds, fix false positives. *Req:* E1.1–E1.3.
- [ ] **P1-T33** Phase exit demo + retrospective. Update Phase 2 specs with learnings. *Req:* E1.4.

## Traceability matrix
| Req | Tasks |
|---|---|
| P1-R01 | T08, T16 |
| P1-R02 | T08 |
| P1-R03 | T24 |
| P1-R04 | T09 |
| P1-R05 | T10 |
| P1-R06 | T11, T12 |
| P1-R07 | T12 |
| P1-R08 | T13 |
| P1-R09 | T14 |
| P1-R10 | T04, T15 |
| P1-R11 | T16 |
| P1-R12 | T18 |
| P1-R13 | T17, T21 |
| P1-R14 | T04, T22 |
| P1-R15 | T23 |
| P1-R16 | T17, T19, T23 |
| P1-R17 | T19 |
| P1-R18 | T20 |
| P1-R19 | T26, T31 |
| P1-R20 | T27 |
| P1-R21 | T06 |
| P1-R22 | T29 |
| P1-R23 | T28 |
| P1-R24 | T28 |
| P1-R25 | T30 |
| P1-R26 | T25 |
| P1-R27 | T34 |
