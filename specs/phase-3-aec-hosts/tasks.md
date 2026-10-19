# Phase 3 — Tasks

## Sprint 1 — SDK v1 (weeks 1–2)
- [ ] **P3-T01** Add BIN-011, REV-*, NAV-*, RSA-* rows to check-catalog.md and checks.yaml (spec PR first). *Req:* P3-R04…R13.
- [ ] **P3-T02** Extract `Mta.Probe.Core` (C#) and refactor AcProbe onto it. *Req:* P3-R01.
- [ ] **P3-T03** Extract Python SDK base modules (`dotnet_static`, `gui_session`, `installer_flow`, `monitor`). *Req:* P3-R01.
- [ ] **P3-T04** Entry-point adapter registry; remove AutoCAD-specific imports from the orchestrator, engine and report. *Req:* P3-R02.
- [ ] **P3-T05** Generalise the conformance suite and run it on AutoCAD; AutoCAD corpus regression gate (P3-N03). *Req:* P3-R03.
- [ ] **P3-T06** BIN-011 shared-dependency check with host-shipped assembly inventories per version (`data/<host>/<year>/assemblies.json`, generated from images). *Req:* P3-R04.
- [ ] **P3-T07** `docs/add-a-host.md`. *Req:* P3-N02.

## Sprint 2 — Revit (weeks 3–5)
- [ ] **P3-T08** **Spike:** Revit driver loop (Idling state machine), `PostCommand` custom-control IDs, `DialogBoxShowing`, journal location per year. *Req:* P3-Q01, P3-Q02.
- [ ] **P3-T09** Revit images `rvt2024…2027` + sample model set per year. *Req:* P3-R07.
- [ ] **P3-T10** `.addin` parser + MAN-001/008 + REV-001/002(static)/007 via mta-inspect extensions. *Req:* P3-R05, P3-R06.
- [ ] **P3-T11** RvtProbe: startup, LoadedApplications, ribbon inventory, dialog capture. *Req:* P3-R07, P3-R08.
- [ ] **P3-T12** RvtProbe driver: open samples, invoke commands per model, hygiene checks REV-002…004, 006. *Req:* P3-R08, P3-R09.
- [ ] **P3-T13** Journal collector + parser. *Req:* P3-R10.
- [ ] **P3-T14** Revit DSL assertions + worksharing template REV-005. *Req:* P3-R09, P3-R11.
- [ ] **P3-T15** Revit SD-01…11 synthetic add-ins + conformance green on all versions. *Req:* P3-R03.

## Sprint 3 — Navisworks & Robot (weeks 6–7)
- [ ] **P3-T16** Navisworks adapter (validates P3-R02: no orchestrator changes): static NAV-001, automation driver NAV-002/CMD-002, GUI session, NAV-003. *Req:* P3-R12.
- [ ] **P3-T17** **Spike + implementation:** Robot COM registration and command enumeration; RsaDriver; RSA-001/002. *Req:* P3-R13, P3-Q04.
- [ ] **P3-T18** Images `nav<year>`, `rsa<year>`; samples. *Req:* P3-R12, P3-R13.
- [ ] **P3-T19** Navisworks and Robot SD plugins + conformance. *Req:* P3-R03.

## Sprint 4 — Integration (week 8)
- [ ] **P3-T20** Report host tabs + inventories + model × version command table. *Req:* P3-R15.
- [ ] **P3-T21** Parity verification: INS/UNI/NET/FS/RUN on the three hosts. *Req:* P3-R14.
- [ ] **P3-T22** Corpus collection (≥30 Revit, ≥5 Navisworks, ≥3 Robot) + runs + tuning. *Req:* P3-R16.
- [ ] **P3-T23** Exit review; update Phase 4 specs.
