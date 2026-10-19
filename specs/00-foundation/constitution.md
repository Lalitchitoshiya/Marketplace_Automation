# Constitution

These principles override convenience. Any deviation needs an ADR.

## 1. Assist the reviewer; never auto-publish
MTA produces **evidence and a recommendation**: `RECOMMEND_APPROVE`, `RECOMMEND_REJECT` or `NEEDS_HUMAN`. A human Autodesk reviewer makes the final publishing decision. No phase may add an automatic publish path.

## 2. Every verdict carries evidence
Every `CheckResult` must link to the artifact that justifies it: a log excerpt, screenshot, video, event trace, or file/line in the package. A verdict without evidence is a defect.

## 3. Separate infrastructure failures from app failures
If MTA itself fails (VM did not boot, licence unavailable, timeout in our harness), the result is `ERROR`, not `FAIL`. A publisher must never be blamed for our infrastructure.

## 4. Treat all submissions as hostile
Third-party binaries are untrusted:
- They run only inside an isolated environment. From Phase 2 this means disposable VMs.
- Static analysis must never execute submission code.
- See [security-and-isolation.md](security-and-isolation.md).

## 5. Configure host facts; do not hard-code them
Product versions, .NET runtimes, install paths, API assembly names and executables live in `config/hosts.yaml` ([host-matrix.md](host-matrix.md)). Supporting a new product year must be a config change plus corpus run, not a code change.

## 6. One contract, many hosts
Every Autodesk product is integrated through the same [Host Adapter Contract](host-adapter-contract.md) and [Probe Protocol](probe-protocol.md). The orchestrator, check engine and reporting stay host-agnostic.

## 7. Deterministic first, AI second
Rule-based checks run first and are reproducible. AI-based checks (Phase 5) are labelled `source: ai`, carry a confidence score, and can only produce `PASS`, `WARN` or `NEEDS_REVIEW`. They never produce a blocking `FAIL` on their own.

## 8. Measure ourselves against the manual reviewer
Each phase exits only when its corpus run meets the agreed agreement rate with manual review verdicts. See [testing-strategy.md](testing-strategy.md).

## 9. Reproducibility
Any job can be re-run from its stored `Submission` plus `config` snapshot and produce the same deterministic results. Artifacts are content-addressed (SHA-256).

## 10. Privacy
Submission binaries, publisher data and reports are Autodesk-confidential. They are stored only in Autodesk-approved storage, never sent to third-party services, and kept for a configurable retention period. AI calls (Phase 5) use an Autodesk-approved LLM endpoint only.

## 11. Internal only: publishers never see the test or its verdict
MTA is an **Autodesk-internal** tool. Publishers must not be able to run MTA, see its results, or find out in advance whether a submission will pass or fail.
- No publisher-facing access in any phase: no portal, no API, no CLI distribution, no automatic notifications.
- The check catalog, thresholds, allow-lists, scenarios, probe binaries and VM images are Autodesk-confidential.
- Information reaches a publisher only through a human reviewer, after a final decision, and in the reviewer's own words (see Phase 5 P5-R16).
- The test environment must not reveal itself to the plugin under test (see [security-and-isolation.md](security-and-isolation.md) §5).

## 12. Engineering standards
- **Orchestrator:** Python 3.12, type-checked (`mypy --strict`), `ruff`, `pytest` with ≥80% line coverage on core.
- **Probes:** C# with nullable enabled and warnings as errors. Python probes for Python-hosted products.
- Every PR references a task ID. Every task references requirement IDs.
- Logs are structured JSON.
