# ADR-0002: File-based NDJSON probe protocol

**Status:** Accepted (v0.1) · **Date:** 2026-10-19

## Context
Probes run inside host processes in very different contexts:
- a headless console (AcCoreConsole);
- full GUI hosts;
- standalone Python interpreters;
- isolated VMs with no guest networking.

The orchestrator must receive events reliably, even when the host crashes mid-run.

## Options
1. Named pipes / sockets: live streaming. However, they are fragile on crash, need a listener in the sandbox, and are harder in Phase 1.
2. **Append-only NDJSON file + JSON plan file.** Simple, crash-tolerant (everything flushed survives), language-agnostic, and easy to replay in unit tests.
3. ETW custom provider: high performance, but complex and Windows / .NET only.

## Decision
Option 2. Events are flushed after every write. The `seq` field detects gaps, and a missing `probe.shutdown` event indicates an abnormal end. Phase 2 adds a per-event HMAC (key injected per Run) for tamper evidence.

## Consequences
- No live streaming in Phase 1. Phase 2 mta-agent may tail the file to stream progress to the dashboard.
- Recorded event files double as unit-test fixtures for the check engine.
