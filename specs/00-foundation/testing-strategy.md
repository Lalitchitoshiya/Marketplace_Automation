# Testing Strategy — "Testing the Tester"

## 1. Test levels for MTA itself
| Level | What | Tooling | Gate |
|---|---|---|---|
| Unit | Parsers, check rules, recommendation logic, DSL parser | pytest, xUnit (probes) | PR |
| Contract | JSON schemas, probe events, adapter conformance | pytest + jsonschema | PR |
| Adapter conformance | Known-good / known-bad sample plugins per host | `tests/adapter_conformance` on host machines/VMs | Nightly + release |
| Corpus accuracy | Full MTA on golden corpus vs manual verdicts | `mta corpus run` | Phase exit, weekly |
| Security | Malicious samples (EICAR, zip-slip, XXE, persistence, egress) | dedicated corpus | Phase exit |

## 2. Golden corpus
The corpus has two parts:
- **Real apps.** Free or with permission, from the Marketplace, with **manual verdicts** recorded by an Autodesk reviewer using the standard checklist.
- **Synthetic defect plugins** that we build. Each one injects exactly one defect class.

### Synthetic defect classes (built per host)
| ID | Defect | Expected check |
|---|---|---|
| SD-01 | Clean, well-behaved plugin | all PASS |
| SD-02 | Throws in `Initialize()` / `OnStartup` | LOD-001 |
| SD-03 | Command throws NullReferenceException | CMD-002 / RUN-002 |
| SD-04 | Command hangs (infinite loop) | CMD-004 |
| SD-05 | Command crashes the host (native access violation) | RUN-001 |
| SD-06 | Wrong target framework for version | BIN-001 |
| SD-07 | Missing dependency DLL | BIN-004 / LOD-001 |
| SD-08 | Ships host API DLLs | BIN-005 |
| SD-09 | Manifest points to a non-existent module | MAN-004 |
| SD-10 | Unsigned binaries | SIG-001 |
| SD-11 | EICAR test file inside the package | SIG-003 |
| SD-12 | Writes HKLM Run key | FS-003 (P2) |
| SD-13 | Calls undeclared HTTP endpoint | NET-002/003 (P2) |
| SD-14 | Leaves files after uninstall | UNI-002 (P2) |
| SD-15 | Nag dialog at startup | UI-004 (P2) |
| SD-16 | Command name collides with built-in (`LINE`) | CMD-003 |
| SD-17 | Builds a ribbon tab in `Initialize` (GUI only) | LOD-001 NEEDS_REVIEW (requires GUI host) |

## 3. Accuracy metrics
For each check family and overall, measured on the corpus:
- **Detection rate (recall)** = MTA-flagged true defects ÷ manual-found defects. Target ≥90% (P1–P2), ≥85% (P3–P4 new hosts).
- **False-positive rate** = MTA FAILs overturned by the reviewer ÷ MTA FAILs. Target ≤10%.
- **Recommendation agreement** = matching job recommendation ÷ jobs.
- **Determinism** = identical deterministic results across 3 re-runs. Target 100%.
- **Throughput** = wall-clock per (plugin × version).

Results are written to `corpus/results/<date>.json` and trended on the dashboard (P2+).

## 4. Baseline measurement (Phase 1, task P1-T01)
Before building, time 5 real manual reviews (checklist step by step) to establish the reviewer-hours baseline for goal G1.
