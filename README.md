# MTA: Marketplace Test Automation

**Autodesk-internal.** Automated review testing for Autodesk Marketplace desktop submissions. Publishers have no access to this tool or its results ([Constitution §11](specs/00-foundation/constitution.md)).

- Start here: [specs/OVERVIEW.md](specs/OVERVIEW.md)
- Phase 1 plan and progress: [specs/phase-1-autocad-headless/steps.md](specs/phase-1-autocad-headless/steps.md)
- Workstation setup: [docs/workstation.md](docs/workstation.md)

## Layout
| Path | Contents |
|---|---|
| `specs/` | Specifications: the source of truth (spec-driven development) |
| `src/mta/` | Python package: CLI, orchestrator, checks, reports |
| `tests/` | Python tests |
| `dotnet/` | C# projects: `mta-inspect`, probes, synthetic test plugins ([dotnet/README.md](dotnet/README.md)) |
| `data/` | Generated reference data (e.g. built-in AutoCAD command lists) |
| `docs/` | Operational documentation |
| `spikes/` | Throw-away experiments; findings live in `specs/adr/` |

## Development
Requires Python 3.12 via [uv](https://docs.astral.sh/uv/), .NET SDK 8+ (10 tested), and AutoCAD for the AutoCAD-dependent projects.

```
uv sync                         # create the environment
uv run mta --version            # CLI
uv run ruff check . ; uv run ruff format --check .
uv run mypy
uv run pytest

dotnet build dotnet/Mta.slnx -c Release
dotnet test  dotnet/tests/MtaInspect.Tests -c Release
```
