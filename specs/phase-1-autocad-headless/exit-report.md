# Phase 1 exit report: AutoCAD headless

Status on 2026-10-20, after step 15. Exit criteria come from [roadmap.md](../00-foundation/roadmap.md) (E1.1–E1.4); the steps from [steps.md](steps.md).

## 1. Exit criteria

| Criterion | Target | Measured | Status |
|---|---|---|---|
| E1.1 Agreement with manual verdicts on blocking defects | ≥ 90 % | **100 %** on the synthetic corpus: 11 cases, every case triggers exactly its expected checks, in all 3 passes | ✅ on synthetic data · ⏳ real corpus needs D-CORPUS |
| E1.2 Time per plugin per AutoCAD version | ≤ 15 min | **max 0.72 min, mean 0.30 min** (static + baseline + load + smoke, AutoCAD 2026, dev workstation) | ✅ |
| E1.3 Deterministic re-runs | identical | **100 %**: identical not-green check sets in 3 full passes | ✅ |
| E1.4 Demo accepted by the Autodesk Marketplace team | accepted | Demo script ready: [docs/demo-phase1.md](../../docs/demo-phase1.md) | ⏳ needs the session with Autodesk |

Also measured: recall 100 % and false-positive rate 0 % (`mta corpus run --repeat 3 --out …`). Synthetic-corpus numbers show that the checks work as designed. They are not evidence of accuracy on real submissions; E1.1 must be repeated on the real corpus.

## 2. What Phase 1 delivers
- **`mta inspect`** (static only) and **`mta run`** (static + AutoCAD core console). Both write `report.json` (schema-valid) and an offline `report.html`. Exit codes: 0 approve, 10 needs human, 20 reject.
- **Static checks:** all 29 static Phase 1 checks in the catalog (package, manifest, binaries, signing, malware, listing).
- **Dynamic checks:**
  - loading: LOD-001…003;
  - commands: CMD-001/002/004, with batch smoke and recovery after crashes or hangs;
  - runtime health: RUN-001…003;
  - scenarios: WFL-001/002 (scenario DSL v1, `mta scenario new / from-features / check`).
- **Safety:**
  - a malware scan before parsing and again after extraction;
  - a dynamic gate;
  - guarded MSI extraction;
  - crash-reporter containment;
  - an undetectable probe (neutral names, generated identity, scanned binary).
- **AutoCAD 2026 and 2027** are verified (`mta doctor --deep` HEALTHY on both). 2025 and 2024 are configured but not installed here.
- **Synthetic corpus:** SD-01…SD-11, SD-16 and SD-17, built per API major (`mta corpus build`), and the accuracy runner (`mta corpus run`).

## 3. Open: needs Autodesk or the test environment

| Item | Why it matters | Owner |
|---|---|---|
| Real corpus: ≥ 8 submissions with verdicts (D-CORPUS) | E1.1 on real data, threshold tuning (P1-T32) | Autodesk |
| Review checklist (D-CHECKLIST), workshop P1-T01 | Confirms Phase 1 scope against the manual process | Autodesk |
| Dedicated non-domain test machine, AutoCAD 2025 (+2024) | Real third-party plugins must not run on a developer machine; 2025/2024 coverage | Autodesk / CCTech IT |
| Unattended licensing (D-LIC, F21) | Runs without a signed-in user | Autodesk |
| Trusted test code-signing certificate (P1-Q07) | A fully green SD-01 on SIG-002 | Autodesk / CCTech |
| SD-11 with EICAR (`--with-eicar`) | Must run on the test machine, where Defender alerts are expected | test machine |
| Scenarios for ≥ 5 real apps with reviewers (P1-T31) | WFL coverage on real plugins | Autodesk reviewers |
| WER LocalDumps (admin) | Optional extra crash evidence | machine admin |
| Phase 1 demo (P1-T33, E1.4) | Phase exit | CCTech + Autodesk |

## 4. Retrospective (short)
**Worked well**
- The spec-first steps.
- The spikes before building. They produced 31 findings (ADR-0003), and several of them prevented wrong designs:
  - F8: a crash kills the core console;
  - F11: an exception in Initialize is silent;
  - F14: `AcMgd` plugins run headless;
  - F24: a command named like a built-in loses silently.
- The synthetic corpus caught real bugs:
  - a host DLL shipped in the package was analysed as plugin code (SD-08);
  - two false load PASSes, caused by the recursive TRUSTEDPATHS form;
  - NEEDS_REVIEW results without evidence;
  - an `mta-inspect` crash on AutoCAD 2027's assemblies.

**Learned**
- Two "done when" criteria written before the spikes were wrong (`SpikeUiPlugin` GUI-required), so criteria should be revisited after spikes.
- Real machines differ from the plan. Examples:
  - AutoCAD 2027 was already installed;
  - Civil 3D's deep roaming folders broke `/isolate` (F28);
  - bot protection rejected HTTPS checks (LST-001);
  - the crash reporter needed containment (F29/F30).

**Carried to Phase 2:** see [phase-2 requirements §3a](../phase-2-autocad-complete/requirements.md).
