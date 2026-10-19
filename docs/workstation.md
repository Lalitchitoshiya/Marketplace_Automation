# Phase 1 Workstation

Reference machine for Phase 1 development (step 1 of [steps.md](../specs/phase-1-autocad-headless/steps.md)).
Last checked: 2026-10-19.

## Machine
| Item | Value |
|---|---|
| OS | Windows 11 Pro x64 (10.0.26300) |
| Domain-joined | **No** (`PartOfDomain = False`) |
| Role | Developer machine. OK for MTA's own synthetic and spike plugins **only**. Real third-party submissions need the dedicated test machine ([security-and-isolation.md](../specs/00-foundation/security-and-isolation.md) §3). |

## Prerequisites
| # | Prerequisite | Status | Version / path | Owner of open item |
|---|---|---|---|---|
| 1 | AutoCAD 2026 | ✅ | `C:\Program Files\Autodesk\AutoCAD 2026` (W.164.0.0, R25.1) | — |
| 2 | `accoreconsole.exe` | ✅ | same folder | — |
| 3 | AutoCAD API DLLs | ✅ | `AcCoreMgd`, `AcDbMgd`, `AcMgd`, `AdWindows` in install folder | — |
| 4 | AutoCAD 2025 | ❌ | not installed | Lalit → request from Autodesk / IT |
| 5 | AutoCAD 2024 (net48) | ❌ | not installed (optional) | Lalit, only if corpus needs net48 |
| 6 | Plain AutoCAD profile | ⚠ | Default profile is Civil 3D; AECC modules load even with `/product ACAD` (ADR-0003 F17) | Accepted on dev machine; dedicated machine must have plain AutoCAD |
| 7 | .NET SDK | ✅ | 10.0.400 (builds `net8.0-windows`) | — |
| 8 | Python 3.12 | ✅ | 3.12.13 via `uv` (`uv python find 3.12`) | — |
| 9 | uv | ✅ | 0.11.8 | — |
| 10 | Git | ✅ | 2.53.0 | — |
| 11 | Defender CLI | ✅ | `C:\Program Files\Windows Defender\MpCmdRun.exe` | — |
| 12 | WER LocalDumps for `accoreconsole.exe` | ❌ | Not configured (needs admin) | Lalit: run the command below once in an **admin** terminal |
| 13 | Unattended licence | ⚠ | Works under the signed-in user; no-login behaviour untested (ADR-0003 F21) | Autodesk (D-LIC) |
| 14 | Dedicated non-domain test machine | ❌ | — | Lalit → request from Autodesk / IT |
| 15 | Review checklist (D-CHECKLIST) | ⏳ | — | Autodesk |
| 16 | Corpus with verdicts (D-CORPUS) | ⏳ | — | Autodesk |

### Enable crash dumps (item 12), admin terminal
```powershell
$k = 'HKLM:\SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps\accoreconsole.exe'
New-Item -Path $k -Force | Out-Null
New-ItemProperty -Path $k -Name DumpFolder -PropertyType ExpandString -Value 'D:\Marketplace_Automation\.mta\dumps' -Force | Out-Null
New-ItemProperty -Path $k -Name DumpType  -PropertyType DWord -Value 1 -Force | Out-Null   # 1 = mini dump
New-ItemProperty -Path $k -Name DumpCount -PropertyType DWord -Value 20 -Force | Out-Null
```
`mta doctor --fix` will do this automatically once implemented (P1-T24).

## Observed timings (core console, AutoCAD 2026)
| Run | Start → load → commands → quit |
|---|---|
| First spike run | 5–11 s |
| Re-run (same experiments, machine busier) | 14–17 s |

Timing varies with machine load, so health-check and watchdog thresholds must allow ≥30 s for startup + quit.

## Spike reproducibility check (2026-10-19)
Re-ran `a_basic`, `b_throw` and `l_lisp_cancel`. Exit codes and event sequences were **identical** to the first run.
