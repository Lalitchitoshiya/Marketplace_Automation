# Security & Isolation

Submissions are untrusted code (Constitution §4). This spec defines the minimum controls for each phase.

## 1. Threat model (STRIDE summary)
| Threat | Example | Control |
|---|---|---|
| Malicious payload | Plugin drops ransomware or a credential stealer | Malware scan before execution (SIG-003). Execution only in a sandbox. Monitoring (FS-*, NET-*). |
| Sandbox escape / lateral movement | Plugin scans the corporate network | Isolated VM network. Egress only via a recording proxy. No domain join. |
| Archive attacks | Zip-slip, zip bomb | PKG-001 limits, safe extraction library, no symlink following |
| Parser attacks | Malicious XML (XXE) in `PackageContents.xml` | `defusedxml`. DTD/external entities disabled. |
| Static-analysis execution | Loading an assembly runs module initialisers | Metadata-only reading (`System.Reflection.Metadata` / `MetadataLoadContext`). **Never `Assembly.Load`** outside the sandbox. |
| Evidence tampering | Plugin edits probe-events.ndjson | Probe writes with a sequence number + HMAC per event (P2). Orchestrator cross-checks against monitor traces. |
| Secrets leakage | Test credentials exfiltrated | Per-run ephemeral test accounts. Secrets injected at runtime only. Egress monitored. |
| Data confidentiality | Reports leak publisher IP | Autodesk-approved storage. RBAC on dashboard (P2). Retention policy. |
| Test evasion | Plugin detects MTA (probe name, VM artefacts, run-dir paths) and behaves well only during testing | Neutral probe naming, VM hardening, no MTA markers visible to the plugin (§5) |
| Verdict oracle | Publisher resubmits repeatedly to learn which changes pass | No automated result ever returned to the publisher; resubmission-frequency flag for reviewers (§5) |
| Rule leakage | Publisher learns checks / thresholds and games them | Catalog, configs, scenarios and images are confidential (Constitution §11) |

## 2. Controls by phase
| Control | P1 | P2 | P3–P5 |
|---|---|---|---|
| Malware scan before any execution | ✔ | ✔ | ✔ |
| Execution environment | Dedicated **non-domain** test workstation or local VM; isolated AutoCAD profile; no corporate credentials on the machine | Disposable Hyper-V VM reverted to a clean checkpoint after **every** run | Same as P2, plus VM image pipeline per host |
| Network | Allowed only for licensing + listing URL checks (from the orchestrator, not the sandbox) | Isolated vSwitch; egress via recording proxy; licence server allow-listed; optional "offline" run | Same |
| Monitoring | Probe only | Sysmon + ETW + proxy logs | Same |
| Artifact integrity | SHA-256 | SHA-256 + event HMAC | Same |
| Access control | Local | Dashboard SSO (Autodesk IdP), roles: reviewer, lead, admin | Same + audit log |

## 3. Phase 1 guardrail
Phase 1 executes plugins on a workstation, not a disposable VM. Therefore:
- Only run packages that **passed SIG-003** and come from the **golden corpus** or an Autodesk-approved queue.
- Use a dedicated test machine that is not the developer's daily machine. Snapshot or reimage it weekly.
- Never run Phase 1 on a domain-joined machine with access to Autodesk internal shares.

## 4. Confidentiality from publishers (Constitution §11)

### 4.1 No publisher access
| Control | Rule |
|---|---|
| Access | CLI, API and dashboard are reachable only from the Autodesk network with Autodesk SSO. There are no publisher roles in RBAC. |
| Distribution | MTA binaries, probes, VM images, `config/` and `/scenarios` are never shared outside Autodesk. They live in an Autodesk-private repository. |
| Outputs | Reports, recommendations, check IDs and evidence are never sent to publishers automatically, in any phase. |
| Publisher communication | Only through a human reviewer, after a final decision, using a sanitised export that contains **no** MTA recommendation, check IDs, severities, thresholds or tool names (Phase 5 P5-R16). |
| Publisher Corner | The integration (Phase 5) writes only to **internal** review records. No status visible to publishers changes because of MTA. |

### 4.2 Resubmission monitoring (Phase 2+)
- The dashboard shows a reviewer how many times the same app has been submitted in the last 30 days, and the diff between attempts.
- WHEN an app is resubmitted more than N times (default 3) in 7 days with small binary changes, THE SYSTEM SHALL flag it for the reviewer as possible trial-and-error probing.

## 5. Preventing test evasion
A plugin must not be able to tell that it is running under MTA:

| Area | Rule |
|---|---|
| Probe naming | Probe assemblies, scripts, commands and add-in IDs use **neutral names, configured per image** (no `Mta`, `Probe`, `Test` in names visible to the plugin). The names are stored in `config/probe_identity.yaml`, which is not checked into the publisher-visible docs. |
| Paths & environment | Run directories, profile names and environment variables use neutral names (e.g. `C:\Users\<realistic-name>\…`). The `MTA_RUN_DIR` value is passed through an indirection that does not appear in the plugin's environment, where possible. |
| VM artefacts | Images use realistic machine names, user names, installed apps and screen resolutions. Hyper-V guest services that are not needed are disabled. Known VM-detection checks (from the security corpus) are tested against each image. |
| Behaviour comparison | Phase 2 security corpus includes "evasive" synthetic plugins that act differently when they detect a VM or the probe. They must not be able to detect MTA. |
| Timing | Probe activity does not create obviously artificial patterns (e.g. commands fired at fixed 0 ms intervals). Configurable jitter is applied. |

## 6. Licensing note
Test VMs need Autodesk product licences for unattended use (network licence server or internal test entitlements). Autodesk must provide this. It is tracked as dependency **D-LIC** in each phase's requirements.
