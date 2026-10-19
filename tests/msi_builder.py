"""Build small but real MSI packages for tests, with only Windows built-ins (msi.dll + makecab).

The payload is compressed into an embedded cabinet, like real Marketplace MSIs, so `msiexec /a` has to
really extract it. Custom actions can be added to test the inventory and the admin-sequence guard; they
are never run.
"""

import ctypes
import subprocess
import uuid
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

MSIHANDLE = wintypes.ULONG
_MSIDBOPEN_CREATE = 3
_MSIMODIFY_INSERT = 1
_VT_I4, _VT_LPSTR = 3, 30
_PID_TEMPLATE, _PID_REVNUMBER, _PID_PAGECOUNT, _PID_WORDCOUNT = 7, 9, 14, 15

_STANDARD_ADMIN = [
    ("CostInitialize", 800),
    ("FileCost", 900),
    ("CostFinalize", 1000),
    ("InstallValidate", 1400),
    ("InstallInitialize", 1500),
    ("InstallAdminPackage", 3900),
    ("InstallFiles", 4000),
    ("InstallFinalize", 6600),
]


@dataclass(frozen=True)
class Action:
    name: str
    type: int
    source: str | None
    target: str | None
    sequence: str  # e.g. "InstallExecuteSequence" or "AdminExecuteSequence"


def _guid() -> str:
    return "{" + str(uuid.uuid4()).upper() + "}"


def _lib() -> ctypes.WinDLL:
    lib = ctypes.WinDLL("msi")
    lib.MsiOpenDatabaseW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(MSIHANDLE)]
    lib.MsiDatabaseImportW.argtypes = [MSIHANDLE, wintypes.LPCWSTR, wintypes.LPCWSTR]
    lib.MsiDatabaseOpenViewW.argtypes = [MSIHANDLE, wintypes.LPCWSTR, ctypes.POINTER(MSIHANDLE)]
    lib.MsiViewExecute.argtypes = [MSIHANDLE, MSIHANDLE]
    lib.MsiViewModify.argtypes = [MSIHANDLE, ctypes.c_int, MSIHANDLE]
    lib.MsiCreateRecord.argtypes = [wintypes.UINT]
    lib.MsiCreateRecord.restype = MSIHANDLE
    lib.MsiRecordSetStringW.argtypes = [MSIHANDLE, wintypes.UINT, wintypes.LPCWSTR]
    lib.MsiRecordSetStreamW.argtypes = [MSIHANDLE, wintypes.UINT, wintypes.LPCWSTR]
    lib.MsiGetSummaryInformationW.argtypes = [
        MSIHANDLE,
        wintypes.LPCWSTR,
        wintypes.UINT,
        ctypes.POINTER(MSIHANDLE),
    ]
    lib.MsiSummaryInfoSetPropertyW.argtypes = [
        MSIHANDLE,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.LPCWSTR,
    ]
    lib.MsiSummaryInfoPersist.argtypes = [MSIHANDLE]
    lib.MsiDatabaseCommit.argtypes = [MSIHANDLE]
    lib.MsiCloseHandle.argtypes = [MSIHANDLE]
    return lib


def _ok(code: int, what: str) -> None:
    if code != 0:
        raise RuntimeError(f"{what} failed with {code}")


def _idt(
    folder: Path, table: str, columns: str, types: str, keys: str, rows: list[tuple[object, ...]]
) -> str:
    lines = [columns, types, f"{table}\t{keys}"]
    lines += ["\t".join("" if v is None else str(v) for v in row) for row in rows]
    name = f"{table}.idt"
    (folder / name).write_text("\r\n".join(lines) + "\r\n", encoding="ascii")
    return name


def build_msi(out: Path, files: dict[str, bytes], work: Path, actions: tuple[Action, ...] = ()) -> Path:
    """`files` maps payload-relative paths ("X.bundle/Contents/X.dll") to their content."""
    work.mkdir(parents=True, exist_ok=True)
    src = work / "src"
    src.mkdir(exist_ok=True)

    directories: dict[str, str] = {"": "TARGETDIR"}
    dir_rows: list[tuple[object, ...]] = [("TARGETDIR", None, "SourceDir")]
    components: dict[str, str] = {}
    comp_rows: list[tuple[object, ...]] = []
    file_rows: list[tuple[object, ...]] = []
    ddf = [
        ".OPTION EXPLICIT",
        ".Set CabinetNameTemplate=payload.cab",
        f".Set DiskDirectoryTemplate={work}",
        ".Set Cabinet=on",
        ".Set Compress=on",
        ".Set MaxDiskSize=0",
    ]
    for seq, (rel, content) in enumerate(sorted(files.items()), start=1):
        path = PurePosixPath(rel)
        parent = ""
        for part in path.parent.parts:  # create every directory level once
            key = f"{parent}/{part}" if parent else part
            if key not in directories:
                directories[key] = f"D{len(directories)}"
                dir_rows.append((directories[key], directories[parent], f"D{len(directories):07d}|{part}"))
            parent = key
        directory = directories[str(path.parent) if str(path.parent) != "." else ""]
        file_key = f"F{seq}"
        if directory not in components:
            components[directory] = f"C{len(components) + 1}"
            comp_rows.append((components[directory], _guid(), directory, 0, None, file_key))
        (src / file_key).write_bytes(content)
        file_rows.append(
            (file_key, components[directory], f"F{seq:07d}|{path.name}", len(content), None, None, 0, seq)
        )
        ddf.append(f'"{src / file_key}" "{file_key}"')
    (work / "payload.ddf").write_text("\r\n".join(ddf) + "\r\n", encoding="ascii")
    subprocess.run(  # noqa: S603
        ["makecab", "/f", str(work / "payload.ddf")],  # noqa: S607
        cwd=work,
        capture_output=True,
        check=True,
    )

    idts = work / "idt"
    idts.mkdir(exist_ok=True)
    sequences: dict[str, list[tuple[object, ...]]] = {
        "AdminExecuteSequence": [(a, None, s) for a, s in _STANDARD_ADMIN]
    }
    for i, action in enumerate(actions):
        sequences.setdefault(action.sequence, []).append((action.name, None, 5000 + i))
    tables = [
        _idt(
            idts,
            "Property",
            "Property\tValue",
            "s72\tl0",
            "Property",
            [
                ("ProductCode", _guid()),
                ("UpgradeCode", _guid()),
                ("ProductName", out.stem),
                ("ProductVersion", "1.0.0"),
                ("Manufacturer", "MTA synthetic"),
                ("ProductLanguage", 1033),
            ],
        ),
        _idt(
            idts,
            "Directory",
            "Directory\tDirectory_Parent\tDefaultDir",
            "s72\tS72\tl255",
            "Directory",
            dir_rows,
        ),
        _idt(
            idts,
            "Component",
            "Component\tComponentId\tDirectory_\tAttributes\tCondition\tKeyPath",
            "s72\tS38\ts72\ti2\tS255\tS72",
            "Component",
            comp_rows,
        ),
        _idt(
            idts,
            "Feature",
            "Feature\tFeature_Parent\tTitle\tDescription\tDisplay\tLevel\tDirectory_\tAttributes",
            "s38\tS38\tL64\tL255\tI2\ti2\tS72\ti2",
            "Feature",
            [("Main", None, "Main", None, 1, 1, None, 0)],
        ),
        _idt(
            idts,
            "FeatureComponents",
            "Feature_\tComponent_",
            "s38\ts72",
            "Feature_\tComponent_",
            [("Main", c) for c in components.values()],
        ),
        _idt(
            idts,
            "File",
            "File\tComponent_\tFileName\tFileSize\tVersion\tLanguage\tAttributes\tSequence",
            "s72\ts72\tl255\ti4\tS72\tS20\tI2\ti2",
            "File",
            file_rows,
        ),
        _idt(
            idts,
            "Media",
            "DiskId\tLastSequence\tDiskPrompt\tCabinet\tVolumeLabel\tSource",
            "i2\ti2\tL64\tS255\tS32\tS72",
            "DiskId",
            [(1, len(files), None, "#payload.cab", None, None)],
        ),
    ]
    tables += [
        _idt(idts, name, "Action\tCondition\tSequence", "s72\tS255\tI2", "Action", rows)
        for name, rows in sequences.items()
    ]
    if actions:
        tables.append(
            _idt(
                idts,
                "CustomAction",
                "Action\tType\tSource\tTarget",
                "s72\ti2\tS72\tS255",
                "Action",
                [(a.name, a.type, a.source, a.target) for a in actions],
            )
        )

    lib = _lib()
    db = MSIHANDLE()
    out.unlink(missing_ok=True)
    _ok(
        lib.MsiOpenDatabaseW(str(out), ctypes.c_void_p(_MSIDBOPEN_CREATE), ctypes.byref(db)),
        "create database",
    )
    try:
        for table in tables:
            _ok(lib.MsiDatabaseImportW(db, str(idts), table), f"import {table}")
        view = MSIHANDLE()
        _ok(lib.MsiDatabaseOpenViewW(db, "SELECT `Name`, `Data` FROM `_Streams`", ctypes.byref(view)), "view")
        _ok(lib.MsiViewExecute(view, 0), "execute")
        record = lib.MsiCreateRecord(2)
        _ok(lib.MsiRecordSetStringW(record, 1, "payload.cab"), "stream name")
        _ok(lib.MsiRecordSetStreamW(record, 2, str(work / "payload.cab")), "stream data")
        _ok(lib.MsiViewModify(view, _MSIMODIFY_INSERT, record), "insert cabinet")
        lib.MsiCloseHandle(record)
        lib.MsiCloseHandle(view)

        summary = MSIHANDLE()
        _ok(lib.MsiGetSummaryInformationW(db, None, 10, ctypes.byref(summary)), "summary")
        _ok(
            lib.MsiSummaryInfoSetPropertyW(summary, _PID_TEMPLATE, _VT_LPSTR, 0, None, "Intel;1033"),
            "template",
        )
        _ok(
            lib.MsiSummaryInfoSetPropertyW(summary, _PID_REVNUMBER, _VT_LPSTR, 0, None, _guid()),
            "package code",
        )
        _ok(lib.MsiSummaryInfoSetPropertyW(summary, _PID_PAGECOUNT, _VT_I4, 200, None, None), "schema")
        _ok(lib.MsiSummaryInfoSetPropertyW(summary, _PID_WORDCOUNT, _VT_I4, 2, None, None), "word count")
        _ok(lib.MsiSummaryInfoPersist(summary), "persist summary")
        lib.MsiCloseHandle(summary)
        _ok(lib.MsiDatabaseCommit(db), "commit")
    finally:
        lib.MsiCloseHandle(db)
    return out
