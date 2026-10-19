# Phase 4 — Tasks

## Sprint 1 — Foundations & Inventor (weeks 1–3)
- [ ] **P4-T01** Catalog + checks.yaml additions (BIN-010, INV-*, FUS-*, VLT-*, ALS-*). *Req:* all.
- [ ] **P4-T02** Secret store integration + account leasing + log/report redaction + artifact secret scanning. *Req:* P4-R16, P4-N04.
- [ ] **P4-T03** Python static toolkit (syntax, imports, risky, deprecations) + host module inventories from images. *Req:* P4-R06.
- [ ] **P4-T04** Inventor images 2024–2027 + sample docs per environment. *Req:* P4-R02.
- [ ] **P4-T05** Inventor `.addin` parser + INV-001 + interop version rule. *Req:* P4-R01.
- [ ] **P4-T06** InvProbe (in-process) + InvDriver (COM): activation, ControlDefinitions by ClientId, ribbon inventory. *Req:* P4-R02, P4-R03.
- [ ] **P4-T07** Inventor per-environment execution + watchdog + StopActiveCommand + INV-003/004. *Req:* P4-R03, P4-R04.
- [ ] **P4-T08** Inventor SD plugins + conformance. *Req:* P4-R18.

## Sprint 2 — Fusion (weeks 4–5)
- [ ] **P4-T09** **Spike:** Fusion automation account policy, probe load ordering, add-in stop API, text commands, bundle vs AddIns folder. *Req:* P4-Q01, P4-Q02.
- [ ] **P4-T10** Fusion image with build pinning + weekly rebuild pipeline. *Req:* P4-R07, P4-R09.
- [ ] **P4-T11** Fusion sign-in automation with leased accounts. *Req:* P4-R07.
- [ ] **P4-T12** FUS-001 packaging/manifest validation. *Req:* P4-R05.
- [ ] **P4-T13** MtaFusionProbe: inventory, command execution, terminate, lifecycle checks; traceback classifier. *Req:* P4-R08, P4-R09.
- [ ] **P4-T14** Scheduled Fusion regression on build change (FUS-005). *Req:* P4-R09, P4-N03.
- [ ] **P4-T15** Fusion SD plugins (traceback, missing vendored lib, UI leftovers) + conformance. *Req:* P4-R18.
- [ ] **P4-T16** macOS feasibility spike report (optional). *Req:* P4-R10.

## Sprint 3 — Vault (weeks 6–7)
- [ ] **P4-T17** Vault server fixture VM + seed scripts + checkpoint reset automation. *Req:* P4-R11, P4-N02.
- [ ] **P4-T18** Vault client images + VaultProbe + VaultDriver. *Req:* P4-R13.
- [ ] **P4-T19** VLT-001/002 static (ApiVersion map in hosts.yaml). *Req:* P4-R12.
- [ ] **P4-T20** Explorer command execution via UIA menu diff (VLT-003) + login time (VLT-006). *Req:* P4-R13.
- [ ] **P4-T21** Event handler operations (VLT-005) + Job Processor flow (VLT-004). *Req:* P4-R14.
- [ ] **P4-T22** Vault SD extensions + conformance. *Req:* P4-R18.

## Sprint 4 — Alias, integration (week 8)
- [ ] **P4-T23** Alias adapter (stretch): static ALS-001, GUI load ALS-002. *Req:* P4-R15.
- [ ] **P4-T24** Parity verification across Phase 4 hosts (INS/UNI/NET/FS/RUN). *Req:* P4-R17.
- [ ] **P4-T25** Corpus collection + runs + tuning. *Req:* P4-R18.
- [ ] **P4-T26** Exit review; update Phase 5 specs.
