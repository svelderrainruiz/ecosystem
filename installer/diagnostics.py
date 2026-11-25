"""Diagnostics zip (ARCH-10, ARCH-12): written locally from an allow-list, never uploaded (INST-REQ-048/049/050/060/085).

The only fields that can enter are the names in diag-allowlist.txt (the file is the single source; the operator reviews every
change to it). Values come from <install folder>/state.json (scalar fields) and <install folder>/steps.jsonl (exit codes,
timings, error codes); folder names with sizes come from the install folder's direct subfolders. No file content is read
except those two. A text value that is not plain (letters, digits, space . _ - + ( ) ) is replaced by "[redacted]", so
paths, URLs, environment variables, user names and host names cannot get through; names given in `deny` (user name, host
name) are removed even when plain. This module has no network code: the caller shows the returned path to the user, who
sends the zip himself.
steps.jsonl (the full step log, with commands and output) is NOT part of the zip and must not be sent.
"""
import json
import os
import re
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ALLOWLIST_PATH = HERE / "diag-allowlist.txt"
PLAIN = re.compile(r"^[A-Za-z0-9 ._+()-]{1,80}$")
SCALAR_FIELDS = ("version", "windows_edition", "service_state")
ENTRY_NAME = "diagnostics.json"


class DiagnosticsError(Exception):
    """Base of every expected refusal."""


class AllowlistError(DiagnosticsError):
    pass


def load_allowlist(path=ALLOWLIST_PATH):
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as e:
        raise AllowlistError(f"allow-list {path} is unreadable: {e!r}") from None
    names = [l.strip() for l in lines if l.strip() and not l.lstrip().startswith("#")]
    if not names:
        raise AllowlistError("allow-list is empty")
    return names


def _plain(value, deny):
    text = str(value)
    if not PLAIN.match(text) or any(d and d.lower() in text.lower() for d in deny):
        return "[redacted]"
    return text


def _folder_sizes(root, deny):
    sizes = {}
    for child in sorted(Path(root).iterdir()):
        if child.is_dir() and not child.is_symlink():
            total = sum(f.stat().st_size for f in child.rglob("*") if f.is_file() and not f.is_symlink())
            sizes[_plain(child.name, deny)] = total
    return sizes


def collect(install_folder, allowlist=None, deny=()):
    try:
        return _collect(install_folder, allowlist, deny)
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        raise DiagnosticsError(f"state or step log is malformed: {type(e).__name__}") from None


def _collect(install_folder, allowlist, deny):
    root = Path(install_folder)
    if not root.is_dir():
        raise DiagnosticsError(f"install folder not found: {root.name}")
    allowed = set(allowlist if allowlist is not None else load_allowlist())
    deny = [d for d in deny if d]
    state_path, steps_path = root / "state.json", root / "steps.jsonl"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    steps = [json.loads(l) for l in steps_path.read_text(encoding="utf-8").splitlines() if l.strip()] \
        if steps_path.exists() else []
    out = {}
    for name in SCALAR_FIELDS:
        if name in allowed and name in state:
            out[name] = _plain(state[name], deny)
    if "exit_codes" in allowed:
        out["exit_codes"] = {}
        for step in steps:
            code = step["exit_code"]
            if type(code) is not int and not (code is None and step.get("exec_error") in ("error", "timeout")):
                raise DiagnosticsError("invalid step exit code")
            out["exit_codes"][_plain(step["step"], deny)] = code
    if "timings" in allowed:
        out["timings"] = {_plain(s["step"], deny): int(s["duration_ms"]) for s in steps if "duration_ms" in s}
    if "error_codes" in allowed:
        out["error_codes"] = {_plain(s["step"], deny): _plain(s["error_code"], deny) for s in steps if s.get("error_code")}
        for step in steps:
            if step.get("exec_error") in ("error", "timeout") and step["exit_code"] is None:
                out["error_codes"][_plain(step["step"], deny)] = step["exec_error"]
    if "folder_sizes" in allowed:
        out["folder_sizes"] = _folder_sizes(root, deny)
    return out


def write_zip(install_folder, out_dir=None, allowlist=None, deny=(), stamp="now"):
    """Writes <out_dir>/diagnostics-<stamp>.zip (default: <install folder>/diagnostics) and returns its path."""
    data = collect(install_folder, allowlist, deny)
    out_dir = Path(out_dir) if out_dir else Path(install_folder) / "diagnostics"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"diagnostics-{_plain(stamp, ())}.zip".replace(" ", "_")
    info = zipfile.ZipInfo(ENTRY_NAME, date_time=(1980, 1, 1, 0, 0, 0))
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(info, json.dumps(data, indent=1, sort_keys=True) + "\n")
    os.chmod(target, 0o600)
    return target


def location_message(path):
    return f"Diagnostics written to {path}. Nothing was sent: read it and send it yourself if you want to."
