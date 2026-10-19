# Data Contracts

JSON Schemas live in `/src/mta/schemas/*.schema.json`. They are generated from these definitions and validated in CI.

## 1. Submission
```json
{
  "submission_id": "sub-2026-000123",
  "app_id": "acme.mytools",
  "app_version": "2.3.0",
  "previous_submission_id": "sub-2026-000077",
  "package": {"filename": "MyTools.msi", "sha256": "…", "size_bytes": 1048576, "kind": "msi|bundle|zip"},
  "products": [{"host_id": "autocad", "versions": [2024, 2025, 2026], "verticals": []}],
  "listing": {
    "title": "MyTools for AutoCAD",
    "publisher": "Acme Ltd",
    "app_type": "desktop|web|mcp",
    "description": "…",
    "support_email": "support@acme.example",
    "privacy_policy_url": "https://acme.example/privacy",
    "pricing": "free|trial|paid|subscription",
    "external_domains": ["api.acme.example"],
    "screenshots": ["…"]
  },
  "reviewer_inputs": {"scenarios": ["scenarios/acme.mytools/*.yaml"], "credentials_ref": null, "notes": ""},
  "received_at": "2026-10-19T09:58:00Z"
}
```
The Submission is built from the **Input Kit** (`submission.yaml` + `package/`, `docs/`, `media/`, `samples/`, `scenarios/`). See [submission-inputs.md](submission-inputs.md). The kit's `features`, `documents` and `test_hints` sections are stored on the Submission as `features`, `documents` and `test_hints`. `listing` is optional. When it is absent, LST-* checks are `SKIPPED`. `products` (the declared hosts and versions) sits at the top level because it is needed to plan Runs even without a listing. When the kit omits it, it is filled from the package manifest.

**Normative source:** the Pydantic models in `src/mta/models/`. The JSON Schemas in `src/mta/schemas/` are generated from them (`mta schema export`). A test fails if the committed schemas drift from the models.

## 2. Job & Run
```json
{"job_id":"job-…","submission_id":"…","state":"RECEIVED|STATIC_ANALYSIS|PLANNED|RUNNING|AGGREGATING|REPORTED|FAILED",
 "config_snapshot_sha256":"…","runs":["run-…"]}

{"run_id":"run-…","job_id":"…","host_id":"autocad","host_version":2026,"ui_mode":"headless|gui",
 "sandbox":{"kind":"local|hyperv","image":"acad2026-win11-v3"},"state":"…","started_at":"…","ended_at":"…"}
```

## 3. CheckResult
```json
{
  "check_id": "CMD-002",
  "target": {"run_id": "run-…", "host_id": "autocad", "host_version": 2026, "subject": "command:ACME_DIMALL"},
  "status": "PASS|FAIL|WARN|NEEDS_REVIEW|SKIPPED|ERROR",
  "severity": "BLOCKER|MAJOR|MINOR|INFO",
  "source": "static|dynamic|monitor|ai",
  "confidence": 1.0,
  "message": "Command ACME_DIMALL threw System.NullReferenceException on blank drawing",
  "evidence": [{"kind": "log", "ref": "sha256:…", "excerpt": "at Acme.Tools.DimAll.Run() …"}],
  "remediation": "Guard against empty model space before iterating entities.",
  "duration_ms": 412
}
```

## 4. Report (report.json)
```json
{
  "report_version": 1,
  "job_id": "…", "submission": { … },
  "recommendation": "RECOMMEND_APPROVE|RECOMMEND_REJECT|NEEDS_HUMAN",
  "recommendation_reasons": ["CMD-002 FAIL (BLOCKER) on AutoCAD 2026"],
  "matrix": [{"host_id":"autocad","host_version":2026,"ui_mode":"headless","summary":{"pass":31,"fail":1,"warn":2,"needs_review":0,"skipped":3,"error":0}}],
  "results": [ /* CheckResult[] */ ],
  "inventory": {"components": [...], "commands": [...], "ui": [...], "network": [...], "files_written": [...]},
  "artifacts": [{"sha256":"…","kind":"screenshot","path":"artifacts/…","run_id":"…"}],
  "mta": {"version":"0.1.0","config_sha256":"…","duration_ms": 512000}
}
```

## 5. Recommendation rule (default, configurable in `checks.yaml`)
```
if any(status == ERROR for blocking-path checks)              → NEEDS_HUMAN  (infra issue flagged)
elif any(status == FAIL and severity == BLOCKER)               → RECOMMEND_REJECT
elif any(status == FAIL and severity == MAJOR) or any(NEEDS_REVIEW) → NEEDS_HUMAN
else                                                          → RECOMMEND_APPROVE
```

## 6. Override (P2+)
```json
{"override_id":"…","check_result_ref":"…","by":"reviewer@autodesk.com","new_status":"PASS","reason":"Expected: command requires network licence","at":"…"}
```
Overrides are stored separately. The original results are never mutated. Override statistics feed false-positive tracking (G5).
