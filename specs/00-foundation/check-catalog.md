# Check Catalog

This is the single registry of automated checks. Runtime enablement and severity overrides live in `config/checks.yaml`. A check can be added only through a spec PR that adds a row here.

**Columns:**
- **Phase** is the phase that introduces the check.
- **Hosts:** `*` means all hosts; `acad` means the AutoCAD family; otherwise the specific adapter IDs.
- **Default severity** applies when the status is `FAIL`.
- **Source:** S = static, D = dynamic (probe), M = monitor, A = AI.

## PKG — Package
| ID | Check | Sev | Src | Hosts | Phase |
|---|---|---|---|---|---|
| PKG-001 | Package extracts safely (no path traversal, no symlinks escaping root, size ≤ limit, file count ≤ limit) | BLOCKER | S | * | 1 |
| PKG-002 | Package kind identified (MSI / bundle / ZIP) and contains a deployable payload | BLOCKER | S | * | 1 |
| PKG-003 | MSI administrative extraction succeeds (`msiexec /a`) | MAJOR | S | * | 1 |
| PKG-004 | Bundle layout valid: one `*.bundle` root with `PackageContents.xml` | BLOCKER | S | acad, inventor, 3dsmax, revit* | 1 |
| PKG-005 | No unexpected executable types (`.bat`, `.ps1`, `.vbs`, `.scr`, `.js`) outside the declared components | WARN→MAJOR | S | * | 1 |
| PKG-006 | Package version matches listing `app_version` | MINOR | S | * | 1 |

## MAN — Manifest
| ID | Check | Sev | Src | Hosts | Phase |
|---|---|---|---|---|---|
| MAN-001 | Manifest well-formed and valid against the MTA schema (`PackageContents.xml`, `.addin`, `.manifest`, `.mod`) | BLOCKER | S | * | 1 (acad), 3–5 others |
| MAN-002 | Required metadata present: ProductCode GUID, AppVersion, Name, Author/Company, AutodeskProduct | MAJOR | S | * | 1 |
| MAN-003 | Declared version range (`SeriesMin`/`SeriesMax` or equivalent) covers the listing's declared versions | MAJOR | S | * | 1 |
| MAN-004 | Every component module path in the manifest exists in the package | BLOCKER | S | * | 1 |
| MAN-005 | Commands declared in the manifest exist in the binaries, and vice versa (drift) | MINOR | S | acad | 1 |
| MAN-006 | OS / Platform / ProductType values valid | MAJOR | S | * | 1 |
| MAN-007 | Each component's runtime requirements map to a configured host version (no orphan component) | MINOR | S | * | 1 |
| MAN-008 | Revit `.addin`: AddInId GUID unique, VendorId present, FullClassName exists in the assembly | BLOCKER | S | revit | 3 |

## BIN — Binary inspection (no execution)
| ID | Check | Sev | Src | Hosts | Phase |
|---|---|---|---|---|---|
| BIN-001 | Target framework compatible with each declared host version (e.g. net48 vs net8.0-windows) | BLOCKER | S | .NET hosts | 1 |
| BIN-002 | Host API references compatible with the declared versions (e.g. AcDbMgd major version) | BLOCKER | S | .NET hosts | 1 |
| BIN-003 | Native binaries are x64 | BLOCKER | S | * | 1 |
| BIN-004 | All referenced assemblies resolvable (shipped, host-provided, or framework) | BLOCKER | S | .NET hosts | 1 |
| BIN-005 | Host API assemblies not shipped in package (e.g. `AcMgd.dll`, `RevitAPI.dll` copied locally) | MAJOR | S | .NET hosts | 1 |
| BIN-006 | Inventory of hard-coded URLs, IPs and domains (INFO; feeds NET-003) | INFO | S | * | 1 |
| BIN-007 | Risky API usage inventory (process spawn, HKLM writes, PowerShell, raw sockets, reflection-emit, AMSI-evasion patterns) | WARN | S | * | 1 |
| BIN-008 | Core-console compatibility: depends on ribbon / palette / WPF / WinForms (`AdWindows`, `AcWindows`, `PaletteSet`) → GUI required. `AcMgd` alone is core-console compatible (ADR-0003 F14). | INFO | S | acad | 1 |
| BIN-009 | Obfuscation detected (INFO; lowers the confidence of static checks) | INFO | S | .NET hosts | 1 |
| BIN-010 | Python package: syntax valid for the host's Python, no `pip install` at runtime, vendored deps present | MAJOR | S | fusion, 3dsmax, maya | 4 |

## SIG — Signing & malware
| ID | Check | Sev | Src | Hosts | Phase |
|---|---|---|---|---|---|
| SIG-001 | Authenticode signature present on every DLL / EXE / MSI / ARX | MAJOR | S | * | 1 |
| SIG-002 | Signature valid, chain trusted, timestamped, not revoked | MAJOR | S | * | 1 |
| SIG-003 | Malware scan clean (Microsoft Defender `MpCmdRun`, plus optional second engine) | BLOCKER | S | * | 1 |
| SIG-004 | Signer consistent with previous approved version of the same app | WARN | S | * | 2 |

## LST — Listing
| ID | Check | Sev | Src | Hosts | Phase |
|---|---|---|---|---|---|
| LST-001 | Privacy policy URL reachable over HTTPS (2xx) | MAJOR | S | * | 1 |
| LST-002 | Support email valid syntax and domain has MX record | MINOR | S | * | 1 |
| LST-003 | Listing products/versions consistent with manifest and binaries | MAJOR | S | * | 1 |
| LST-004 | Description quality / consistency review | WARN | A | * | 5 |
| LST-005 | Listing screenshots resemble observed UI | WARN | A | * | 5 |

## INS — Install
| ID | Check | Sev | Src | Hosts | Phase |
|---|---|---|---|---|---|
| INS-001 | Silent install succeeds (`msiexec /i /qn`, exit 0 or 3010) | BLOCKER | D | * | 2 |
| INS-002 | Payload lands in a recognised plugin location for the host | MAJOR | D | * | 2 |
| INS-003 | Installer does not require interactive input or reboot (3010 → WARN) | MINOR | D | * | 2 |
| INS-004 | Per-version deployment: installer targets every declared version | MAJOR | D | * | 2 |

## LOD — Load
| ID | Check | Sev | Src | Hosts | Phase |
|---|---|---|---|---|---|
| LOD-001 | Every component loads without exception | BLOCKER | D | * | 1 |
| LOD-002 | Component load time ≤ threshold (default 5 s each) | MINOR | D | * | 1 |
| LOD-003 | Host startup completes with plugin installed (no hang) | BLOCKER | D | * | 1 |
| LOD-004 | Host's native loader (autoloader / `.addin` / module) picks the plugin up without manual load | BLOCKER | D | * | 2 |
| LOD-005 | Host startup time delta vs baseline ≤ threshold (default +20%) | MINOR | D | * | 2 |
| LOD-006 | No error dialogs from the host's add-in manager at startup | BLOCKER | D | * | 2 |

## CMD — Commands
| ID | Check | Sev | Src | Hosts | Phase |
|---|---|---|---|---|---|
| CMD-001 | Commands declared (manifest / binaries) are registered at runtime | MAJOR | D | * | 1 |
| CMD-002 | Smoke invoke: each command completes, cancels cleanly or awaits input without unhandled exception | BLOCKER | D | * | 1 |
| CMD-003 | No collision with built-in host command names or other common apps | MAJOR | S | acad | 1 |
| CMD-004 | Command does not hang beyond the timeout after cancel | MAJOR | D | * | 1 |
| CMD-005 | Document integrity after command: AUDIT reports no errors introduced | MINOR | D | acad | 2 |

## UI — User interface (GUI mode)
| ID | Check | Sev | Src | Hosts | Phase |
|---|---|---|---|---|---|
| UI-001 | Plugin UI present (ribbon tab/panel, menu, toolbar, palette) as described | MAJOR | D | * | 2 |
| UI-002 | Each plugin ribbon button / menu item triggers a command without error | MAJOR | D | * | 2 |
| UI-003 | Dialogs open, render (non-blank screenshot) and close via Cancel/Esc | MAJOR | D | * | 2 |
| UI-004 | No modal nag / popup at host startup (except licence activation for trial/paid) | WARN | D | * | 2 |
| UI-005 | High-DPI rendering sanity (150%: no clipped controls, by screenshot heuristics) | MINOR | D | * | 2 |
| UI-006 | Icons provided for ribbon buttons (no blank icons) | MINOR | D | * | 2 |

## WFL — Workflow scenarios
| ID | Check | Sev | Src | Hosts | Phase |
|---|---|---|---|---|---|
| WFL-001 | Reviewer/publisher scenario steps execute | MAJOR | D | * | 1 |
| WFL-002 | Scenario assertions hold | MAJOR | D | * | 1 |
| WFL-003 | AI-generated scenario from listing claim passes | WARN | A | * | 5 |

## RUN — Runtime health
| ID | Check | Sev | Src | Hosts | Phase |
|---|---|---|---|---|---|
| RUN-001 | Host process did not crash (exit code, WER report, dump) | BLOCKER | D/M | * | 1 |
| RUN-002 | No unhandled exceptions attributed to the plugin | BLOCKER | D | * | 1 |
| RUN-003 | Host exits cleanly on quit with the plugin loaded (no hang on shutdown) | MAJOR | D | * | 1 |
| RUN-004 | Memory / handle / GDI growth during smoke within threshold | MINOR | M | * | 2 |
| RUN-005 | First-chance exception storm (> N/min from plugin assemblies) | WARN | D | * | 2 |

## NET — Network (monitored)
| ID | Check | Sev | Src | Hosts | Phase |
|---|---|---|---|---|---|
| NET-001 | Outbound connection inventory (INFO) | INFO | M | * | 2 |
| NET-002 | All outbound HTTP traffic uses TLS | MAJOR | M | * | 2 |
| NET-003 | No connections to domains not declared in listing `external_domains` | MAJOR | M | * | 2 |
| NET-004 | Plugin works (or degrades gracefully) when offline | MINOR | D | * | 2 |

## FS — File system / registry / persistence (monitored)
| ID | Check | Sev | Src | Hosts | Phase |
|---|---|---|---|---|---|
| FS-001 | No writes outside allowed locations (allow-list per host) | MAJOR | M | * | 2 |
| FS-002 | No registry writes outside allowed keys | MAJOR | M | * | 2 |
| FS-003 | No persistence mechanisms (Run keys, services, scheduled tasks, startup folder) | BLOCKER | M | * | 2 |
| FS-004 | No modification of host install folder or other vendors' plugins | BLOCKER | M | * | 2 |
| FS-005 | No child processes except an allow-list (INFO list + WARN) | WARN | M | * | 2 |

## UNI — Uninstall
| ID | Check | Sev | Src | Hosts | Phase |
|---|---|---|---|---|---|
| UNI-001 | Silent uninstall succeeds | MAJOR | D | * | 2 |
| UNI-002 | No leftover payload files / registry (user data allow-listed) | MINOR | D | * | 2 |
| UNI-003 | Host launches cleanly after uninstall (no missing-module errors) | BLOCKER | D | * | 2 |

## ENT — Entitlement / licensing
| ID | Check | Sev | Src | Hosts | Phase |
|---|---|---|---|---|---|
| ENT-001 | Paid / trial app references the Autodesk Entitlement API, or declares an alternative | INFO | S | * | 2 |
| ENT-002 | Trial / paid app shows a licence state rather than crashing when unentitled | MAJOR | D | * | 2 |

## AI — Intelligent feature testing
| ID | Check | Sev | Src | Hosts | Phase |
|---|---|---|---|---|---|
| AI-001 | Feature claims extracted from listing (INFO, list) | INFO | A | * | 5 |
| AI-002 | Each claim exercised by an agent run, with evidence | WARN | A | * | 5 |
| AI-003 | Observed behaviour contradicts listing claim | NEEDS_REVIEW | A | * | 5 |

## Rules
- AI checks (`Src = A`) may only emit `PASS`, `WARN`, `NEEDS_REVIEW` or `INFO` (Constitution §7).
- A check that cannot run because of missing prerequisites emits `SKIPPED` with a reason. Example: no listing provided → LST-* `SKIPPED`.
- A new check starts as **non-blocking** (severity capped at `MAJOR`) for one phase. It can only become `BLOCKER` after the corpus shows ≤5% false positives.
