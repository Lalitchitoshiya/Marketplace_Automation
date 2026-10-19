# Phase 5 — M&E, AI, Production: Design

## 1. 3ds Max adapter
- **Static:**
  - PackageContents components grouped by `Description` part type;
  - PE exports via `pefile` (`LibVersion` etc.);
  - the SDK version constant is read from the `LibVersion` implementation **without executing it**: disassembly-free heuristic = the version table in `data/3dsmax/sdk_versions.json` mapped from imported `core.dll` / `maxutil.dll` export ordinals and versions (verify; fallback = dynamic check in the sandbox);
  - MAXScript / Python static checks (BIN-010 for `.py`, regex/AST-lite for `.ms`).
- **Headless:** `3dsmaxbatch.exe <run>\probe\mta_probe.py -mxsString ... -sceneFile <sample.max> -v 5 -log <run>\max.log` (switches verify). Probe (pymxs):
  1. Emit loaded plugin DLLs (`pluginManager` APIs, verify), compared with the expected plugin DLL paths → LOD-001 / MAX-002.
  2. Enumerate classes whose DLL is under the plugin folder (`rt.<superclass>.classes` + `exprForMAXObject`, verify) → CMD-001 inventory.
  3. For each class: create it in an empty scene; for modifiers, apply to a box; for materials, assign to a box; record exceptions (MAX-003).
  4. Macroscripts: parse `.mcr` for category / name, then `macros.run cat name` under watchdog (CMD-002).
  5. Save the scene with plugin objects → reset → load → compare object counts (MAX-004).
- **GUI:** `3dsmax.exe -U PythonHost <probe_gui.py>`, with menus via `rt.menuMan` (legacy) / the new menu system (2025+, verify), toolbars via CUI files, and the dialog watcher via FlaUI (Qt windows expose UIA partially; fallback to screenshot + Qt introspection through PySide).

## 2. Maya adapter
- **Environment:**
  - `MAYA_APP_DIR=<run>\maya_app`;
  - `MAYA_MODULE_PATH=<run>\plugin\modules;<image default>`;
  - `MAYA_DISABLE_CIP=1`, `MAYA_DISABLE_CER=1` (no telemetry or crash-reporter UI);
  - `MAYA_NO_HOME=1` where appropriate.
- **Headless probe** (`mayapy mta_maya_probe.py`):
```python
import maya.standalone; maya.standalone.initialize(name="python")
from maya import cmds
# for each plugin file p:
cmds.loadPlugin(p)                                  # LOD-001
info = {"commands": cmds.pluginInfo(p, q=True, command=True) or [],
        "nodes": cmds.pluginInfo(p, q=True, dependNode=True) or []}   # CMD-001
# smoke commands: call with no args under watchdog; RuntimeError(usage) ⇒ ok
# nodes: cmds.createNode(t) in fresh scene ⇒ MAYA-002
# round trip: cmds.file(rename=...); cmds.file(save=True, type="mayaAscii"); reopen; compare ⇒ MAYA-004
cmds.file(new=True, force=True); cmds.unloadPlugin(p)   # MAYA-003
```
  The watchdog uses a per-command subprocess fallback (same strategy as AutoCAD batch → isolate).
- **GUI:**
  - `maya.exe -command "python(\"import mta_probe_gui; mta_probe_gui.run()\")"`;
  - inventory via `cmds.lsUI(menus=True, windows=True)` and shelf layouts (diff against baseline);
  - menu items are invoked through their `command` callbacks;
  - Qt windows are found through `shiboken` / `PySide` `QApplication.topLevelWidgets()` for dialog capture and closing.

## 3. AI Feature Tester
```
          ┌────────────────────────── ai-service (Python) ─────────────────────────────┐
listing ─►│ 1 ClaimExtractor ──► claims.json (quotes verified against source text)       │
docs    ─►│ 2 ScenarioSynthesizer ─► DSL YAML ─► validator/linter ─► (≤2 retries)        │
inventory►│ 3 Router: DSL-expressible? ── yes ─► normal scenario runner (deterministic)  │
samples ─►│                           └─ no ──► 4 Agent runner (computer use, in VM)     │
          │ 5 Judge (evidence → supported / contradicted / inconclusive + confidence)    │
          │ 6 Results → CheckResults(source=ai) ; promotion API                          │
          └──────────────────────────────────────────────────────────────────────────────┘
```
- **Model configuration:** `config/ai.yaml` sets `{endpoint, models: {extract, synthesize, agent, judge}, budgets}`. The default is the most capable approved Claude model for the agent and the judge, and a smaller, faster model for extraction and linting. Models are swappable. P5-R14 evals gate any change.
- **Prompt hygiene:** untrusted text is wrapped in tagged blocks with an explicit "data, not instructions" system rule. The agent tool schema exposes only: `screenshot`, `uia_tree`, `click(x,y|automation_id)`, `type(text)`, `key(combo)`, `wait(ms)`, `open_sample(name)`, `done(summary)`. There is no shell tool.
- **Agent runtime:** the agent loop runs on the control plane and sends actions to mta-agent in the VM (pyautogui / FlaUI executor). Every step stores the screenshot, action and model summary as an artifact. Budgets are enforced by the runner, not by the model.
- **Judge input:** the claim, the scenario or agent trajectory summary, before / after screenshots, probe events (commands run, exceptions) and output files. The judge must cite evidence artifact IDs. A judgement without a citation is downgraded to `inconclusive`.
- **Evaluation harness:** `mta ai eval` runs the labelled set and writes metrics to `corpus/ai-results/<date>.json`.

## 4. Publisher Corner integration
- An `intake-connector` service receives a webhook, or polls at an interval (P5-Q01). It then:
  1. downloads the package and listing through a service account;
  2. calls `POST /submissions` with `idempotency_key = pc_submission_id + revision`;
  3. on report completion, posts `{recommendation, report_url, summary}` back to the internal review record.
- Retries use exponential backoff and a dead-letter queue. Alerts fire after 3 failures.

## 5. Compatibility sweep
- Triggered by an image registration with `sweep: true`.
- Selects the latest approved submission per app whose declared host family matches. It creates Jobs with `priority=low` and `versions=[new]` and **forces** the run even if the new version is outside the app's declared range: the point is to see whether the app would work.
- Aggregate report: a table of apps × {compatible, issues, blocked}, plus top failure checks.

## 6. Production topology
- **Control plane:** containers (AKS or an equivalent Autodesk platform), PostgreSQL (managed, HA), Redis (HA), artifact store with lifecycle rules.
- **Execution plane:** N Hyper-V hosts or Azure Dv5 / Ev5 hosts with nested virtualisation (decided in Phase 2, P2-Q04). The pool autoscaler is driven by queue depth per image family and licence seats.
- **Observability:**
  - OpenTelemetry SDK in the API, scheduler, hostd and agent;
  - Prometheus + Grafana dashboards: queue, pool, seats, Run outcomes, ERROR rate, AI cost;
  - alerting to the Marketplace ops channel.
- **Security:**
  - OIDC SSO;
  - RBAC roles reviewer / lead / admin / auditor;
  - audit log (append-only);
  - secrets in the vault;
  - mTLS between hostd and the control plane;
  - weekly image patching pipeline.

## 7. Catalog additions (to apply in P5-T01)
| ID | Check | Sev | Src |
|---|---|---|---|
| MAX-001 | C++ plugin exports / SDK version incompatible | BLOCKER | S |
| MAX-002 | Plugin DLL / script / macro failed to load | BLOCKER | D |
| MAX-003 | Plugin class fails to instantiate / apply | BLOCKER | D |
| MAX-004 | Scene round-trip fails or crashes after uninstall | MAJOR | D |
| MAYA-001 | Module / plugin packaging invalid | BLOCKER | S |
| MAYA-002 | Plugin node creation fails | BLOCKER | D |
| MAYA-003 | Plugin fails to unload cleanly | MAJOR | D |
| MAYA-004 | Scene save / reopen loses data | MAJOR | D |
| MAYA-005 | Persistent environment modification / leaked script jobs | MAJOR | D/M |
