"""Spike P1-T03 runner: executes AcCoreConsole experiments and records what happens.

Usage:  python run_spike.py [experiment ...]      (no args = all)
Results: runs/<experiment>/{script.scr, console.log, spike-events.ndjson, result.json}
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ACAD = Path(r"C:\Program Files\Autodesk\AutoCAD 2026")
CORE = ACAD / "accoreconsole.exe"
HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
RUNS = HERE / "runs"
PLUGIN = OUT / "SpikePlugin" / "SpikePlugin.dll"
UI_PLUGIN = OUT / "SpikeUiPlugin" / "SpikeUiPlugin.dll"

QUIT = ["QUIT", "Y"]


def netload(dll: Path) -> list[str]:
    return ["NETLOAD", str(dll)]


# name -> (script lines, timeout seconds, extra args, extra env, notes)
EXPERIMENTS: dict[str, dict] = {
    "a_basic": dict(
        lines=["SECURELOAD 0", *netload(PLUGIN), "SPK_HELLO", "SPK_PROBEAPI",
               '(princ (strcat "\\nGETCNAME_HELLO=" (vl-princ-to-string (getcname "SPK_HELLO"))))',
               '(princ (strcat "\\nGETCNAME_LINE=" (vl-princ-to-string (getcname "LINE"))))',
               '(princ (strcat "\\nGETCNAME_FAKE=" (vl-princ-to-string (getcname "NOT_A_REAL_CMD"))))',
               "NOT_A_REAL_CMD", *QUIT],
        timeout=120, notes="load, run, command lookup, unknown command, quit"),
    "b_throw": dict(
        lines=["SECURELOAD 0", *netload(PLUGIN), "SPK_THROW", "SPK_HELLO", *QUIT],
        timeout=120, notes="exception in command; does the session continue?"),
    "c_prompt_eof": dict(
        lines=["SECURELOAD 0", *netload(PLUGIN), "SPK_PROMPT"],
        timeout=60, notes="script ends while a prompt is active, stdin closed"),
    "d_prompt_enter": dict(
        lines=["SECURELOAD 0", *netload(PLUGIN), "SPK_PROMPT", "", "SPK_SELECT", "", "", "SPK_HELLO", *QUIT],
        timeout=120, notes="blank lines as Enter at string and selection prompts"),
    "e_hang": dict(
        lines=["SECURELOAD 0", *netload(PLUGIN), "SPK_HANG", *QUIT],
        timeout=45, notes="command hangs; watchdog must kill"),
    "f_crash": dict(
        lines=["SECURELOAD 0", *netload(PLUGIN), "SPK_CRASH", *QUIT],
        timeout=120, notes="Environment.FailFast inside command"),
    "g_secureload_default": dict(
        lines=[*netload(PLUGIN), "SPK_HELLO", *QUIT],
        timeout=60, notes="SECURELOAD left at default with plugin in untrusted folder"),
    "h_trustedpaths": dict(
        lines=[f'(setvar "TRUSTEDPATHS" "{str(PLUGIN.parent).replace(chr(92), "/")}")',
               '(princ (strcat "\\nTRUSTED=" (getvar "TRUSTEDPATHS")))',
               '(princ (strcat "\\nSECURELOAD=" (itoa (getvar "SECURELOAD"))))',
               *netload(PLUGIN), "SPK_HELLO", *QUIT],
        timeout=60, notes="TRUSTEDPATHS set from script, SECURELOAD default"),
    "i_ui_plugin": dict(
        lines=["SECURELOAD 0", *netload(UI_PLUGIN), "SPKUI_ALERT", *QUIT],
        timeout=90, notes="plugin referencing AcMgd (UI) in core console"),
    "j_loadmodule": dict(
        lines=["SPK_HELLO", *QUIT],
        timeout=90, args=["/loadmodule", str(PLUGIN)],
        notes="/loadmodule switch with a .NET assembly"),
    "l_lisp_cancel": dict(
        lines=["SECURELOAD 0", *netload(PLUGIN), "SPK_PROMPT", "(command)", "SPK_SELECT", "(command)",
               "SPK_HELLO", *QUIT],
        timeout=60, notes="(command) typed at an active prompt: does it cancel like ESC?"),
    "m_lisp_invoke_cancel": dict(
        lines=["SECURELOAD 0", *netload(PLUGIN), '(command "SPK_PROMPT")', "(command)",
               '(command "SPK_SELECT")', "(command)", "SPK_HELLO", *QUIT],
        timeout=60, notes="start command via (command \"X\") then cancel with (command)"),
    "n_init_throw": dict(
        lines=["SECURELOAD 0", *netload(PLUGIN), "SPK_HELLO", *QUIT],
        timeout=60, env={"SPIKE_THROW_INIT": "1"}, notes="exception inside IExtensionApplication.Initialize"),
    "o_throw_then_marker": dict(
        lines=["SECURELOAD 0", *netload(PLUGIN), "SPK_THROW"],
        timeout=60, notes="repeat of b to confirm exception => process crash is deterministic"),
    "k_autoload_bundle": dict(
        lines=['(princ (strcat "\\nAPPAUTOLOAD=" (itoa (getvar "APPAUTOLOAD"))))', "SPK_HELLO", *QUIT],
        timeout=120, bundle=True,
        notes="bundle in %APPDATA%\\Autodesk\\ApplicationPlugins with APPDATA redirected to the run folder"),
}

PACKAGE_CONTENTS = """<?xml version="1.0" encoding="utf-8"?>
<ApplicationPackage SchemaVersion="1.0" AutodeskProduct="AutoCAD" ProductType="Application"
  Name="SpikeBundle" AppVersion="1.0.0" ProductCode="{6B1B5E2A-3C1D-4E0B-9F3A-0A1B2C3D4E5F}"
  UpgradeCode="{7C2C6F3B-4D2E-4F1C-8A4B-1B2C3D4E5F60}">
  <CompanyDetails Name="Spike" />
  <RuntimeRequirements OS="Win64" Platform="AutoCAD*" SeriesMin="R25.0" SeriesMax="R25.9" />
  <Components>
    <ComponentEntry AppName="SpikePlugin" ModuleName="./Contents/SpikePlugin.dll" LoadOnAutoCADStartup="True" />
  </Components>
</ApplicationPackage>
"""


def make_bundle(appdata: Path) -> None:
    bundle = appdata / "Autodesk" / "ApplicationPlugins" / "SpikeBundle.bundle"
    (bundle / "Contents").mkdir(parents=True, exist_ok=True)
    (bundle / "PackageContents.xml").write_text(PACKAGE_CONTENTS, encoding="utf-8")
    shutil.copy2(PLUGIN, bundle / "Contents" / "SpikePlugin.dll")


def run(name: str, exp: dict) -> dict:
    run_dir = RUNS / name
    shutil.rmtree(run_dir, ignore_errors=True)
    (run_dir / "profile").mkdir(parents=True)
    script = run_dir / "script.scr"
    # LF only: with CRLF, CR and LF each act as Enter and repeat the previous command.
    script.write_bytes(("\n".join(exp["lines"]) + "\n").encode("utf-8"))

    env = dict(os.environ, SPIKE_RUN_DIR=str(run_dir), **exp.get("env", {}))
    if exp.get("bundle"):
        appdata = run_dir / "appdata"
        make_bundle(appdata)
        env["APPDATA"] = str(appdata)

    cmd = [str(CORE), "/s", str(script), "/product", "ACAD", "/l", "en-US",
           "/isolate", f"spike_{name}", str(run_dir / "profile"), *exp.get("args", [])]

    start = time.monotonic()
    proc = subprocess.Popen(cmd, cwd=run_dir, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    killed = False
    try:
        raw, _ = proc.communicate(timeout=exp["timeout"])
    except subprocess.TimeoutExpired:
        killed = True
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        raw, _ = proc.communicate()
    elapsed = round(time.monotonic() - start, 1)

    text = raw.decode("utf-16-le", errors="replace")
    (run_dir / "console.log").write_text(text, encoding="utf-8")

    events_file = run_dir / "spike-events.ndjson"
    events = [json.loads(l) for l in events_file.read_text(encoding="utf-8").splitlines() if l.strip()] \
        if events_file.exists() else []
    ui_file = run_dir / "spike-ui.txt"

    result = dict(
        experiment=name, notes=exp["notes"], exit_code=proc.returncode,
        exit_code_hex=f"0x{proc.returncode & 0xFFFFFFFF:08X}" if proc.returncode is not None else None,
        killed_by_watchdog=killed, seconds=elapsed,
        event_types=[e["type"] for e in events],
        ui_file=ui_file.read_text(encoding="utf-8") if ui_file.exists() else None,
        console_tail=text.strip().splitlines()[-25:],
    )
    (run_dir / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> None:
    names = sys.argv[1:] or list(EXPERIMENTS)
    for n in names:
        r = run(n, EXPERIMENTS[n])
        print(f"== {n}: exit={r['exit_code']} ({r['exit_code_hex']}) killed={r['killed_by_watchdog']} "
              f"t={r['seconds']}s events={r['event_types']}")


if __name__ == "__main__":
    main()
