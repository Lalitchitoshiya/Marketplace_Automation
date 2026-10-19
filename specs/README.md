# Marketplace Test Automation (MTA) — Specifications

Spec-driven development (SDD) workspace for the Autodesk Marketplace submission-testing POC.

**The spec is the source of truth.** Code is written to satisfy a spec. If the code needs to change, the spec changes first.

## How to read this folder

**New here? Start with [OVERVIEW.md](OVERVIEW.md)**: the problem, the idea and the plan in plain language (5-minute read).

| Folder / file | Purpose |
|---|---|
| [OVERVIEW.md](OVERVIEW.md) | Big picture for everyone: problem, solution idea, phases, benefits |
| [00-foundation/constitution.md](00-foundation/constitution.md) | Non-negotiable engineering principles. Read first. |
| [00-foundation/product-vision.md](00-foundation/product-vision.md) | Problem, goals, personas, scope, success metrics |
| [00-foundation/roadmap.md](00-foundation/roadmap.md) | The 5 phases, what each delivers, exit criteria |
| [00-foundation/architecture.md](00-foundation/architecture.md) | System components, data flow, repo layout |
| [00-foundation/tech-stack.md](00-foundation/tech-stack.md) | Product form (CLI → web app → automatic service) and technologies per layer |
| [00-foundation/host-adapter-contract.md](00-foundation/host-adapter-contract.md) | Interface every Autodesk product adapter implements |
| [00-foundation/probe-protocol.md](00-foundation/probe-protocol.md) | How in-host probes report events back (NDJSON) |
| [00-foundation/submission-inputs.md](00-foundation/submission-inputs.md) | Input Kit: how the package, user guide, screenshots, samples and feature hints are given to MTA |
| [00-foundation/data-contracts.md](00-foundation/data-contracts.md) | Submission, Job, CheckResult, Report schemas |
| [00-foundation/check-catalog.md](00-foundation/check-catalog.md) | Every automated check: ID, severity, phase, applicability |
| [00-foundation/scenario-dsl.md](00-foundation/scenario-dsl.md) | YAML format for workflow / feature test scenarios |
| [00-foundation/host-matrix.md](00-foundation/host-matrix.md) | Products × versions × runtime facts (config-driven) |
| [00-foundation/security-and-isolation.md](00-foundation/security-and-isolation.md) | Handling untrusted third-party binaries safely |
| [00-foundation/testing-strategy.md](00-foundation/testing-strategy.md) | How we test the tester: golden corpus, accuracy metrics |
| [00-foundation/glossary.md](00-foundation/glossary.md) | Terms |
| [phase-1-autocad-headless/](phase-1-autocad-headless/) | **POC**: AutoCAD plugin static + headless sanity. See [steps.md](phase-1-autocad-headless/steps.md) for the 15-step execution plan and prerequisite status. |
| [phase-2-autocad-complete/](phase-2-autocad-complete/) | AutoCAD GUI, sandbox VMs, monitoring, verticals |
| [phase-3-aec-hosts/](phase-3-aec-hosts/) | Revit, Navisworks, Robot Structural Analysis |
| [phase-4-manufacturing-hosts/](phase-4-manufacturing-hosts/) | Inventor, Fusion, Vault, Alias |
| [phase-5-media-ai-production/](phase-5-media-ai-production/) | 3ds Max, Maya, AI feature testing, production rollout |
| [adr/](adr/) | Architecture Decision Records |

Each phase folder contains:

- `requirements.md`: user stories and acceptance criteria in **EARS** notation (`WHEN <trigger> THE SYSTEM SHALL <response>`).
- `design.md`: how the requirements are met (components, sequences, interfaces).
- `tasks.md`: ordered, trackable implementation tasks. Each task traces back to the requirements it satisfies.

## SDD workflow

```
1. Specify   → edit requirements.md (what & why)          → review with Autodesk QA lead
2. Design    → edit design.md (how)                        → tech review
3. Plan      → edit tasks.md (ordered, traceable tasks)    → sprint planning
4. Implement → code + tests; PR references task IDs        → CI green
5. Verify    → acceptance criteria demonstrated on corpus  → phase exit review
6. Evolve    → spec change PR first, code PR second
```

## ID conventions

| Kind | Format | Example |
|---|---|---|
| Requirement | `P<phase>-R<nn>` | `P1-R07` |
| Task | `P<phase>-T<nn>` | `P1-T12` |
| Check | `<FAMILY>-<nnn>` | `MAN-004` |
| ADR | `ADR-<nnnn>` | `ADR-0002` |
| Open question | `P<phase>-Q<nn>` | `P1-Q03` |

## Status

| Phase | Status |
|---|---|
| 0 Foundation | Draft v0.1 |
| 1 AutoCAD headless | Draft v0.1 |
| 2 AutoCAD complete | Draft v0.1 |
| 3 AEC hosts | Draft v0.1 |
| 4 Manufacturing hosts | Draft v0.1 |
| 5 M&E + AI + production | Draft v0.1 |
