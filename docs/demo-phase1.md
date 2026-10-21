# Phase 1 demo script (E1.4)

For the demo to the Autodesk Marketplace team, about 20 minutes. Run it on a machine where `mta doctor --deep` says HEALTHY.

## 0. Before the demo (5 min, not shown)
```
uv run mta probe build
uv run mta corpus build
uv run mta doctor --deep          # must end with HEALTHY
```

## 1. Environment health (1 min)
`uv run mta doctor`: AutoCAD versions found, tools present, run folder OK.
Point out that a host update which changes behaviour is caught before results are trusted (`--deep`).

## 2. A clean plugin, end to end (5 min)
```
uv run mta kit init demo-kit --package <SD-01 bundle>    # pre-fills version, products, commands
uv run mta scenario from-features --kit demo-kit         # draft scenarios from the kit's feature hints
uv run mta run --kit demo-kit --offline
```
Open `report.html`:
- the banner and its reasons;
- the version matrix;
- the findings with evidence and filters;
- the command table (completed / awaiting input);
- the scenario results;
- the listing screenshots.

Exit code 10 means NEEDS_HUMAN (unsigned).

## 3. Defects found automatically (7 min)
`uv run mta corpus run`: each synthetic defect triggers exactly its check:

| Case | Defect | Check |
|---|---|---|
| SD-02 | Initialize throws | LOD-001 |
| SD-03 | Null reference in a command | CMD-002 + RUN-002 |
| SD-04 | Hang | CMD-004 |
| SD-05 | Native crash | RUN-001 |
| SD-06 | Wrong .NET | BIN-001 |
| SD-07 | Missing DLL | BIN-004 + LOD-001 |
| SD-08 | Ships AutoCAD DLLs | BIN-005 |
| SD-09 | Bad manifest | MAN-004 |
| SD-10 | Unsigned | SIG-001 |
| SD-16 | `LINE` collision | CMD-003 |

Show one crash (SD-05): the crash is recorded with evidence, no crash dialog appears, and the run continues with the next command.

## 4. Safety and confidentiality (2 min)
- **Nothing runs before the malware scan.** MSIs whose admin install would run code are not extracted.
- **The probe cannot be detected.** Its names are neutral and generated from the confidential config, and the binary is scanned clean.
- **Reports are internal**, and publishers have no access.

## 5. What Autodesk needs to provide (3 min)
See `specs/phase-1-autocad-headless/exit-report.md`, section "Open":
- the real corpus with verdicts (D-CORPUS);
- the dedicated test machine and AutoCAD 2025;
- unattended licensing (D-LIC);
- the review checklist (D-CHECKLIST);
- a trusted test signing certificate.
