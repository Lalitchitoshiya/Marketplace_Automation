# Host Matrix

The facts below seed `config/hosts.yaml`.

> ⚠ Values marked **(verify)** must be confirmed by the phase's discovery spike against installed products and Autodesk developer documentation before implementation. Per Constitution §5, a wrong value is fixed in config, not code.

## 1. Phase allocation
| Host | Family | Plugin tech | Native loader | Headless option | Phase |
|---|---|---|---|---|---|
| AutoCAD | AutoCAD | .NET, ObjectARX (C++), AutoLISP, VBA (legacy) | ApplicationPlugins bundle autoloader | **AcCoreConsole** | **1** |
| AutoCAD verticals: Civil 3D, Map 3D, Plant 3D, Electrical, Mechanical, MEP, Architecture | AutoCAD | as AutoCAD + vertical APIs | bundle (`Platform=`/vertical attrs) | AcCoreConsole with `/product` (verify per vertical) | 2 |
| Advance Steel | AutoCAD-based | .NET (Advance Steel API) | bundle / addon registration (verify) | limited (verify) | 2 |
| Revit | AEC | .NET (Revit API) | `.addin` manifest / bundle | none official → probe-driven GUI + journals; APS Design Automation for DB-only logic | 3 |
| Navisworks Manage/Simulate | AEC | .NET (Navisworks API) | Plugins folder / bundle | Automation API (`NavisworksAutomation`) | 3 |
| Robot Structural Analysis | AEC | COM (RobotOM), .NET add-ins | add-in registration | COM automation (window hidden) | 3 |
| Inventor | MFG | .NET / COM add-ins | `.addin` file / bundle | COM `Visible=false`; Apprentice for read-only | 4 |
| Fusion | MFG | Python / C++ add-ins | `AddIns` folder + `.manifest` | none (GUI + harness add-in); requires sign-in | 4 |
| Vault (Client) | MFG/PDM | .NET extensions (`IExplorerExtension`, `IWebServiceExtension`, Job Processor) | `Extensions` folder + `.vcet.config` | Vault SDK client; Job Processor | 4 |
| Alias | Automotive | C++ plugins (`.plugin`) | Plug-in Manager | none (verify) | 4 (stretch) |
| 3ds Max | M&E | C++ (`.dlx/.dlo/.dlm/.gup`), .NET, MAXScript, Python (pymxs) | `ApplicationPlugins` bundle, plugin dirs | **3dsmaxbatch.exe** | 5 |
| Maya | M&E | C++ (`.mll`), Python, MEL | Modules (`.mod`), `MAYA_MODULE_PATH`, Plug-in Manager | **mayapy** / `maya.standalone`, `maya -batch` | 5 |

## 2. Version × runtime seed (all **(verify)**)
| Host | Version | Internal | Runtime for plugins |
|---|---|---|---|
| AutoCAD | 2024 | R24.3 | .NET Framework 4.8 |
| AutoCAD | 2025 | R25.0 | .NET 8 |
| AutoCAD | 2026 | R25.1 | .NET 8 |
| AutoCAD | 2027 | R26.0 (likely: Autodesk's `AutoCAD.NET` NuGet package version 26.0.0 exists) | .NET 10 likely (packages ship `lib/net10.0`) (verify) |
| Revit | 2024 | — | .NET Framework 4.8 |
| Revit | 2025 / 2026 | — | .NET 8 |
| Revit | 2027 | — | (verify) |
| Inventor | 2024 | — | .NET Framework 4.8 |
| Inventor | 2025 / 2026 | — | .NET 8 |
| Navisworks | 2024–2027 | — | (verify) |
| Vault | 2024–2027 | — | (verify) |
| 3ds Max | 2024–2027 | — | .NET (verify), Python 3.x (verify) |
| Maya | 2024 / 2025 / 2026 | — | Python 3.10 / 3.11 / 3.11 (verify) |
| Fusion | rolling | — | Python 3.x bundled (verify) |

**Supported-version policy:** the current year plus three previous years, aligned with Marketplace listing practice. This is configurable.

## 3. hosts.yaml shape
```yaml
hosts:
  autocad:
    family: autocad
    versions:
      - year: 2026
        internal: R25.1
        runtime: net8.0-windows
        install_dir: "C:/Program Files/Autodesk/AutoCAD 2026"
        exe: acad.exe
        headless_exe: accoreconsole.exe
        api_assemblies: [AcCoreMgd.dll, AcDbMgd.dll, AcMgd.dll]
        ui_only_assemblies: [AcMgd.dll, AdWindows.dll, AcWindows.dll]
        plugin_dirs:
          - "%ProgramData%/Autodesk/ApplicationPlugins"
          - "%APPDATA%/Autodesk/ApplicationPlugins"
        verticals:
          civil3d: {product_switch: "/product C3D", language: en-US}   # (verify)
        builtin_commands_file: data/autocad/2026/commands.txt
```

## 4. Sample document library (`/samples/<host>/`)
Each host needs a minimal library. Reviewers can extend it.
- **AutoCAD:** blank metric/imperial, lines_10, blocks_attrs, xref_set, layouts_viewports, large_50MB, Civil surface (vertical).
- **Revit:** empty architectural/structural/MEP templates, small house, worksharing central model, linked model, family file.
- **Inventor:** part, assembly (100 parts), drawing, sheet metal, iLogic part.
- **Navisworks:** NWD federated model with clash set.
- **3ds Max / Maya:** empty scene, scene with meshes/materials/animation, references.
