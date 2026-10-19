# Glossary

| Term | Meaning |
|---|---|
| **Submission** | One version of one Marketplace app as uploaded by a publisher: package + listing metadata. |
| **Package** | The binary deliverable: an MSI, a `.bundle` folder, or a ZIP containing one. |
| **Bundle** | Autodesk ApplicationPlugins format: a `<Name>.bundle` folder with `PackageContents.xml` at its root, deployed to `%ProgramData%\Autodesk\ApplicationPlugins` or `%APPDATA%\Autodesk\ApplicationPlugins`. |
| **PackageContents.xml** | Bundle manifest. Declares product, versions (`SeriesMin`/`SeriesMax`), components (`ComponentEntry`) and commands. |
| **Autoloader** | AutoCAD-family mechanism that loads bundles at startup (`APPAUTOLOAD` system variable). |
| **Host** | An Autodesk desktop product that loads plugins (AutoCAD, Revit, Inventor, …). |
| **Host version** | A product year, e.g. AutoCAD 2026 (`R25.1`). |
| **Vertical** | A product built on a host platform, e.g. Civil 3D on AutoCAD. |
| **Host Adapter** | MTA module that knows how to deploy, launch, probe and tear down one host. See [host-adapter-contract.md](host-adapter-contract.md). |
| **Probe** | Code MTA injects into the host process (C# add-in or Python script). It observes the plugin and executes test actions, emitting NDJSON events. |
| **AcCoreConsole** | `accoreconsole.exe`: headless AutoCAD executable that runs script files without UI. It cannot load assemblies that depend on `AcMgd.dll` (UI). |
| **Check** | One automated verification with a catalog ID (e.g. `MAN-004`). |
| **CheckResult** | Outcome of a check on one target: status, severity, evidence. |
| **Status** | `PASS`, `FAIL`, `WARN`, `NEEDS_REVIEW`, `SKIPPED` or `ERROR`. `ERROR` means an MTA/infrastructure failure. |
| **Severity** | `BLOCKER`, `MAJOR`, `MINOR` or `INFO`. |
| **Recommendation** | Job-level outcome: `RECOMMEND_APPROVE`, `RECOMMEND_REJECT` or `NEEDS_HUMAN`. |
| **Scenario** | Declarative YAML workflow test ([scenario-dsl.md](scenario-dsl.md)). |
| **Job** | One execution of MTA against a submission. |
| **Run** | One (job × host × version) execution unit. |
| **Golden corpus** | Curated set of plugins with known manual verdicts, used to measure MTA accuracy. |
| **Sandbox** | Isolated execution environment: an isolated profile in Phase 1, a disposable VM from Phase 2. |
| **Evidence** | An artifact supporting a CheckResult: log, screenshot, video, trace, or file excerpt. |
| **EARS** | Easy Approach to Requirements Syntax, used for acceptance criteria. |
| **APS** | Autodesk Platform Services (formerly Forge). |
