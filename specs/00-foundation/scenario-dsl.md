# Scenario DSL (v1)

Scenarios are declarative YAML workflow tests authored by reviewers. Publishers may supply them later, and they are AI-generated in Phase 5. The same DSL works for every host: steps are host-agnostic verbs, and host-specific verbs are namespaced.

## 1. Example (AutoCAD)
```yaml
scenario: acme.mytools/dimension-all
version: 1
title: "DIMALL dimensions every line in the drawing"
hosts: [autocad]
host_versions: ">=2024"
ui_mode: headless            # headless | gui | any
timeout_s: 120
setup:
  open: samples/autocad/lines_10.dwg      # from MTA sample library
steps:
  - run: ACME_DIMALL
    inputs: ["ALL", ""]                    # prompt responses in order; "" = Enter
    expect_outcome: completed
  - assert:
      entity_count: {type: AcDbRotatedDimension, op: ">=", value: 10}
  - assert:
      layer_exists: "ACME-DIMS"
  - run: ACME_EXPORTCSV
    inputs: ["${RUN_DIR}/out.csv"]
  - assert:
      file_exists: "${RUN_DIR}/out.csv"
      file_lines: {op: "==", value: 11}
teardown:
  close_document: discard
```

## 2. Generic verbs
| Verb | Purpose |
|---|---|
| `open` | Open a sample document / model |
| `new` | New document from a template |
| `run` | Invoke a command by name, with `inputs` |
| `click` | (GUI) click a UI element by `{tab, panel, button}` or automation ID |
| `dialog` | (GUI) interact with a dialog: `{title, set: {control: value}, press: OK}` |
| `wait` | Wait for a condition or duration |
| `screenshot` | Capture evidence |
| `assert` | One or more assertions |
| `save_as` | Save the document to the run dir |
| `script` | Escape hatch: host-native script (`.scr`, LISP, Python, Dynamo) |

## 3. Assertion catalogue
| Assertion | Hosts |
|---|---|
| `no_exception` (default after every step) | * |
| `outcome` | * |
| `file_exists`, `file_lines`, `file_contains` | * |
| `entity_count {type, layer?, op, value}` | autocad |
| `layer_exists`, `block_exists`, `sysvar {name, value}` | autocad |
| `element_count {category, op, value}`, `parameter_value` | revit |
| `feature_count`, `body_count`, `iproperty` | inventor, fusion |
| `node_exists`, `attribute_value` | maya, 3dsmax |
| `dialog_shown {title}` | GUI |
| `screenshot_not_blank` | GUI |

## 4. Rules
- Scenarios live in `/scenarios/<app_id>/`. They are versioned in git and linked to an app, not a submission, so they are reused for every update. This is regression testing for free.
- A scenario that fails because of a missing sample or a host mismatch gives `SKIPPED`, not `FAIL`.
- Each step emits `scenario.step` events. Assertions emit `assert.result` (see [probe-protocol.md](probe-protocol.md)).
- Secrets for apps that need sign-in are referenced via `${secret:NAME}` and resolved from the vault. They are never stored in YAML.

## 5. Phase 1 implementation notes (step 14)
- `open` is supported in `setup` only. The core console has one document, so a mid-scenario `open` makes the scenario SKIPPED until Phase 2.
- `entity_count.type` is the ObjectARX class name (`AcDbLine`, `AcDbRotatedDimension`, …) or `*`.
- `inputs: [""]` sends Enter. It is safe while a prompt is active; at `Command:` it would repeat the last command (ADR-0003 F4).
- `${RUN_DIR}` expands to the run folder in inputs, script lines and file assertions.
- `mta scenario from-features --kit` writes one draft per kit feature. `mta scenario check` validates files.
