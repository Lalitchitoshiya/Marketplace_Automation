# Submission Inputs: the Input Kit

How we give MTA everything it needs to test a plugin: the package, its description, user guide, screenshots, sample files and test hints.

## 1. Idea

Every test starts from one **Input Kit**: a folder (or ZIP) with a fixed layout and one required form file, `submission.yaml`. The kit is the same in every phase. Only the way it arrives changes:

| Phase | How the kit arrives |
|---|---|
| **1** | Reviewer prepares the folder by hand (or with `mta kit init`) and runs `mta run --kit <folder>` |
| **2–4** | Reviewer uploads the files through the **web dashboard** form ("New test"), or the API (`POST /submissions`) |
| **5** | **Built automatically from Publisher Corner** (package, listing text, screenshots, links). Reviewers can still add files in the dashboard. |

## 2. Kit layout

```
acme-mytools-2.3.0/
├── submission.yaml          ← REQUIRED: the "form" (app info, versions, features, hints)
├── package/                 ← REQUIRED: exactly one MSI, .bundle folder or ZIP
│   └── MyTools.msi
├── docs/                    ← optional: user guide, help, release notes
│   ├── user-guide.pdf
│   ├── quick-start.md
│   └── release-notes.txt
├── media/                   ← optional: listing screenshots, demo videos
│   ├── screenshots/
│   │   ├── 01-ribbon.png
│   │   └── 02-dialog.png
│   └── videos/
│       └── demo.mp4
├── samples/                 ← optional: publisher's own test files
│   └── site-plan.dwg
└── scenarios/               ← optional: ready-made test scenarios (YAML)
    └── dimension-all.yaml
```

Accepted formats:

| Folder | Formats | Limits (default) |
|---|---|---|
| `docs/` | PDF, DOCX, Markdown, TXT, HTML | 50 MB per file |
| `media/screenshots/` | PNG, JPG | 10 MB per image, max 30 |
| `media/videos/` | MP4, WEBM | 500 MB per video |
| `samples/` | Host file types (DWG, DXF, RVT, RFA, IPT, IAM, NWD, MAX, MA/MB, …) | 500 MB per file |
| `scenarios/` | YAML per [scenario-dsl.md](scenario-dsl.md) | — |

## 3. `submission.yaml`

```yaml
kit_version: 1

app:
  id: acme.mytools                 # stable across versions (links history & scenarios)
  title: "MyTools for AutoCAD"
  version: "2.3.0"
  publisher: "Acme Ltd"
  type: desktop                    # desktop (POC scope); web / mcp later
  pricing: paid                    # free | trial | paid | subscription

products:                          # what the listing says it supports
  - host: autocad
    versions: [2024, 2025, 2026]
    verticals: []                  # e.g. [civil3d]

listing:
  short_description: "Automatic dimensioning and CSV export."
  description_file: docs/listing-description.md     # or inline `description: |`
  support_email: support@acme.example
  privacy_policy_url: https://acme.example/privacy
  documentation_urls:
    - https://acme.example/mytools/help
  external_domains: [api.acme.example]              # every server the plugin talks to
  screenshots: [media/screenshots/01-ribbon.png, media/screenshots/02-dialog.png]

documents:                         # files in docs/, with what they are
  - path: docs/user-guide.pdf
    kind: user_guide               # user_guide | quick_start | release_notes | install_guide | other
  - path: docs/release-notes.txt
    kind: release_notes

# --- The most useful part for testing: structured feature hints -------------
features:
  - id: F1
    name: "Dimension all lines"
    how_to: "Ribbon > Acme tab > Dimensions panel > Dim All, or command ACME_DIMALL"
    commands: [ACME_DIMALL]
    sample: samples/site-plan.dwg
    expected: "Every line gets an aligned dimension on layer ACME-DIMS"
  - id: F2
    name: "Export dimensions to CSV"
    commands: [ACME_EXPORTCSV]
    expected: "A CSV file with one row per dimension"

test_hints:
  needs_login: false               # plugin requires its own account?
  credentials_ref: null            # name of secret in the vault, never the password itself
  licence_key_ref: null            # same, for paid apps needing a key
  needs_internet: true
  known_limitations: "Does not support paper space."
  reviewer_notes: ""
```

Rules:
- Only `kit_version`, `app.id`, `app.version` and the `package/` folder are **required**. Everything else improves the tests but is optional.
- **Passwords and licence keys are never written in the kit.** They go into the secret vault, and the kit only names them (`credentials_ref`).
- Paths are relative to the kit root.

## 4. What MTA does with each input

| Input | Phase 1–2 (rule-based) | Phase 5 (AI) |
|---|---|---|
| `package/` | Everything: static checks, install, load, commands, UI, monitoring | same |
| `products` | Which versions and verticals to test; LST-003 consistency check | same |
| `support_email`, `privacy_policy_url` | LST-001, LST-002 | same |
| `external_domains` | NET-003: flag connections to undeclared servers | same |
| `features[]` | **Auto-generated draft scenarios**: each feature with `commands` + `sample` becomes a scenario skeleton (`mta scenario from-features`). The reviewer adds the assertions. Features listing a command that does not exist → CMD-001 finding. | Claims are taken directly from `features` (highest-quality input) |
| `samples/` | Used as the document for smoke tests and scenarios, in addition to MTA's standard sample library | same |
| `scenarios/` | Executed as workflow tests (WFL-001/002) | same |
| `docs/` (user guide etc.) | Text extracted and searched for **command names**. Commands mentioned in the guide but missing at runtime → finding; commands that exist but are undocumented → INFO. Shown to reviewers in the report. | AI reads the guide → extracts testable claims → generates scenarios → explores the UI (AI-001…003) |
| `media/screenshots/` | Shown in the report **side by side** with MTA's own screenshots of the real UI | LST-005: AI compares listing screenshots with the real UI |
| `media/videos/` | Linked in the report for the reviewer | Key frames extracted and used as extra context for the AI tester |
| `test_hints` | Login and licence handling, offline run decisions, notes shown to reviewer | Passed to the AI tester as context |

## 5. Processing pipeline

```
Input Kit ──► 1 validate (schema, files exist, formats, size limits, malware scan on ALL files)
          ──► 2 store (content-addressed, SHA-256)
          ──► 3 extract
                 docs/*.pdf  → text (pypdf)           docs/*.docx → text (python-docx)
                 docs/*.html → main text              docs/*.md   → as is
                 screenshots → thumbnails             videos      → key frames (ffmpeg, Phase 5)
          ──► 4 index: command names, ribbon labels and feature names found in the text
          ──► 5 hand to static checks, the scenario generator and (Phase 5) the AI tester
```

## 6. Safety rules for inputs
- All kit files are **untrusted**, like the package itself:
  - they are malware-scanned;
  - macros in DOCX files are never executed;
  - PDFs are parsed as text only;
  - sample drawings and models are opened **only inside the sandbox**.
- Text from docs and listings is **data, never instructions**. The Phase 5 AI treats it as quoted material only (see Phase 5 P5-R13).
- Size and count limits are applied before extraction (PKG-001 rules apply to the kit too).

## 7. CLI support (Phase 1)

| Command | What it does |
|---|---|
| `mta kit init <folder> --package MyTools.msi` | Creates the folder layout and a pre-filled `submission.yaml` (products, versions and commands detected from the package) |
| `mta kit validate <folder>` | Checks the kit: schema, paths, formats, limits |
| `mta scenario from-features <folder>` | Turns `features[]` into draft scenario YAMLs in `scenarios/` |
| `mta run --kit <folder>` | Full test run using the kit |
| `mta run <package>` | Still works: a minimal kit is created on the fly (no docs, no features) |

## 8. Recommendation to Autodesk
The `features` section (name, how to use it, command, sample, expected result) is the single most valuable input for automated testing. We recommend that Autodesk **adds an optional "Test information" section to the Publisher Corner submission form** with these fields. In Phase 5 it would then flow into MTA automatically.
