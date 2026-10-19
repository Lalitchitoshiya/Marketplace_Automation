"""MSI reading and administrative extraction (P1-R04, PKG-003; design.md §2.1).

Tables are read through `msi.dll` in read-only mode, which never runs anything. `msiexec /a` is only started
when no code-executing custom action is scheduled in the admin sequences: otherwise publisher code would run
outside a sandbox.
"""

import ctypes
import subprocess
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path

_ERROR_SUCCESS = 0
_ERROR_MORE_DATA = 234
_ERROR_NO_MORE_ITEMS = 259
_MSICONDITION_TRUE = 1
_MSIDBOPEN_READONLY = 0

MSIHANDLE = wintypes.ULONG

SEQUENCE_TABLES = (
    "InstallExecuteSequence",
    "InstallUISequence",
    "AdminExecuteSequence",
    "AdminUISequence",
    "AdvtExecuteSequence",
)
ADMIN_SEQUENCES = frozenset({"AdminExecuteSequence", "AdminUISequence"})
_PROPERTIES = ("ProductName", "ProductVersion", "Manufacturer", "ProductCode", "UpgradeCode", "ALLUSERS")

# Custom action base type = Type & 7 (Windows Installer "Summary List of All Custom Action Types").
_BASE_KINDS = {1: "dll", 2: "exe", 3: "data", 5: "jscript", 6: "vbscript", 7: "nested_install"}
_CODE_KINDS = frozenset({"dll", "exe", "jscript", "vbscript", "nested_install"})
_TARGET_MAX = 200

# msiexec exit codes that are MTA / environment problems, never the publisher's (Constitution §3).
ENVIRONMENT_EXIT_CODES = {1618: "another installation is in progress", 1625: "blocked by system policy"}
SUCCESS_EXIT_CODES = frozenset({0, 3010})


class MsiError(Exception):
    """The file cannot be read as an MSI database."""


@dataclass(frozen=True)
class CustomAction:
    name: str
    type: int
    kind: str  # dll / exe / data / jscript / vbscript / nested_install / unknown
    source: str | None
    target: str | None  # truncated: inline scripts can be long
    sequences: list[str] = field(default_factory=list)

    @property
    def executes_code(self) -> bool:
        return self.kind in _CODE_KINDS or self.kind == "unknown"

    @property
    def runs_in_admin_install(self) -> bool:
        return self.executes_code and bool(ADMIN_SEQUENCES.intersection(self.sequences))


@dataclass(frozen=True)
class MsiTables:
    properties: dict[str, str]
    custom_actions: list[CustomAction]
    file_count: int
    declared_bytes: int  # sum of File.FileSize

    @property
    def admin_code_actions(self) -> list[CustomAction]:
        return [a for a in self.custom_actions if a.runs_in_admin_install]


def _msi() -> ctypes.WinDLL:
    lib = ctypes.WinDLL("msi")
    lib.MsiOpenDatabaseW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(MSIHANDLE)]
    lib.MsiDatabaseOpenViewW.argtypes = [MSIHANDLE, wintypes.LPCWSTR, ctypes.POINTER(MSIHANDLE)]
    lib.MsiDatabaseIsTablePersistentW.argtypes = [MSIHANDLE, wintypes.LPCWSTR]
    lib.MsiViewExecute.argtypes = [MSIHANDLE, MSIHANDLE]
    lib.MsiViewFetch.argtypes = [MSIHANDLE, ctypes.POINTER(MSIHANDLE)]
    lib.MsiRecordGetFieldCount.argtypes = [MSIHANDLE]
    lib.MsiRecordIsNull.argtypes = [MSIHANDLE, wintypes.UINT]
    lib.MsiRecordGetStringW.argtypes = [
        MSIHANDLE,
        wintypes.UINT,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    lib.MsiCloseHandle.argtypes = [MSIHANDLE]
    return lib


def _record_string(lib: ctypes.WinDLL, record: int, index: int) -> str | None:
    if lib.MsiRecordIsNull(record, index):
        return None
    size = wintypes.DWORD(256)
    while True:
        buffer = ctypes.create_unicode_buffer(size.value + 1)
        size.value += 1
        code = lib.MsiRecordGetStringW(record, index, buffer, ctypes.byref(size))
        if code == _ERROR_SUCCESS:
            return buffer.value
        if code != _ERROR_MORE_DATA:
            raise MsiError(f"MsiRecordGetString failed ({code})")


def query(lib: ctypes.WinDLL, db: int, sql: str) -> list[list[str | None]]:
    view = MSIHANDLE()
    if lib.MsiDatabaseOpenViewW(db, sql, ctypes.byref(view)) != _ERROR_SUCCESS:
        raise MsiError(f"cannot query: {sql}")
    rows: list[list[str | None]] = []
    try:
        if lib.MsiViewExecute(view, 0) != _ERROR_SUCCESS:
            raise MsiError(f"cannot execute: {sql}")
        while True:
            record = MSIHANDLE()
            code = lib.MsiViewFetch(view, ctypes.byref(record))
            if code == _ERROR_NO_MORE_ITEMS:
                return rows
            if code != _ERROR_SUCCESS:
                raise MsiError(f"fetch failed ({code}): {sql}")
            try:
                count = lib.MsiRecordGetFieldCount(record)
                rows.append([_record_string(lib, record.value, i) for i in range(1, count + 1)])
            finally:
                lib.MsiCloseHandle(record)
    finally:
        lib.MsiCloseHandle(view)


def _has_table(lib: ctypes.WinDLL, db: int, table: str) -> bool:
    return bool(lib.MsiDatabaseIsTablePersistentW(db, table) == _MSICONDITION_TRUE)


def _action_kind(action_type: int) -> str:
    return _BASE_KINDS.get(action_type & 7, "unknown")


def msi_read_tables(path: Path) -> MsiTables:
    """Read the tables MTA needs. Read-only: nothing in the package is executed."""
    lib = _msi()
    db = MSIHANDLE()
    code = lib.MsiOpenDatabaseW(str(path), ctypes.c_void_p(_MSIDBOPEN_READONLY), ctypes.byref(db))
    if code != _ERROR_SUCCESS:
        raise MsiError(f"{path.name}: not a readable MSI database (error {code})")
    try:
        properties: dict[str, str] = {}
        if _has_table(lib, db.value, "Property"):
            for name, value in query(lib, db.value, "SELECT `Property`, `Value` FROM `Property`"):
                if name in _PROPERTIES and value is not None:
                    properties[name] = value

        scheduled: dict[str, list[str]] = {}
        for table in SEQUENCE_TABLES:
            if _has_table(lib, db.value, table):
                for (action,) in query(lib, db.value, f"SELECT `Action` FROM `{table}`"):  # noqa: S608 (constant names)
                    if action is not None:
                        scheduled.setdefault(action, []).append(table)

        actions: list[CustomAction] = []
        if _has_table(lib, db.value, "CustomAction"):
            sql = "SELECT `Action`, `Type`, `Source`, `Target` FROM `CustomAction`"
            for name, type_text, source, target in query(lib, db.value, sql):
                action_type = int(type_text or 0)
                actions.append(
                    CustomAction(
                        name=name or "",
                        type=action_type,
                        kind=_action_kind(action_type),
                        source=source,
                        target=target[:_TARGET_MAX] if target else target,
                        sequences=scheduled.get(name or "", []),
                    )
                )

        file_count, declared = 0, 0
        if _has_table(lib, db.value, "File"):
            for (size,) in query(lib, db.value, "SELECT `FileSize` FROM `File`"):
                file_count += 1
                declared += int(size or 0)
        return MsiTables(properties, actions, file_count, declared)
    finally:
        lib.MsiCloseHandle(db)


@dataclass(frozen=True)
class AdminExtractResult:
    exit_code: int | None  # None = timed out
    log_tail: str

    @property
    def succeeded(self) -> bool:
        return self.exit_code in SUCCESS_EXIT_CODES

    @property
    def environment_problem(self) -> str | None:
        if self.exit_code is None:
            return "msiexec timed out"
        return ENVIRONMENT_EXIT_CODES.get(self.exit_code)


def _read_log(log: Path, lines: int = 25) -> str:
    if not log.is_file():
        return "(no msiexec log)"
    raw = log.read_bytes()
    text = raw.decode("utf-16", errors="replace") if raw[:2] == b"\xff\xfe" else raw.decode(errors="replace")
    return "\n".join(text.strip().splitlines()[-lines:])


def msi_admin_extract(msi: Path, dest: Path, log: Path, timeout_s: int) -> AdminExtractResult:
    """`msiexec /a` into an empty `dest`. The caller must check `MsiTables.admin_code_actions` first."""
    dest.mkdir(parents=True, exist_ok=False)
    # A string, not a list: msiexec needs PROPERTY="value" quoting, which list2cmdline does not produce.
    command = f'msiexec /a "{msi.resolve()}" /qn TARGETDIR="{dest.resolve()}" /L*v "{log.resolve()}"'
    try:
        done = subprocess.run(command, capture_output=True, timeout=timeout_s, check=False)  # noqa: S603
    except subprocess.TimeoutExpired:
        return AdminExtractResult(None, _read_log(log))
    # The admin image contains a rewritten copy of the MSI; it is not payload.
    (dest / msi.name).unlink(missing_ok=True)
    return AdminExtractResult(done.returncode, _read_log(log))
