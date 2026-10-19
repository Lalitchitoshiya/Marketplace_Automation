# Architecture

## 1. Component view

```
                 ┌─────────────────────────────────────────────────────────────┐
 Publisher       │                     MTA Control Plane                        │
 Corner  ──(P5)──▶ Intake API ──▶ Job Queue ──▶ Orchestrator ──▶ Report Builder │──▶ Reviewer
 CLI     ──(P1)──▶     │                         │      ▲            │           │    Dashboard
                 │     ▼                         │      │            ▼           │    (P2+)
                 │  Artifact Store (SHA-256)     │   Check Engine   Report Store  │
                 └───────────────────────────────┼──────┼──────────────────────────┘
                                                 │      │ CheckResults
                         ┌───────────────────────┼──────┼──────────────────────┐
                         │      Static Analyzer  ▼      │  (no code execution)  │
                         │  package · manifest · binaries · signing · listing   │
                         └──────────────────────────────────────────────────────┘
                                                 │ Run(host, version)
                         ┌───────────────────────▼──────────────────────────────┐
                         │                Execution Plane                        │
                         │  Sandbox Provider (P1 local-isolated / P2+ Hyper-V VM)│
                         │   ┌──────────────── VM / isolated env ─────────────┐ │
                         │   │ Agent (mta-agent) ──▶ Host Adapter runtime      │ │
                         │   │        │               │                       │ │
                         │   │        │      Autodesk Host process            │ │
                         │   │        │      ├── Plugin under test            │ │
                         │   │        │      └── Probe ──NDJSON──▶ events file │ │
                         │   │  Monitors (Sysmon/ETW, screen recorder) (P2+)  │ │
                         │   └─────────────────────────────────────────────────┘ │
                         └──────────────────────────────────────────────────────┘
```

## 2. Components

| Component | Responsibility | Introduced |
|---|---|---|
| **CLI** (`mta`) | Run jobs locally, inspect results, manage corpus | P1 |
| **Intake** | Accept a package + listing metadata, compute hashes, build the `Submission` record | P1 (CLI), P2 (REST), P5 (Publisher Corner) |
| **Artifact Store** | Content-addressed storage for packages, evidence and reports | P1 (local FS), P2 (Azure Blob / S3, configurable) |
| **Job Queue** | Queue `Run`s, apply retries, concurrency per host licence pool | P2 |
| **Orchestrator** | Plan the job: detect host(s) and versions, fan out Runs, collect results | P1 |
| **Static Analyzer** | Check plugins without executing them: package, manifest, binaries, signatures, listing | P1 |
| **Check Engine** | Turn probe events + monitor data into `CheckResult`s using catalog rules | P1 |
| **Host Adapter** | Per-product: deploy, launch, drive the probe, collect artifacts | P1 (AutoCAD) → P5 (all) |
| **Probe** | In-process observer and actor inside the host | P1 (AcProbe) → P5 |
| **Sandbox Provider** | Supply a clean environment per Run and destroy or reset it afterwards | P1 local, P2 Hyper-V |
| **mta-agent** | Small service inside the VM. Receives a Run spec, executes the adapter, uploads artifacts. | P2 |
| **Monitors** | Sysmon/ETW (FS, registry, network, process), screen recording, crash-dump capture | P2 |
| **Report Builder** | Render `report.json` → `report.html`. Compute the recommendation. | P1 |
| **Dashboard** | Reviewer UI: queue, reports, evidence viewer, overrides | P2 (v1), P5 (v2) |
| **AI Feature Tester** | Turn listing claims into scenarios; run a computer-use agent for exploratory testing | P5 |

## 3. Job lifecycle

```
RECEIVED → STATIC_ANALYSIS → PLANNED → RUNNING (n Runs in parallel) → AGGREGATING → REPORTED
                 │                                   │
                 └── blocker found → still run dynamic (configurable: fail_fast=false)
```

A single Run, per (host, version):

```
1 provision sandbox (clean snapshot)
2 deploy probe
3 install / deploy plugin
4 launch host (headless or GUI)
5 probe: LOAD phase  → load events, registered commands, UI inventory
6 probe: SMOKE phase → invoke each command (timeout, cancel)
7 probe: SCENARIO phase → run scenarios
8 close host → collect logs, dumps, monitor traces, screenshots
9 uninstall + post-uninstall launch check (P2+)
10 destroy / revert sandbox
```

## 4. Repository layout

```
/specs                     ← this folder (source of truth)
/config
  hosts.yaml               ← host matrix (versions, paths, runtimes)
  checks.yaml              ← check catalog runtime config (enabled, severity overrides)
  thresholds.yaml
/src
  /mta                     ← Python package (orchestrator, CLI, static analyzer, check engine, reports)
    /cli
    /intake
    /static
    /engine
    /adapters
      /base                ← Host Adapter Contract (Protocol classes)
      /autocad
      /revit ...
    /sandbox
    /report
  /probes
    /AcProbe               ← C# (multi-target net48;net8.0-windows)
    /RvtProbe              ← P3
    /InvProbe              ← P4
    /py_probes             ← Fusion / 3ds Max / Maya (P4–P5)
  /agent                   ← mta-agent (P2)
  /dashboard               ← P2
/corpus                    ← golden corpus manifests (binaries stored outside git)
/scenarios                 ← reviewer-authored scenario YAMLs, per app
/tests
/adr
```

## 5. Technology choices
| Concern | Choice | ADR |
|---|---|---|
| Orchestrator language | Python 3.12 | [ADR-0001](../adr/ADR-0001-python-orchestrator-csharp-probes.md) |
| In-host probes | C# for .NET hosts, Python for Python-hosted products | ADR-0001 |
| Probe → orchestrator channel | NDJSON event file plus a control file (no sockets in Phase 1) | [ADR-0002](../adr/ADR-0002-ndjson-probe-protocol.md) |
| AutoCAD Phase 1 runtime | AcCoreConsole headless | [ADR-0003](../adr/ADR-0003-accoreconsole-for-phase-1.md) |
| Sandbox | Hyper-V VMs with checkpoints | [ADR-0004](../adr/ADR-0004-hyperv-sandbox.md) |
| .NET static inspection | `System.Reflection.Metadata` via a small C# CLI (`mta-inspect`) | ADR-0001 |
| GUI automation | FlaUI (UIA3) | Phase 2 design |
| Behaviour monitoring | Sysmon + ETW | Phase 2 design |
| Reports | JSON (schema-validated) + Jinja2 HTML | — |
