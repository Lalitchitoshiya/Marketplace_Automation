# MTA .NET projects

| Project | Purpose | Needs AutoCAD to build |
|---|---|---|
| `src/MtaInspect` | `mta-inspect`: metadata-only assembly inspection (step 9) | No |
| `tests/MtaInspect.Tests` | xUnit tests for mta-inspect | No |
| `synthetic/Sd01Clean` | SD-01 clean synthetic plugin; base of the canary plugin | Yes |

Projects with `<UsesAutoCAD>true</UsesAutoCAD>` reference the installed AutoCAD (`AcCoreMgd`, `AcDbMgd`).
Set the version or folder with `-p:AcadVersion=2025` or `-p:AcadDir=...` (or the `MTA_ACAD_DIR` environment variable).

```
dotnet build dotnet/Mta.slnx -c Release          # everything (machine with AutoCAD)
dotnet test  dotnet/tests/MtaInspect.Tests        # no AutoCAD needed
```
