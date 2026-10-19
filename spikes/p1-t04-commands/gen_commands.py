"""Spike P1-T04: build the built-in command list for AutoCAD 2026 and test command-name collisions.

1. Collect candidate command names from acad.pgp (alias targets) and acad.CUIX (menu macros).
2. Verify every candidate inside AcCoreConsole with (getcname) -> data/commands-2026.txt
3. Collision experiment: load a plugin that defines LINE and see which LINE runs.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

ACAD = Path(r"C:\Program Files\Autodesk\AutoCAD 2026")
CORE = ACAD / "accoreconsole.exe"
CUIX = ACAD / r"UserDataCache\en-us\Support\acad.CUIX"
HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"
DATA = HERE / "data"
PLUGIN = HERE / "out" / "CollisionPlugin" / "CollisionPlugin.dll"
PGP = HERE.parent / "p1-t03-accoreconsole" / "runs" / "a_basic" / "profile" / "Roaming" / "Support" / "acad.pgp"

TOKEN = re.compile(r"^[A-Z0-9][A-Z0-9_\-]{1,40}$")


def candidates() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}

    def add(name: str, source: str) -> None:
        n = name.strip().lstrip("_.'+-").upper()
        if TOKEN.match(n):
            found.setdefault(n, set()).add(source)

    # acad.pgp:  ALIAS,   *COMMAND
    for line in PGP.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^\s*([^;,\s]+)\s*,\s*\*(\S+)", line)
        if m:
            add(m.group(2), "pgp")

    # acad.CUIX: menu macros such as ^C^C_line or ^C^C._-insert
    with zipfile.ZipFile(CUIX) as z:
        for n in z.namelist():
            if not n.endswith(".cui"):
                continue
            text = z.read(n).decode("utf-8", errors="replace")
            for macro in re.findall(r"<Command>(.*?)</Command>", text, flags=re.S):
                for part in re.split(r"\^C|;|\s|\\", macro):
                    if part.startswith(("_", ".", "'", "-")) or part.isalpha():
                        add(part, "cuix")
    return found


def run_core(name: str, lines: list[str], timeout: int = 300) -> tuple[int, str, Path]:
    run_dir = RUNS / name
    shutil.rmtree(run_dir, ignore_errors=True)
    (run_dir / "profile").mkdir(parents=True)
    script = run_dir / "script.scr"
    script.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))  # LF only (ADR-0003 F3)
    cmd = [str(CORE), "/s", str(script), "/product", "ACAD", "/l", "en-US",
           "/isolate", f"spike_{name}", str(run_dir / "profile")]
    env = dict(__import__("os").environ, SPIKE_RUN_DIR=str(run_dir))
    p = subprocess.run(cmd, cwd=run_dir, env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)
    text = p.stdout.decode("utf-16-le", errors="replace")
    (run_dir / "console.log").write_text(text, encoding="utf-8")
    return p.returncode, text, run_dir


def lisp_path(p: Path) -> str:
    return str(p).replace("\\", "/")


def verify(found: dict[str, set[str]]) -> list[dict]:
    DATA.mkdir(exist_ok=True)
    cand_file = DATA / "candidates.txt"
    cand_file.write_text("\n".join(sorted(found)) + "\n", encoding="utf-8")
    out_file = DATA / "verified.tsv"
    out_file.unlink(missing_ok=True)
    lisp = (f'(progn (setq in (open "{lisp_path(cand_file)}" "r") out (open "{lisp_path(out_file)}" "w")) '
            '(while (setq l (read-line in)) (if (setq g (getcname l)) (write-line (strcat l "\\t" g) out))) '
            '(close in) (close out) (princ))')
    t = time.monotonic()
    code, _, _ = run_core("verify", [lisp, "QUIT", "Y"])
    print(f"verify: exit={code} in {time.monotonic() - t:.1f}s")
    rows = []
    for line in out_file.read_text(encoding="utf-8").splitlines():
        cand, glob = line.split("\t")
        rows.append({"name": cand, "global": glob.lstrip("_"), "sources": sorted(found[cand])})
    return rows


def collision() -> dict:
    lines = [
        f'(setvar "TRUSTEDPATHS" "{lisp_path(PLUGIN.parent)}")',
        '(princ (strcat "\\nBEFORE=" (vl-princ-to-string (getcname "LINE"))))',
        "NETLOAD", str(PLUGIN),
        '(princ (strcat "\\nAFTER=" (vl-princ-to-string (getcname "LINE"))))',
        "LINE", "0,0", "10,10", "(command)",
        "_.LINE", "0,0", "5,5", "(command)",
        "SPK_LISTAPI",
        "QUIT", "Y",
    ]
    code, text, run_dir = run_core("collision", lines, timeout=120)
    tail = text[text.find("menu utilities"):] if "menu utilities" in text else text
    return {"exit": code, "console": tail, "apis": (run_dir / "command-apis.txt").read_text(encoding="utf-8")
            if (run_dir / "command-apis.txt").exists() else None}


def main() -> None:
    found = candidates()
    print(f"candidates: {len(found)} (pgp={sum('pgp' in s for s in found.values())}, "
          f"cuix={sum('cuix' in s for s in found.values())})")
    rows = verify(found)
    verified = {r["global"] for r in rows}
    # getcname only knows commands registered in the core console; demand-loaded and GUI-only
    # commands (ALIGN, APPLOAD, ...) are missing, so pgp alias targets are added as trusted names.
    pgp_targets = {n for n, s in found.items() if "pgp" in s}
    names = sorted(verified | pgp_targets)
    header = ["# AutoCAD 2026 (R25.1) built-in command global names",
              "# Generated by spikes/p1-t04-commands/gen_commands.py:",
              "#   (getcname)-verified names from acad.pgp + acad.CUIX candidates  UNION  all acad.pgp alias targets",
              "# Environment note: generated on a machine where Civil 3D object-enabler modules load (ADR-0003 F17)"]
    (DATA / "commands-2026.txt").write_text("\n".join(header + names) + "\n", encoding="utf-8")
    (DATA / "commands-2026.json").write_text(json.dumps(
        [{"name": n, "verified_in_core_console": n in verified, "in_pgp": n in pgp_targets} for n in names],
        indent=1), encoding="utf-8")
    print(f"verified in core console: {len(verified)}; pgp targets: {len(pgp_targets)}; "
          f"final list: {len(names)} (of {len(found)} candidates)")

    c = collision()
    (DATA / "collision.json").write_text(json.dumps(c, indent=1), encoding="utf-8")
    print(f"collision run exit={c['exit']}")


if __name__ == "__main__":
    main()
