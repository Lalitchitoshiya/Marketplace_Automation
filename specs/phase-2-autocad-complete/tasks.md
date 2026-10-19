# Phase 2 — Tasks

## Sprint 1 — Infrastructure (weeks 1–2)
- [ ] **P2-T01** Provision the Hyper-V host, isolated vSwitch, egress gateway VM (dnsmasq + Squid), licence server reachability. *Req:* P2-R04, D-INFRA, D-LIC.
- [ ] **P2-T02** Packer image pipeline for `acad2026-win11` + image smoke test with SD-01. *Req:* P2-R02.
- [ ] **P2-T03** **Spike:** GUI probe load ordering (P2-Q01), `LOGFILEMODE` capture, `SendStringToExecute` + prompt cancel reliability. *DoD:* ADR addendum.
- [ ] **P2-T04** mta-hostd: VM pool, checkpoint revert, PowerShell Direct exec, file copy in/out, quarantine. *Req:* P2-R01, P2-R03, P2-R05.
- [ ] **P2-T05** mta-agent: Run plan execution inside the guest, artifact packaging. *Req:* P2-R01.

## Sprint 2 — Install, GUI, UI (weeks 3–4)
- [ ] **P2-T06** Installer step (msiexec + log parse) → INS-001…004; bundle/ZIP fallback deploy. *Req:* P2-R06.
- [ ] **P2-T07** FS/registry snapshot + diff tool; uninstall flow → UNI-001…003. *Req:* P2-R07.
- [ ] **P2-T08** GUI launcher (`acad.exe`, isolated profile, product switch, LOGFILEMODE) + baseline launch caching. *Req:* P2-R08, P2-R09.
- [ ] **P2-T09** MtaProbe.AutoCAD.Gui: autoload verification (LOD-004), ribbon/menu/palette inventory with baseline diff. *Req:* P2-R10.
- [ ] **P2-T10** FlaUI dialog watcher + classifier + auto-close + screenshots. *Req:* P2-R09, P2-R11.
- [ ] **P2-T11** UI exercise (probe-invoke all + FlaUI click ≥1 per panel) → UI-001…004, UI-006. *Req:* P2-R11.
- [ ] **P2-T12** Video recording + event-bookmark index. *Req:* P2-R12.
- [ ] **P2-T13** Scenario DSL GUI verbs (`click`, `dialog`, `wait`, `screenshot`) + assertions. *Req:* P2-R13.

## Sprint 3 — Monitoring & rules (weeks 5–6)
- [ ] **P2-T14** Sysmon config + EVTX export/parse + process-tree attribution. *Req:* P2-R15.
- [ ] **P2-T15** Baseline subtraction + path normalisation. *Req:* P2-R16.
- [ ] **P2-T16** Allow-lists + rules NET-001…003, FS-001…005. *Req:* P2-R17.
- [ ] **P2-T17** Offline run mode + NET-004. *Req:* P2-R04.
- [ ] **P2-T18** Resource sampler + RUN-004/005; AUDIT + CMD-005. *Req:* P2-R18, P2-R21.
- [ ] **P2-T19** ENT-001/002. *Req:* P2-R22.
- [ ] **P2-T20** SIG-004 signer consistency; UI-005 high-DPI pass (optional). *Req:* P2-R14.

## Sprint 4 — Matrix, verticals, service (weeks 7–8)
- [ ] **P2-T21** Images for AutoCAD 2024, 2025, 2027 + Civil 3D, Plant 3D, toolset, Advance Steel. *Req:* P2-R19, P2-R20.
- [ ] **P2-T22** Vertical detection + LST-003 extension + vertical samples. *Req:* P2-R20.
- [ ] **P2-T23** FastAPI service, PostgreSQL schema, queue, scheduler (capacity, seats, priority), OIDC. *Req:* P2-R05, P2-R23.
- [ ] **P2-T24** Dashboard v1: queue, report + evidence viewer + video bookmarks, overrides, re-run, roles. *Req:* P2-R24.
- [ ] **P2-T25** Regression diff + app history page. *Req:* P2-R25.
- [ ] **P2-T26** Override analytics + metrics page. *Req:* P2-R26.
- [ ] **P2-T27** SD-12…15 synthetic plugins + security corpus (EICAR, persistence, network scanner, VM-detection). *Req:* P2-R27, P2-N03.
- [ ] **P2-T28** Corpus expansion to ≥40 apps with Autodesk verdicts; full matrix runs; tuning. *Req:* P2-R27.
- [ ] **P2-T29** Phase exit review: accuracy, security tests, performance; update Phase 3 specs. *Req:* exit criteria.

## Traceability
| Req | Tasks | Req | Tasks |
|---|---|---|---|
| R01 | T04, T05 | R15 | T14 |
| R02 | T02, T21 | R16 | T15 |
| R03 | T04 | R17 | T16 |
| R04 | T01, T17 | R18 | T18 |
| R05 | T04, T23 | R19 | T21 |
| R06 | T06 | R20 | T21, T22 |
| R07 | T07 | R21 | T18 |
| R08 | T08, T09 | R22 | T19 |
| R09 | T08, T10 | R23 | T23 |
| R10 | T09 | R24 | T24 |
| R11 | T10, T11 | R25 | T25 |
| R12 | T12 | R26 | T26 |
| R13 | T13 | R27 | T27, T28 |
| R14 | T20 | | |
