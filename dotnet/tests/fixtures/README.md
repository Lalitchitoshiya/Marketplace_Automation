# Inspection fixtures

Test inputs for `mta-inspect` and the Python BIN-* rules. These assemblies are never loaded or run.

| Project | What it is | Used for |
|---|---|---|
| `FakeAcCoreMgd` | Assembly named **AcCoreMgd 25.0.0.0** with the same type names as AutoCAD's `CommandMethodAttribute`, `CommandFlags`, `IExtensionApplication`, `PaletteSet` … | Lets fixture plugins compile **without AutoCAD** (CI has none). Metadata only records type names, which is exactly what `mta-inspect` reads. |
| `FixturePlugin` | net8.0 plugin using every `CommandMethod` overload, an unregistered command class, `LispFunction`, P/Invoke, URLs, `Process.Start`, `PaletteSet` | Command decoding, GUI-required (BIN-008), risky APIs (BIN-007), URLs (BIN-006) |
| `FixtureNet48` | .NET Framework 4.8, x86 | Target framework (BIN-001) and architecture (BIN-003) |
