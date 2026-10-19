# Phase 5 — Tasks

## Sprint 1 — 3ds Max & Maya (weeks 1–3)
- [ ] **P5-T01** Catalog + checks.yaml additions (MAX-*, MAYA-*, LST-004/005, WFL-003, AI-*).
- [ ] **P5-T02** **Spike:** 3ds Max batch switches, pluginManager / class enumeration APIs, menu system per version, SDK compatibility table. *Req:* P5-Q03.
- [ ] **P5-T03** 3ds Max images + samples; static MAX-001 + bundle part types. *Req:* P5-R01.
- [ ] **P5-T04** 3ds Max headless probe (load, classes, instantiate, macros, round-trip). *Req:* P5-R02, P5-R03.
- [ ] **P5-T05** 3ds Max GUI probe + UI exercise. *Req:* P5-R03.
- [ ] **P5-T06** Maya images + samples; `.mod` / plugin static checks MAYA-001. *Req:* P5-R04.
- [ ] **P5-T07** Maya headless probe (load, pluginInfo, smoke, nodes, unload, round-trip). *Req:* P5-R05, P5-R06.
- [ ] **P5-T08** Maya GUI probe (lsUI, shelves, Qt dialogs) + MAYA-005. *Req:* P5-R06.
- [ ] **P5-T09** SD plugins for both hosts + conformance + corpus (≥10 each). *Req:* exit criteria.

## Sprint 2 — AI Feature Tester (weeks 4–6)
- [ ] **P5-T10** D-LLM endpoint integration, `config/ai.yaml`, budget enforcement, prompt/response logging. *Req:* P5-R13, P5-N01.
- [ ] **P5-T11** ClaimExtractor with quote verification. *Req:* P5-R07.
- [ ] **P5-T12** ScenarioSynthesizer + validator / linter + retry. *Req:* P5-R08.
- [ ] **P5-T13** Agent runner (control-plane loop + in-VM executor + trajectory artifacts). *Req:* P5-R09.
- [ ] **P5-T14** Judge with evidence citation + CheckResult mapping (AI-001…003, WFL-003). *Req:* P5-R10.
- [ ] **P5-T15** LST-004/005 (description consistency, screenshot similarity). *Req:* P5-R11.
- [ ] **P5-T16** Promotion API + dashboard action. *Req:* P5-R12.
- [ ] **P5-T17** AI eval set (≥30 apps labelled with reviewers) + `mta ai eval` + prompt-injection red-team cases. *Req:* P5-R13, P5-R14.

## Sprint 3 — Production integration (weeks 7–8)
- [ ] **P5-T18** Publisher Corner intake-connector + write-back + DLQ. *Req:* P5-R15, P5-Q01.
- [ ] **P5-T19** Publisher-facing sanitised export. *Req:* P5-R16.
- [ ] **P5-T20** Compatibility sweep + aggregate report. *Req:* P5-R17.
- [ ] **P5-T21** Dashboard v2 features. *Req:* P5-R18.
- [ ] **P5-T22** Autoscaling pool + licence-seat-aware scheduler improvements. *Req:* P5-R19, P5-N03.

## Sprint 4 — Hardening & rollout (weeks 9–10, then shadow mode)
- [ ] **P5-T23** OpenTelemetry, dashboards, SLO alerts. *Req:* P5-R20.
- [ ] **P5-T24** Security review, pen-test fixes, RBAC review, retention jobs, backup/restore + DR drill. *Req:* P5-R21.
- [ ] **P5-T25** Runbooks + guides (add-a-host v2, add-a-check, scenario authoring) + training. *Req:* P5-R23.
- [ ] **P5-T26** Shadow mode (≥4 weeks): agreement tracking, weekly tuning. *Req:* P5-R22.
- [ ] **P5-T27** Stage-gate reviews → assisted mode → default mode. *Req:* P5-R22.
- [ ] **P5-T28** Final POC report: G1–G6 results, cost model, post-POC backlog (web apps, MCP servers, publisher self-check).
