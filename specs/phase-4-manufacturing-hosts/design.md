# Phase 4 — Manufacturing Hosts: Design

## 1. Inventor adapter
```
mta-agent ── InvDriver.exe (out-of-process .NET, COM) ──► Inventor.exe
                                                           └─ InvProbe (in-process add-in: Mta.Probe.Core hooks)
```
- **InvProbe:** an `ApplicationAddInServer` installed in the image with `LoadOnStartUp=1`. It hooks `AppDomain` first-chance and unhandled exceptions (attributed to plugin assemblies) and `ApplicationEvents` (document open/close, `OnActivateDocument`). It emits events.
- **InvDriver** (COM):
  1. `GetActiveObject` / `CreateInstance("Inventor.Application")`, `Visible` per plan, `SilentOperation = true` during open/close only.
  2. `ApplicationAddIns` → item by ClassIdString → `Activated`. If it is false, try `Activate()` and capture the exception (INV-002).
  3. Command inventory: `CommandManager.ControlDefinitions` where `ClientId == addin.ClientId` → id, display name, `Enabled`.
  4. Ribbon inventory: `UserInterfaceManager.Ribbons[env].RibbonTabs[*].RibbonPanels[*].CommandControls[*].ControlDefinition` filtered by ClientId.
  5. Per environment, open the sample doc (`samples/inventor/<year>/part.ipt`, `assembly.iam`, `drawing.idw`, `sheetmetal.ipt`, `presentation.ipn`). For each enabled definition, `Execute2(true)` runs on a worker thread with a watchdog. The FlaUI watcher captures dialogs, and `CommandManager.StopActiveCommand()` stops any command still active after the timeout.
  6. Hygiene: `doc.Dirty` after open (INV-004); `GeneralOptions` / `FileOptions` snapshot diff.

## 2. Python static toolkit (`src/mta/static/python/`), shared with 3ds Max and Maya
- `syntax.py` runs `compile(source, path, "exec")` with the host's Python version. A compile never executes code. Matching CPython versions are installed on the control plane.
- `imports.py`:
  - AST walk for `import` / `from` statements;
  - resolution order: stdlib list for the version → vendored dirs (`lib/`, `site-packages/`, `Packages/`) → host-provided modules list (`data/<host>/<build>/modules.txt`, captured from images).
- `risky.py`: AST patterns for `subprocess.*`, `os.system`, `pip`, `ctypes.windll`, `eval` / `exec` of downloaded data, `urllib` / `requests` URLs.
- `deprecations.py`: per-host deprecated API symbol list.

## 3. Fusion adapter
- **Image:** Fusion installed per-user (it auto-updates). The image pipeline **pins** a build by disabling updates after install. A weekly job rebuilds the image with the latest production build, which triggers the scheduled regression (FUS-005).
- **Sign-in:** the account is leased from the pool. First launch performs sign-in through FlaUI on the login web view, with credentials injected from the secret store. The signed-in session is cached in a *per-account* checkpoint layer where policy allows (P4-Q01).
- **MtaFusionProbe** (Python add-in, `runOnStartup: true`, loaded before the plugin through alphabetical / ordering configuration — verify):
  - `run()`:
    1. Snapshot the baseline command definitions, workspaces and panels.
    2. Wait for the plugin add-in start (poll `app.userInterface.commandDefinitions` diff + log file).
    3. Emit inventory.
  - Executes the plan (read from `MTA_RUN_DIR`). For each command definition, `cmdDef.execute()` runs on a custom event (thread-safe). After the timeout, `ui.terminateActiveCommand()`.
  - Hooks `ui.commandStarting` / `commandTerminated` events for outcome.
  - Message-box detection: the out-of-process FlaUI watcher classifies dialogs whose text matches `Traceback (most recent call last)` → FUS-003 with the text.
  - Lifecycle (FUS-004): stop the plugin via `app.scripts`/add-in API (verify) → diff the UI against the baseline → leftovers = FAIL.
- **Text commands** (`app.executeTextCommand`) are used where an API is missing, e.g. listing loaded add-ins (verify availability).

## 4. Vault adapter
```
┌────────── Vault fixture VM (vault<year>-srv) ──────────┐      ┌──── Client VM (vault<year>-cli) ─────┐
│ ADMS + SQL Server Express/Std, seeded "MTA" vault       │◄────►│ Vault Explorer + Job Processor        │
│ checkpoint: clean                                       │ iso  │ VaultProbe (IExplorerExtension +      │
└─────────────────────────────────────────────────────────┘ VLAN │   IWebServiceExtension observer)      │
                                                                 │ VaultDriver (Vault SDK client)        │
                                                                 └───────────────────────────────────────┘
```
- **Seed data:** the `infra/vault/seed/` script uses the SDK to create the folder tree, upload sample Inventor / AutoCAD files with references, lifecycle definitions, categories, users and roles. The fixture is checkpointed after seeding.
- **Static:**
  - `.vcet.config` schema;
  - mta-inspect reads `[assembly: ApiVersion("NN.0")]` and `[assembly: ExtensionId]`, and finds types implementing `IExplorerExtension`, `IWebServiceExtension` and `IJobHandler`;
  - VLT-001 maps `ApiVersion` to declared versions using `hosts.yaml` (`vault.versions[].api_version`).
- **Explorer extension test:** FlaUI logs in using the fixture credentials (secret store). `VaultProbe` records `OnLogOn` and extension load errors. Commands are found from the plugin's context-menu entries by diffing the UIA menu tree against the baseline, per selection type. Each command is executed and its outcome recorded (VLT-003).
- **Event handlers (VLT-005):** `VaultDriver` performs check-out, check-in, a lifecycle change, rename, move and delete on seeded files through the SDK. It records success, a restriction message (an `Restrictions` add from the handler is OK if declared) or an exception.
- **Jobs (VLT-004):** `JobService.AddJob(type, …)` for each `IJobHandler` type declared → start `JobProcessor.exe` in unattended mode → poll the job queue until done or failed or timeout.

## 5. Alias adapter (stretch)
- Static: PE checks; imports `libalias*`/version-specific DLLs (verify names).
- Dynamic: GUI launch → FlaUI opens Plug-in Manager → loads `.plugin` → diffs menu bar → exercises new menu items with the dialog watcher.

## 6. Catalog additions (to apply in P4-T01)
| ID | Check | Sev | Src |
|---|---|---|---|
| BIN-010 | Python plugin static health | MAJOR | S |
| INV-001 | Inventor `.addin` manifest invalid / version range mismatch | BLOCKER | S |
| INV-002 | Add-in fails to activate | BLOCKER | D |
| INV-003 | Control definition execution fails | BLOCKER | D |
| INV-004 | Activation dirties documents / changes options | MAJOR | D |
| FUS-001 | Fusion packaging / manifest invalid | BLOCKER | S |
| FUS-002 | Add-in did not start | BLOCKER | D |
| FUS-003 | Python traceback shown to user | BLOCKER | D |
| FUS-004 | UI leftovers after stop | MINOR | D |
| FUS-005 | Regression on new Fusion build | MAJOR | D |
| VLT-001 | `ApiVersion` mismatch with declared Vault version | BLOCKER | S |
| VLT-002 | `.vcet.config` / layout invalid | BLOCKER | S |
| VLT-003 | Explorer command fails | BLOCKER | D |
| VLT-004 | Job handler fails to process job | MAJOR | D |
| VLT-005 | Event handler breaks standard operation | BLOCKER | D |
| VLT-006 | Login time degraded | MINOR | D |
| ALS-001 | Alias plugin binary incompatible | BLOCKER | S |
| ALS-002 | Alias plugin fails to load / menu item fails | BLOCKER | D |
