# ADR-0001: Python orchestrator, C# probes, metadata-only .NET inspection

**Status:** Accepted (v0.1) · **Date:** 2026-10-19

## Context
MTA needs:
- an orchestrator (CLI, service, check engine, reports, AI integration);
- in-process probes for .NET-based Autodesk hosts (AutoCAD, Revit, Inventor, Navisworks, Vault) and Python-based hosts (Fusion, 3ds Max, Maya);
- static inspection of .NET assemblies without executing them.

## Decision
- **Orchestrator in Python 3.12.** Python has a strong ecosystem for the work involved:
  - process control (`psutil`);
  - PE parsing (`pefile`);
  - EVTX parsing;
  - Jinja2 reports;
  - FastAPI;
  - LLM SDKs;
  - Playwright (for the future web-app adapter).
  
  It is also fast to iterate on.
- **Probes in C#** for .NET hosts. A probe must run inside the host's CLR, and `Mta.Probe.Core` is multi-targeted for `net48` and `net8.0-windows`. Probes for Python hosts are written in Python.
- **mta-inspect in C# (.NET 8)** using `System.Reflection.Metadata`. This is metadata-only reading: custom attributes and type references are decoded without loading the assembly. It never calls `Assembly.Load`.

## Consequences
- The team needs Python and C# skills.
- One build pipeline produces both Python wheels and .NET artifacts.
- mta-inspect output is a stable JSON contract between the languages, with versioned schemas.
