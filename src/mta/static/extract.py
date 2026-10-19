"""Safe package extraction and checks PKG-001...003 (P1-R04; design.md §2.1).

Archives come from publishers and are treated as hostile: every name is validated and the declared sizes are
checked before anything is written; actual bytes are counted while writing; a rejected archive leaves nothing
behind.
"""

import os
import re
import shutil
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from mta.config import MtaConfig
from mta.config.models import ExtractThresholds
from mta.models import CheckResult, PackageKind, Status
from mta.static.msi import MsiError, MsiTables, msi_admin_extract, msi_read_tables
from mta.static.results import ResultSink, excerpt

_RESERVED = re.compile(r"^(con|prn|aux|nul|com[0-9¹²³]|lpt[0-9¹²³])(\..*)?$", re.IGNORECASE)
_S_IFMT, _S_IFLNK = 0o170000, 0o120000
_ARCHIVE_SUFFIXES = (".zip", ".msi", ".cab", ".7z", ".rar", ".nupkg", ".msix", ".appx")
_CHUNK = 1 << 20


class ExtractError(Exception):
    def __init__(self, problems: list[str]) -> None:
        super().__init__(f"{len(problems)} extraction problem(s): {problems[0]}")
        self.problems = problems


@dataclass(frozen=True)
class ZipExtraction:
    files: list[Path]
    total_bytes: int
    nested_archives: list[str]


def check_member_name(name: str) -> str | None:
    """Return why an archive member name is unsafe on Windows, or None if it is fine."""
    if "\0" in name:
        return "contains a NUL character"
    norm = name.replace("\\", "/")
    if norm.startswith("/"):
        return "absolute path"
    if ":" in norm:
        return "contains ':' (drive letter or alternate data stream)"
    for part in norm.rstrip("/").split("/"):
        if part in ("", "."):
            return "empty or '.' path component"
        if part == "..":
            return "path traversal ('..')"
        if part != part.rstrip(". "):
            return "component ends with a dot or space"
        if _RESERVED.match(part):
            return f"Windows reserved name '{part}'"
    return None


def _parts(name: str) -> list[str]:
    return name.replace("\\", "/").rstrip("/").split("/")


def _long(path: Path) -> str:
    """Absolute path that also works beyond MAX_PATH on Windows."""
    text = os.path.abspath(path)  # noqa: PTH100 (no symlink resolution wanted; string for \?\)
    return "\\\\?\\" + text if os.name == "nt" and not text.startswith("\\\\?\\") else text


def _plan_zip(infos: list[zipfile.ZipInfo], limits: ExtractThresholds) -> list[str]:
    """All problems that can be found from the central directory, before writing anything."""
    problems: list[str] = []
    files = [i for i in infos if not i.is_dir()]
    seen: dict[str, str] = {}
    dirs: set[str] = set()
    for info in infos:
        reason = check_member_name(info.filename)
        if reason:
            problems.append(f"{info.filename!r}: {reason}")
            continue
        if (info.external_attr >> 16) & _S_IFMT == _S_IFLNK:
            problems.append(f"{info.filename}: symbolic link entries are not allowed")
        if info.flag_bits & 0x1:
            problems.append(f"{info.filename}: encrypted entries cannot be scanned")
        parts = [p.casefold() for p in _parts(info.filename)]
        key = "/".join(parts)
        dirs.update("/".join(parts[:i]) for i in range(1, len(parts)))
        if info.is_dir():
            dirs.add(key)
        elif key in seen:
            problems.append(f"{info.filename}: duplicate of {seen[key]} (names are case-insensitive)")
        else:
            seen[key] = info.filename
        if (
            not info.is_dir()
            and info.file_size > limits.ratio_min_bytes
            and info.file_size > limits.max_compression_ratio * max(info.compress_size, 1)
        ):
            ratio = info.file_size // max(info.compress_size, 1)
            problems.append(f"{info.filename}: compression ratio {ratio}:1 suggests a zip bomb")
    problems.extend(f"{seen[k]}: a file and a folder have the same name" for k in seen.keys() & dirs)
    if len(files) > limits.max_files:
        problems.append(f"{len(files)} files exceed the limit of {limits.max_files}")
    declared = sum(i.file_size for i in files)
    if declared > limits.max_bytes:
        problems.append(f"declared size {declared} bytes exceeds the limit of {limits.max_bytes}")
    return problems


def safe_extract_zip(archive: Path, dest: Path, limits: ExtractThresholds) -> ZipExtraction:
    """Extract into a new folder `dest`, or raise ExtractError and leave nothing behind."""
    try:
        with zipfile.ZipFile(archive) as zf:
            infos = zf.infolist()
            problems = _plan_zip(infos, limits)
            if problems:
                raise ExtractError(problems)
            dest.mkdir(parents=True, exist_ok=False)
            return _write_members(zf, infos, dest, limits)
    except ExtractError:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    except (zipfile.BadZipFile, zlib.error, NotImplementedError, EOFError, OSError) as exc:
        shutil.rmtree(dest, ignore_errors=True)
        raise ExtractError([f"corrupt or unsupported archive: {exc}"]) from exc


def _write_members(
    zf: zipfile.ZipFile, infos: list[zipfile.ZipInfo], dest: Path, limits: ExtractThresholds
) -> ZipExtraction:
    root = os.path.abspath(dest) + os.sep  # noqa: PTH100
    files: list[Path] = []
    nested: list[str] = []
    total = 0
    for info in infos:
        target = dest.joinpath(*_parts(info.filename))
        if not os.path.abspath(target).startswith(root):  # noqa: PTH100 (defence in depth; names were validated)
            raise ExtractError([f"{info.filename}: resolves outside the extraction folder"])
        if info.is_dir():
            os.makedirs(_long(target), exist_ok=True)  # noqa: PTH103 (long path string)
            continue
        os.makedirs(_long(target.parent), exist_ok=True)  # noqa: PTH103
        written = 0
        with zf.open(info) as source, open(_long(target), "xb") as out:  # noqa: PTH123 (long path string)
            while chunk := source.read(_CHUNK):
                written += len(chunk)
                total += len(chunk)
                if written > info.file_size or total > limits.max_bytes:
                    raise ExtractError([f"{info.filename}: more data than declared (zip bomb)"])
                out.write(chunk)
        files.append(target)
        if info.filename.lower().endswith(_ARCHIVE_SUFFIXES):
            nested.append(info.filename)
    return ZipExtraction(files, total, nested)


# ---- PKG-001...003 ---------------------------------------------------------------------------------------


@dataclass
class PackageExtraction:
    payload_dir: Path | None  # None when no payload could be produced
    files: list[Path] = field(default_factory=list)
    results: list[CheckResult] = field(default_factory=list)
    msi: MsiTables | None = None
    nested_archives: list[str] = field(default_factory=list)


def _tree(root: Path) -> tuple[list[Path], list[str]]:
    """Files under root, and any links (which are never followed)."""
    files: list[Path] = []
    links: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        for name in [*dirnames, *filenames]:
            path = Path(dirpath, name)
            if path.is_symlink() or path.is_junction():
                links.append(path.relative_to(root).as_posix())
        dirnames[:] = [
            d for d in dirnames if not Path(dirpath, d).is_symlink() and not Path(dirpath, d).is_junction()
        ]
        files.extend(Path(dirpath, f) for f in filenames if not Path(dirpath, f).is_symlink())
    return sorted(files), links


def _check_tree(
    results: ResultSink, root: Path, files: list[Path], links: list[str], limits: ExtractThresholds
) -> bool:
    size = sum(f.stat().st_size for f in files)
    problems = [f"{link}: links are not allowed" for link in links]
    if len(files) > limits.max_files:
        problems.append(f"{len(files)} files exceed the limit of {limits.max_files}")
    if size > limits.max_bytes:
        problems.append(f"{size} bytes exceed the limit of {limits.max_bytes}")
    if problems:
        results.add("PKG-001", Status.FAIL, "Extracted payload breaks the safety limits", excerpt(problems))
        return False
    results.add("PKG-001", Status.PASS, f"Payload is safe: {len(files)} files, {size} bytes, no links")
    return True


def _check_payload(results: ResultSink, root: Path, files: list[Path], extensions: set[str]) -> None:
    bundles = sorted({p.relative_to(root).as_posix() for p in root.rglob("*.bundle") if p.is_dir()})
    deployable = [f.relative_to(root).as_posix() for f in files if f.suffix.lower() in extensions]
    if bundles or deployable:
        found = bundles + [d for d in deployable if not any(d.startswith(b + "/") for b in bundles)]
        results.add(
            "PKG-002", Status.PASS, f"Deployable payload found ({len(found)} item(s))", excerpt(found)
        )
        return
    listing = [f.relative_to(root).as_posix() for f in files] or ["(no files)"]
    results.add(
        "PKG-002",
        Status.FAIL,
        "No deployable payload: no *.bundle folder and no plugin files",
        excerpt(listing),
        fix="Package the plugin as an Autodesk .bundle (PackageContents.xml + Contents/) or include its "
        "DLL/ARX/LSP files.",
    )


def extract_package(
    package: Path, kind: PackageKind, dest: Path, cfg: MtaConfig, *, work_dir: Path
) -> PackageExtraction:
    """Produce the payload in `dest` (which must not exist) and the PKG-001...003 results."""
    limits = cfg.thresholds.extract
    extensions = {e.lower() for host in cfg.hosts.hosts.values() for e in host.payload_extensions}
    results = ResultSink(cfg)
    outcome = PackageExtraction(payload_dir=None)

    if kind is PackageKind.BUNDLE:
        dest.mkdir(parents=True)
        shutil.copytree(package, dest / package.name, symlinks=True)
        results.skip("PKG-003", reason="not an MSI")
    elif kind is PackageKind.ZIP:
        results.skip("PKG-003", reason="not an MSI")
        try:
            extracted = safe_extract_zip(package, dest, limits)
        except ExtractError as exc:
            results.add(
                "PKG-001",
                Status.FAIL,
                "Archive cannot be extracted safely",
                excerpt(exc.problems),
                fix="Rebuild the ZIP with plain relative paths, no links and no encryption.",
            )
            results.skip("PKG-002", reason="no payload: extraction was refused")
            outcome.results = results.sorted()
            return outcome
        outcome.nested_archives = extracted.nested_archives
    else:
        if not _extract_msi(package, dest, cfg, results, outcome, work_dir):
            outcome.results = results.sorted()
            return outcome

    files, links = _tree(dest)
    if _check_tree(results, dest, files, links, limits):
        outcome.payload_dir, outcome.files = dest, files
        _check_payload(results, dest, files, extensions)
    else:
        results.skip("PKG-002", reason="payload rejected by PKG-001")
    outcome.results = results.sorted()
    return outcome


def _extract_msi(
    package: Path, dest: Path, cfg: MtaConfig, results: ResultSink, outcome: PackageExtraction, work_dir: Path
) -> bool:
    limits = cfg.thresholds.extract
    try:
        tables = msi_read_tables(package)
    except MsiError as exc:
        results.add(
            "PKG-003",
            Status.FAIL,
            "MSI database cannot be read",
            str(exc),
            fix="Rebuild the MSI; the file is damaged or not a Windows Installer package.",
        )
        results.skip("PKG-001", "PKG-002", reason="MSI could not be read")
        return False
    outcome.msi = tables

    admin_code = tables.admin_code_actions
    if admin_code:
        rows = [f"{a.name} (type {a.type}, {a.kind}) in {', '.join(a.sequences)}" for a in admin_code]
        results.add(
            "PKG-003",
            Status.NEEDS_REVIEW,
            "Admin install would run publisher code, so it was not started outside a sandbox",
            excerpt(rows),
        )
        results.skip("PKG-001", "PKG-002", reason="MSI not extracted (admin custom actions)")
        return False
    declared = []
    if tables.file_count > limits.max_files:
        declared.append(f"{tables.file_count} files exceed the limit of {limits.max_files}")
    if tables.declared_bytes > limits.max_bytes:
        declared.append(
            f"declared size {tables.declared_bytes} bytes exceeds the limit of {limits.max_bytes}"
        )
    if declared:
        results.add("PKG-001", Status.FAIL, "MSI declares more than the safety limits", excerpt(declared))
        results.skip("PKG-002", "PKG-003", reason="not extracted: over the limits")
        return False

    log = work_dir / "msiexec-admin.log"
    done = msi_admin_extract(package, dest, log, limits.msi_timeout_s)
    problem = done.environment_problem
    if problem:
        results.add("PKG-003", Status.ERROR, f"msiexec could not run: {problem}", done.log_tail)
        results.skip("PKG-001", "PKG-002", reason="MSI not extracted (environment problem)")
        return False
    if not done.succeeded:
        results.add(
            "PKG-003",
            Status.FAIL,
            f"Administrative extraction failed (msiexec exit {done.exit_code})",
            done.log_tail,
            fix="Make sure `msiexec /a` works on the package (no custom actions "
            "required for an administrative image).",
        )
        results.skip("PKG-001", "PKG-002", reason="MSI not extracted")
        return False
    code_actions = [a for a in tables.custom_actions if a.executes_code]
    note = (
        f"; {len(code_actions)} code custom action(s) inventoried for the sandbox install"
        if code_actions
        else ""
    )
    results.add("PKG-003", Status.PASS, f"Administrative extraction succeeded{note}")
    return True
