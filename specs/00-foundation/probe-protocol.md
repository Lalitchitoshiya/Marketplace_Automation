# Probe Protocol

Probes run **inside** the host process. They observe the plugin and execute test actions. They talk to the orchestrator through files, so the protocol works identically in headless consoles, GUI hosts and VMs. See [ADR-0002](../adr/ADR-0002-ndjson-probe-protocol.md).

## 1. Channel
| File | Direction | Format |
|---|---|---|
| `%MTA_RUN_DIR%\probe-plan.json` | orchestrator → probe | JSON. Actions to perform. |
| `%MTA_RUN_DIR%\probe-events.ndjson` | probe → orchestrator | One JSON event per line, append-only, flushed after each write |
| `%MTA_RUN_DIR%\artifacts\` | probe → orchestrator | Screenshots, exported drawings, etc. |

The environment variable `MTA_RUN_DIR` is set before the host launches. If the probe cannot write events, the run is `ERROR`.

**Neutral names on the wire.** A plugin could find the run folder through the environment, so every name it could see comes from `config/probe_identity.yaml` (Constitution §11):
- the environment variable (`run_dir_env`, e.g. `WSA_SESSION_DIR`);
- the plan and event file names (`plan_file` / `events_file`, e.g. `session.json` / `session.log`);
- the assembly, command and LISP-function names.

`MTA_RUN_DIR`, `probe-plan.json` and `probe-events.ndjson` in this document are placeholders. For the same reason the probe's own events are named `session.start` / `session.error` / `session.shutdown` on the wire, and `probe_version` is sent as `version`. `test_built_probe_reveals_nothing` checks that the built DLL contains no "mta", "probe" or "test".

## 2. Event envelope
```json
{"v":1,"seq":17,"ts":"2026-10-19T10:02:03.120Z","run_id":"r-8f2c","type":"command.invoke.end",
 "data":{ ... }}
```
`seq` is strictly increasing. Gaps indicate a crash. The orchestrator also treats a missing `probe.shutdown` event as a sign of an abnormal exit.

## 3. Event types (v1)
| type | data fields | Emitted when |
|---|---|---|
| `probe.start` | probe_version, host_id, host_version, pid, runtime | Probe initialised |
| `host.ready` | startup_ms | Host finished startup (doc manager ready, ApplicationInitialized, …) |
| `assembly.load` | name, version, path, target_framework | Any assembly loads into the host (AppDomain/AssemblyLoadContext hook) |
| `component.load.begin` / `.end` | component, module_path, loader (`netload`/`arx`/`lisp`/`autoload`/`addin`), ok, error, duration_ms | Plugin component load attempt |
| `command.registered` | name, group, source_assembly, flags | Probe enumerates commands after load |
| `ui.element` | kind (`tab`/`panel`/`button`/`menu`/`toolbar`/`palette`), id, text, command | UI inventory (GUI mode) |
| `command.invoke.begin` / `.end` | command, outcome, duration_ms, exception, prompts_seen[] | Smoke or scenario invocation |
| `scenario.step` | scenario_id, step_index, action, status, detail | Scenario execution |
| `assert.result` | scenario_id, assertion, expected, actual, ok | Scenario assertion |
| `exception.unhandled` | type, message, stack, source_assembly, is_terminating | AppDomain / dispatcher unhandled exception |
| `exception.first_chance` | type, source_assembly (rate-limited, plugin assemblies only) | Optional diagnostic |
| `dialog.shown` | title, owner, screenshot | Modal dialog detected (GUI mode) |
| `metric` | name, value, unit | Memory, handles, GDI objects, timing |
| `artifact` | kind, path, sha256 | Probe produced a file |
| `probe.error` | message, stack | Probe internal failure → `ERROR` |
| `probe.shutdown` | reason | Clean end |

**Added in step 11 (AutoCAD core console, v1 minor additions):**

| type | data fields | Emitted when |
|---|---|---|
| `mark` | phase (`begin`/`end`), label | The script brackets a smoke invocation (`MARK begin X` … `MARK end X`) |
| `command.start` / `.ended` / `.cancelled` / `.failed` / `.unknown` | name, mark | Raw `Document.Command*` events (ADR-0003 F19); the runner derives `command.invoke.*` outcomes from them |
| `prompt` | kind (`string`/`keyword`/`point`/…), message, mark | `Editor.PromptingFor*`, excluding the probe's own argument prompts |
| `command.defined` | name, defined, global | The script reports `(getcname "X")` through the probe's LISP function (F18) |
| `enumerate.end` | count | After the `command.registered` events of an enumerate |
| `note` | kind, name, value | Other values reported through the LISP function |

`component.load.end` also carries `loaded`: whether an assembly from exactly that file is now in the process. That is the load evidence; the `assembly.load` event was missing for one WPF plugin in step 12. It also carries `plugin_exceptions`: the plugin first-chance exceptions seen during the load. An exception in `Initialize` is otherwise silent (F11). Exception events carry the active `mark`.

**Driving the probe:** every probe command reads one argument from the next script line (`GetString`, spaces allowed). For example, the `load` command followed by a component name loads that component from the plan.

New event types may be added in a minor version. Consumers must ignore unknown types.

## 4. probe-plan.json
```json
{
  "v": 1,
  "run_id": "r-8f2c",
  "components": [{"name":"MyTools","module":"C:\\...\\MyTools.dll","loader":"netload"}],
  "phases": ["load", "enumerate", "smoke", "scenarios"],
  "smoke": {"commands": "all", "timeout_ms": 20000, "on_prompt": "cancel", "isolate_document": true},
  "scenarios": ["scenarios/acme-mytools/basic.yaml"],
  "sample_documents": ["C:\\mta\\samples\\autocad\\blank_metric.dwg"]
}
```

## 5. Probe implementation requirements
- The probe must never change plugin behaviour beyond what the plan requests.
- The probe catches its own exceptions and reports `probe.error`. It never crashes the host.
- The probe assembly is strong-named and signed by Autodesk / MTA. Its assembly name, command names and add-in IDs come from `config/probe_identity.yaml` and are **neutral** (no `Mta` / `Probe` / `Test`), so the plugin under test cannot detect it ([security-and-isolation.md](security-and-isolation.md) §5). Names such as `MtaProbe.*` and `MTAPROBE_*` in these specs are **placeholders**. The probe's real assemblies are excluded from plugin attribution by their configured identity.
- Exception attribution: an exception counts as belonging to the plugin if any stack frame belongs to an assembly loaded from the plugin's deployment folder.
