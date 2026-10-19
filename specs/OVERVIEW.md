# MTA: Overview

> **Marketplace Test Automation (MTA)** automatically tests the plugins and add-ins that publishers submit to the Autodesk Marketplace. Reviewers get a ready-made test report instead of testing everything by hand.

This page gives the big picture. For details, follow the links at the end.

---

## 1. The problem

Every time a publisher submits a new app or an update to the Autodesk Marketplace, an Autodesk reviewer tests it **by hand**:

1. Install the plugin.
2. Open AutoCAD, Revit or another product, and check that the plugin loads.
3. Click through its buttons and commands to see whether anything crashes.
4. Try its main workflows on sample drawings or models.
5. **Repeat for every product version** the plugin supports (e.g. AutoCAD 2024, 2025, 2026, 2027).
6. Check the paperwork: digital signature, privacy policy, support email.
7. Uninstall it and make sure nothing is left broken.

This is **slow** (hours per app), **repetitive**, and **inconsistent**: two reviewers may test differently. The work grows with every new app, update and product version.

## 2. The idea in one sentence

> **A robot reviewer does the repetitive testing in a safe, disposable computer, records everything it sees, and hands the human reviewer a report with evidence, so the human only judges what was flagged.**

The human still makes the final decision. MTA never approves or publishes anything on its own.

## 3. How it works

```
 Publisher submits app
          │
          ▼
 ┌─────────────────────┐   1. LOOK (without running anything)
 │  Inspect the files  │   Is the package complete? Right versions? Signed?
 │                     │   Virus-free? Privacy policy link working?
 └─────────┬───────────┘
           ▼
 ┌─────────────────────┐   2. RUN IT SAFELY
 │  Disposable test PC │   A clean virtual machine with AutoCAD (or Revit, …)
 │  (virtual machine)  │   installed. The plugin can't harm anything real.
 └─────────┬───────────┘   It's wiped after every test.
           ▼
 ┌─────────────────────┐   3. WATCH & TRY
 │  Our "probe" inside │   A helper plugin we wrote sits inside the product, next
 │  the product        │   to the publisher's plugin, and:
 │                     │    • checks the plugin loaded
 │                     │    • runs every command/button once (smoke test)
 │                     │    • runs workflow scenarios on sample drawings
 │                     │    • notes every error, crash, popup and screenshot
 └─────────┬───────────┘   In the background, the system also records files
           │               written, internet connections and settings changed.
           ▼               ×  repeated for every supported product version
 ┌─────────────────────┐
 │  4. REPORT          │   One page: Approve / Reject / Needs a human,
 │                     │   with proof (logs, screenshots, video) for every finding.
 └─────────┬───────────┘
           ▼
   Human reviewer decides
```

### What the reviewer sees
- A **recommendation**: ✅ approve, ❌ reject, or 👀 needs a human.
- A **table of versions**, e.g. "works in AutoCAD 2025 and 2026, crashes in 2024".
- A **list of findings**. Each finding has proof, e.g. "Command `DIMALL` crashed with this error (log) on this drawing (screenshot)".
- For updates: **what changed** since the last approved version.

## 4. What gets automated

| Manual reviewer task today | MTA |
|---|---|
| Check package, versions, signature, virus scan | ✅ Fully automatic |
| Check listing details (privacy link, support email) | ✅ Fully automatic |
| Install / uninstall | ✅ Fully automatic |
| Does it load? Do commands exist? Any crash? | ✅ Fully automatic |
| Click every ribbon button, open dialogs | ✅ Automatic, with screenshots and video |
| Is it doing anything suspicious (hidden internet calls, auto-start tricks)? | ✅ Automatic monitoring (manual review rarely catches this) |
| Repeat everything for each product version | ✅ Runs in parallel on several test machines |
| Run real workflows | ✅ Via reusable **scenarios** written once per app and re-run on every update |
| "Does it really do what the listing promises?" | 🤖 AI assistant tries it and reports, a human confirms (Phase 5) |
| Final approve / reject decision | 👤 **Always a human** |

## 5. Key ideas that make it work

1. **One common plug for all products.** Each Autodesk product (AutoCAD, Revit, Inventor…) gets an **adapter** that follows the same rules. Adding a new product means writing a new adapter, without rebuilding the system.
2. **A probe inside the product.** Watching from inside the product, rather than only clicking from outside, gives exact, reliable information: which command failed, with which error.
3. **Disposable machines.** Plugins are untrusted code, so they only ever run on throw-away virtual machines that are reset after every test.
4. **Evidence for everything.** No finding without proof. Reviewers can trust or quickly double-check every result.
5. **Our failures are not the publisher's failures.** If our test machine breaks, the result says "infrastructure error", never "plugin failed".
6. **Tests improve over time.** Workflow scenarios are saved per app and re-run automatically on every update, which gives free regression testing.
7. **Measured against humans.** We keep a set of plugins with known human verdicts and keep checking that MTA agrees with them before anyone relies on it.

## 6. Roadmap: 5 phases

| Phase | Products | What we deliver | Duration |
|---|---|---|---|
| **1. POC** | AutoCAD | Command-line tool: file inspection + headless AutoCAD (no window) to load the plugin and run every command + HTML report | 6 weeks |
| **2. AutoCAD complete** | AutoCAD + Civil 3D, Plant 3D, etc. | Disposable VMs, real install / uninstall, full UI testing (ribbon, dialogs, video), behaviour monitoring, all versions, reviewer dashboard | 8 weeks |
| **3. AEC** | Revit, Navisworks, Robot | Reusable adapter kit + three new products | 8 weeks |
| **4. Manufacturing** | Inventor, Fusion, Vault, Alias | Python-based add-ins, cloud sign-in (Fusion), test server (Vault) | 8 weeks |
| **5. Media & AI & production** | 3ds Max, Maya | AI feature testing, automatic trigger from Publisher Corner, re-testing all apps when a new product version is released, production rollout | 10 weeks |

**Rollout is gradual:**
1. **Shadow mode:** MTA runs quietly next to human reviewers, and we compare results.
2. **Assisted mode:** reviewers start from the MTA report.
3. **Default mode:** every desktop submission gets an MTA report.

## 7. Expected benefits

| Goal | Target |
|---|---|
| Reviewer time per submission | **≥70% less** |
| Version coverage | **100%** of declared versions tested, every time |
| Consistency | Same input → same result, every time |
| Catch real problems | ≥90% of problems humans find |
| False alarms | ≤10% of "fail" results overturned by reviewers |
| Bonus | Proactive compatibility report for every app when a new product year (e.g. AutoCAD 2028) arrives |

## 8. What we need from Autodesk

1. **Their current manual review checklist.** This defines exactly what we automate.
2. **Sample submissions with past review verdicts**, to measure our accuracy.
3. **Product licences** that work on unattended test machines.
4. **Test infrastructure** (virtual machine hosts), from Phase 2.
5. **Access to Publisher Corner submission events**, in Phase 5.

## 9. Not in this POC (possible next steps)

- Web apps (browser-based integrations).
- MCP servers (AI connectors).

**Deliberately never included:** any way for publishers to run MTA or see its results. MTA is internal to Autodesk. Publishers can't find out in advance whether their app will pass, and the test environment is built so that plugins can't tell they are being tested.

---

## Where to go next

| If you want to… | Read |
|---|---|
| Understand the project rules | [constitution.md](00-foundation/constitution.md) |
| See goals and scope | [product-vision.md](00-foundation/product-vision.md) |
| See the phases in detail | [roadmap.md](00-foundation/roadmap.md) |
| Understand the system design | [architecture.md](00-foundation/architecture.md) |
| See what we build it with (CLI, web app, technologies) | [tech-stack.md](00-foundation/tech-stack.md) |
| See every automated check | [check-catalog.md](00-foundation/check-catalog.md) |
| Start building Phase 1 | [phase-1-autocad-headless/](phase-1-autocad-headless/) |
| Look up a term | [glossary.md](00-foundation/glossary.md) |
