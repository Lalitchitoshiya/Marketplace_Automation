# Tech Stack & Product Form

## 1. What kind of product is MTA?

MTA is **not a desktop app**. It grows in form across the phases:

| Phase | Product form | Who uses it | How |
|---|---|---|---|
| **1** | **Command-line tool (CLI)** `mta` + an **HTML report file** | Our team + 1–2 Autodesk reviewers | `mta run MyPlugin.msi` on a Windows test machine with AutoCAD → opens `report.html` in a browser |
| **2–4** | **Internal web application** (dashboard + REST API) + **backend workers** on test-machine servers | All Marketplace reviewers | Upload or select a submission in the browser → watch progress → read the report, view screenshots / video, override findings |
| **5** | **Fully automatic service** connected to Publisher Corner | Whole Marketplace team | Nothing to start: every new submission is tested automatically, and the report link appears in the review record |

The CLI stays available in every phase for developers, debugging and corpus runs.

**Why not a desktop app?**
- The heavy work (running AutoCAD, Revit… in virtual machines) happens on **servers**, not on the reviewer's laptop.
- Several reviewers need to **share** the same results, history and overrides.
- A web dashboard needs no installation, and reviewers can open the report from anywhere on the Autodesk network.

```
Phase 1:   Reviewer PC ── mta CLI ── AutoCAD (headless) ──► report.html

Phase 2+:  Browser ──► Web dashboard + API (server) ──► Job queue
                                                          │
                                       VM host servers ◄──┘
                                       (disposable VMs running AutoCAD, Revit, …)
```

## 2. Tech stack by layer

| Layer | Technology | Phase | Why |
|---|---|---|---|
| **CLI & orchestrator** | Python 3.12, Typer (CLI), Pydantic (data models), psutil (process control) | 1 | Fast to build; strong libraries for automation, parsing, reporting and AI |
| **Static analysis** | Python: `pefile`, `defusedxml`, `dnspython`, `requests` | 1 | Read binaries and manifests safely without running them |
| **.NET inspection** | `mta-inspect`: C# / .NET 8, `System.Reflection.Metadata` | 1 | Reads plugin DLLs (commands, versions, references) without loading them |
| **In-product probes** | C# (multi-target .NET Framework 4.8 + .NET 8) for AutoCAD, Revit, Inventor, Navisworks, Vault | 1 → 4 | Must run inside the product's own .NET runtime |
| | Python probes for Fusion, 3ds Max, Maya | 4 → 5 | These products host Python plugins |
| **Malware / signature** | Microsoft Defender CLI (`MpCmdRun`), PowerShell `Get-AuthenticodeSignature` | 1 | Built into Windows |
| **Reports** | JSON (schema-validated) + Jinja2 → single-file HTML | 1 | Works offline; easy to attach and share |
| **UI automation** | FlaUI (C#, UIA3) | 2 | Clicks ribbon buttons, detects and closes dialogs |
| **Screen recording** | ffmpeg | 2 | Video evidence |
| **Behaviour monitoring** | Sysmon + ETW, `python-evtx` parser | 2 | Records files, registry and network activity |
| **Sandbox / test machines** | Hyper-V VMs + checkpoints; PowerShell Direct | 2 | Disposable, resettable Windows machines with Autodesk products |
| **VM image building** | Packer + PowerShell | 2 | Rebuilds test machines from code, reproducibly |
| **Backend API** | FastAPI (Python) | 2 | Same language as the orchestrator; automatic OpenAPI docs |
| **Database** | PostgreSQL + SQLAlchemy + Alembic | 2 | Jobs, results, overrides, history |
| **Job queue** | Redis + Celery | 2 | Distributes test runs to VM hosts; retries |
| **Web dashboard** | Server-rendered: FastAPI + Jinja2 + **HTMX**, video.js for video | 2 | Simple and fast to build for an internal tool; can move to React if the UI becomes complex |
| **Login / security** | OIDC single sign-on (Autodesk corporate login), role-based access | 2 | Reviewers use their Autodesk accounts |
| **File storage** | Azure Blob / AWS S3 / MinIO (whatever Autodesk approves) | 2 | Packages, screenshots, videos, logs |
| **Secrets** | Azure Key Vault or HashiCorp Vault | 4 | Test-account passwords (Fusion, Vault) |
| **AI feature testing** | Claude via an Autodesk-approved endpoint (Anthropic SDK) | 5 | Reads listing claims, generates tests, explores the UI, judges results |
| **Observability** | OpenTelemetry, Prometheus, Grafana | 5 | Monitoring and alerts in production |
| **Deployment** | Docker containers; Kubernetes (or Autodesk's platform) in Phase 5 | 2 → 5 | Standard, scalable |
| **CI/CD** | GitHub Actions or Azure DevOps, with **self-hosted Windows runners** that have Autodesk products installed | 1 | Probe tests need real AutoCAD / Revit |
| **Code quality** | Python: ruff, mypy, pytest · C#: xUnit, nullable enabled, warnings as errors | 1 | Constitution §12 |

## 3. Languages summary

| Language | Used for | Share of code (estimate) |
|---|---|---|
| **Python** | CLI, orchestrator, checks, reports, API, dashboard, AI, Python probes | ~65% |
| **C#** | Probes inside .NET products, mta-inspect, FlaUI runner | ~30% |
| **PowerShell** | VM control, image building | ~5% |
| HTML / CSS / HTMX | Report and dashboard templates | small |

The team therefore needs **Python + C# (.NET) skills**, plus basic Windows / Hyper-V administration from Phase 2.

## 4. Phase 1 development setup

- A Windows 11 machine (not domain-joined) with **AutoCAD 2025 and 2026**.
- Python 3.12 + `uv` (package manager).
- .NET 8 SDK + Visual Studio 2022 / Rider (for probes and mta-inspect).
- Git repository + CI with one self-hosted Windows runner that has AutoCAD installed.

Decisions behind this stack: [ADR-0001](../adr/ADR-0001-python-orchestrator-csharp-probes.md), [ADR-0002](../adr/ADR-0002-ndjson-probe-protocol.md), [ADR-0003](../adr/ADR-0003-accoreconsole-for-phase-1.md), [ADR-0004](../adr/ADR-0004-hyperv-sandbox.md).
