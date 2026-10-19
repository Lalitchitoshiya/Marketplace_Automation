# Product Vision

## Problem
Publishers submit apps to the Autodesk Design & Make Marketplace: desktop plugins / add-ins, web apps, content, training material and MCP servers. Every new submission and every version update is tested **manually** by Autodesk reviewers or testers. A typical desktop-plugin review involves:

1. Downloading the package and installing it on a machine with the right product year.
2. Launching the product and confirming the plugin loads: ribbon, commands, no error dialogs.
3. Running the main commands and workflows described in the listing on sample data.
4. Repeating for every declared product version (e.g. AutoCAD 2024–2027) and sometimes verticals (Civil 3D, Plant 3D…).
5. Checking signing, privacy policy, support email and listing consistency.
6. Uninstalling and confirming the product is unaffected.

This takes hours per submission, scales linearly with the version matrix, and is error-prone and inconsistent between reviewers.

## Vision
> Within minutes of a submission, the reviewer opens one report that shows exactly what the plugin did in every declared product version, with evidence. Their job shrinks from "test everything" to "judge the flagged items."

## Goals
| # | Goal | Measured by |
|---|---|---|
| G1 | Cut manual review effort per desktop submission | ≥70% reduction in reviewer hours (baseline measured in Phase 1) |
| G2 | Consistent, reproducible reviews | Same input → same deterministic verdicts, 100% |
| G3 | Cover the full declared version matrix | 100% of declared versions tested automatically |
| G4 | Catch defects before reviewers do | ≥90% of manually found blocking defects in the corpus also flagged by MTA |
| G5 | Low false-alarm rate | ≤10% of MTA `FAIL`s overturned by reviewers |
| G6 | Support every Marketplace desktop host | All hosts in [host-matrix.md](host-matrix.md) by end of Phase 5 |

## Non-goals (POC)
- Replacing the human reviewer or publishing automatically (see Constitution §1).
- Testing **web apps** and **MCP servers**. These are tracked as a post-Phase-5 extension. The architecture keeps room for them: the adapter contract is host-agnostic.
- Testing content-only listings (families, blocks, materials) and training material beyond package / static checks.
- Performance benchmarking of plugin algorithms.
- Testing publisher back-end services.

## Personas
| Persona | Needs |
|---|---|
| **Reviewer / Tester** (Autodesk Marketplace team) | One trustworthy report, evidence for every finding, fast re-runs, ability to add scenarios |
| **Marketplace QA Lead** | Throughput metrics, consistency, a defect taxonomy, confidence before turning a check into a blocking check |
| **MTA Developer** (us) | Clear contracts, easy to add a host or check, reproducible runs |
| **Publisher** (indirect, **no access**) | Benefits only indirectly: faster reviews, clearer rejection reasons written by the reviewer. Publishers never use MTA or see its output (Constitution §11). |

## Scope by phase (summary; detail in [roadmap.md](roadmap.md))
| Phase | Hosts | Capability |
|---|---|---|
| 1 | AutoCAD | Static analysis + headless (Core Console) load / command sanity + scenarios + report |
| 2 | AutoCAD + verticals | GUI testing, ribbon/UI, disposable VMs, install/uninstall, behaviour monitoring, version matrix, queue + dashboard v1 |
| 3 | Revit, Navisworks, Robot | Adapter SDK generalised; AEC adapters |
| 4 | Inventor, Fusion, Vault, Alias | Manufacturing adapters, server-dependent hosts (Vault) |
| 5 | 3ds Max, Maya | Python-hosted adapters, AI feature testing, Publisher Corner integration, production hardening |
