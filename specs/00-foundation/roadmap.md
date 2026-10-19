# Roadmap — 5 Phases

Durations assume 3–4 engineers. Each phase ends with an **exit review** against its exit criteria, run on the golden corpus ([testing-strategy.md](testing-strategy.md)).

```
Phase 1  AutoCAD headless POC          ██████                 (6 wks)
Phase 2  AutoCAD complete + sandbox          ████████         (8 wks)
Phase 3  AEC: Revit/Navisworks/Robot                 ████████ (8 wks)
Phase 4  Manufacturing hosts                                 ████████ (8 wks)
Phase 5  M&E + AI + production                                      ██████████ (10 wks)
```

---

## Phase 1 — AutoCAD Headless Sanity (POC)
**Goal:** prove that an AutoCAD plugin submission can be validated end-to-end without a human, on one Windows machine.

Delivers:
- CLI `mta run <package>` that ingests an MSI / `.bundle` / ZIP.
- Static analysis: package structure, `PackageContents.xml`, .NET binary inspection, signing, malware scan, listing basics.
- AutoCAD adapter using **AcCoreConsole** (headless): load each component, verify commands are registered, smoke-invoke each command, run reviewer scenarios.
- In-host **AcProbe** (.NET) that emits NDJSON events.
- JSON + HTML report with evidence and overall recommendation.
- Golden corpus v1 (≥15 AutoCAD plugins).

**Exit criteria:**
- E1.1 Corpus run: ≥90% agreement with manual verdicts on blocking defects.
- E1.2 ≤15 min per plugin per AutoCAD version on a dev workstation.
- E1.3 Deterministic re-runs (identical deterministic check results).
- E1.4 Demo to Autodesk Marketplace team accepted.

## Phase 2 — AutoCAD Complete
**Goal:** cover everything a reviewer does for an AutoCAD plugin, safely and across the full version matrix.

Delivers:
- Disposable Windows VM sandbox (Hyper-V checkpoints) with a pool manager.
- Real MSI install / uninstall testing.
- GUI AutoCAD runner (`acad.exe`) with FlaUI: autoloader, ribbon/CUI inventory, button → command execution, dialog capture, screenshots, video.
- Behaviour monitoring (Sysmon/ETW): file, registry, process and network activity; persistence detection.
- Version matrix (2024–2027) and **AutoCAD verticals**: Civil 3D, Map 3D, Plant 3D, Electrical, Mechanical, MEP, Architecture, Advance Steel.
- Job queue, REST API, reviewer dashboard v1.

**Exit criteria:** ≥90% agreement on the extended corpus (≥40 plugins), zero sandbox escapes in security tests, ≤30 min wall-clock for a 4-version matrix (parallel VMs).

## Phase 3 — AEC Hosts
**Goal:** generalise the adapter SDK and support Revit, Navisworks and Robot Structural Analysis.

Delivers: Adapter SDK v1 (extracted from AutoCAD), the RvtProbe (Revit), Revit journal-based automation, the Navisworks probe (Automation API), the Robot probe (RobotOM COM), `.addin` manifest validation, and sample-model library.

**Exit criteria:** ≥85% agreement on the Revit corpus (≥30 add-ins), all three hosts green on the corpus, and a new host can be added by implementing the contract without changes to the orchestrator.

## Phase 4 — Manufacturing Hosts
**Goal:** Inventor, Fusion, Vault (client + server), Alias.

Delivers: InvProbe (COM / in-process add-in), the Fusion Python harness add-in with sign-in handling, a Vault test-server fixture plus Vault client extension probe, Alias plugin load checks (stretch), and Python and C++ static analysis.

**Exit criteria:** ≥85% agreement on the manufacturing corpus, and Vault server fixture reset in <10 min.

## Phase 5 — Media & Entertainment, AI, Production
**Goal:** complete host coverage, add intelligent feature testing, and run in production.

Delivers:
- 3ds Max adapter (`3dsmaxbatch`, pymxs) and Maya adapter (`mayapy`, `maya.standalone`, modules).
- **AI Feature Tester:** extracts claims from the listing, generates scenarios, explores the UI with a computer-use agent, and checks screenshot consistency.
- Publisher Corner integration (automatic trigger on submission and update).
- Reviewer dashboard v2: diff between versions of the same app, re-run, override with reason, analytics.
- Production hardening: scaling, observability, retention, access control, runbooks.

**Exit criteria:** all hosts in [host-matrix.md](host-matrix.md) supported, AI claims coverage ≥70% of listing claims with ≤10% hallucinated findings, and 4 weeks of shadow-mode operation alongside manual review with G1–G5 met.

---

## Post-POC backlog (not in the 5 phases)
- Web app adapter: Playwright, APS OAuth, scopes, HTTPS, privacy.
- MCP server adapter: manifest ↔ `tools/list` diff, egress vs `external_endpoints`, description-injection scan, schema fuzzing.

**Explicitly excluded:** a publisher self-check / pre-submission portal. Publishers must not be able to learn in advance whether a submission passes (Constitution §11).
- Content-only listings (Revit families, blocks): deep validation.
