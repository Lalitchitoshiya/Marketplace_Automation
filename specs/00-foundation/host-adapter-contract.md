# Host Adapter Contract

Every Autodesk product is integrated through this contract. The orchestrator and check engine only talk to adapters through it. The contract is introduced in Phase 1 (AutoCAD is the only implementation) and frozen as **Adapter SDK v1** in Phase 3.

## 1. Python interface (normative)

```python
class HostAdapter(Protocol):
    id: str                      # "autocad", "revit", "inventor", ...
    display_name: str

    # ---- discovery -------------------------------------------------------
    def detect(self, pkg: PackageInfo) -> DetectionResult:
        """Does this package target this host? Returns the versions targeted plus confidence.
        Must not execute package code."""

    def supported_versions(self) -> list[HostVersion]:
        """From config/hosts.yaml; filtered to versions installed in the sandbox image."""

    # ---- static ----------------------------------------------------------
    def static_checks(self, pkg: PackageInfo, versions: list[HostVersion]) -> list[CheckResult]:
        """Host-specific static checks (e.g. PackageContents.xml for AutoCAD, .addin for Revit)."""

    # ---- dynamic ---------------------------------------------------------
    def prepare(self, env: SandboxEnv, version: HostVersion) -> None:
        """Isolated profile, licence, clean settings, deploy probe."""

    def deploy(self, env: SandboxEnv, pkg: PackageInfo, mode: DeployMode) -> DeployResult:
        """DeployMode.BUNDLE_COPY (P1) | DeployMode.INSTALLER (P2+)."""

    def launch(self, env: SandboxEnv, version: HostVersion, ui: UiMode) -> HostSession:
        """UiMode.HEADLESS | UiMode.GUI. Returns a session wrapping the host process + probe channel."""

    def load_report(self, s: HostSession) -> LoadReport
    def list_commands(self, s: HostSession) -> list[CommandInfo]
    def ui_inventory(self, s: HostSession) -> UiInventory          # P2+ (GUI only)
    def invoke(self, s: HostSession, cmd: CommandInfo, opts: InvokeOptions) -> InvokeResult
    def run_scenario(self, s: HostSession, sc: Scenario) -> ScenarioResult
    def close(self, s: HostSession) -> CloseResult                  # graceful → forced

    def collect_artifacts(self, env: SandboxEnv, s: HostSession) -> list[Artifact]
    def uninstall(self, env: SandboxEnv, pkg: PackageInfo) -> UninstallResult   # P2+
```

## 2. Behavioural rules
| # | Rule |
|---|---|
| A1 | `detect` and `static_checks` must never execute submission code. |
| A2 | Every dynamic method has a timeout from `config/thresholds.yaml`. On timeout it returns a result with `timed_out=true` and never hangs the orchestrator. |
| A3 | `close` must always end the host process: graceful quit, then kill after the timeout. It must record which of the two happened. |
| A4 | Adapters never decide `PASS`/`FAIL`. They return facts. The Check Engine applies the rules. (Exception: adapter-specific static checks return `CheckResult`s directly.) |
| A5 | Every artifact is registered through `collect_artifacts` with a type: `log`, `screenshot`, `video`, `dump`, `trace` or `drawing`. |
| A6 | Adapters raise `InfrastructureError` for MTA-side failures. These map to status `ERROR` (Constitution §3). |
| A7 | Host facts (paths, executables, runtime) come from `HostVersion`, which is loaded from `hosts.yaml`. They are never hard-coded. |

## 3. Core data types (abbreviated; full schema in [data-contracts.md](data-contracts.md))
```python
@dataclass
class HostVersion:
    host_id: str; year: int; internal: str        # "R25.1" / "2026"
    runtime: str                                   # "net8.0-windows" | "net48" | "python3.11"
    exe: str; headless_exe: str | None
    plugin_dirs: list[str]

@dataclass
class CommandInfo:
    name: str; source: Literal["manifest", "binary", "runtime", "ui"]
    assembly: str | None; flags: list[str]

@dataclass
class InvokeResult:
    command: str; outcome: Literal["completed", "awaiting_input", "cancelled", "exception", "crash", "timeout"]
    duration_ms: int; exception: str | None; evidence: list[ArtifactRef]
```

## 4. Adapter conformance suite
Each adapter must pass `tests/adapter_conformance/`. This shared pytest suite runs against:
- a **known-good** sample plugin for that host, so all core checks are expected to pass;
- a **known-bad** sample plugin per defect class: load exception, crashing command, hanging command, missing dependency.

An adapter is "supported" only when the conformance suite is green on every configured version.
