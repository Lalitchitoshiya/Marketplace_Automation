# ADR-0004: Hyper-V VMs with checkpoints as the sandbox (Phase 2+)

**Status:** Proposed · **Date:** 2026-10-19 · **Decision owner:** Phase 2 tech lead + Autodesk infra

## Context
Untrusted plugins must execute in disposable environments with full Autodesk desktop products. Those products are large GUI apps that need GPU-less rendering, licensing and a full Windows install.

## Options
| Option | Pros | Cons |
|---|---|---|
| **Hyper-V VMs + checkpoints** | Full Windows; fast revert; PowerShell Direct (no guest network needed); mature | Needs Windows hosts; image size (~60–100 GB per host version) |
| Windows Sandbox | Very fast and disposable | No persistent pre-installed Autodesk products; licensing/activation each time; limited automation |
| Windows containers | Lightweight | Autodesk desktop GUI products not supported in containers |
| Azure VMs (no nesting) | Elastic | Slower reset (redeploy from image), higher cost per run |
| Azure with nested Hyper-V | Elastic + checkpoints | More complex networking; cost |

## Decision (proposed)
Hyper-V with checkpoints. The same automation (`mta-hostd`) runs on-prem or on Azure hosts that support nested virtualisation. The final hosting choice is open question P2-Q04.

## Consequences
- Packer-based image pipeline per host version (P2-R02).
- Licence-server reachability from the isolated network must be solved with Autodesk (D-LIC).
