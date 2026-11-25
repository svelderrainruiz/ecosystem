"""Footprint and elevation scan (ARCH-5, ARCH-6; INST-REQ-027..032, 078, 079, 089).

installer/footprint.json is the one description of what the installer may change: one folder, one service, one
uninstall entry (plus the documented per-user exceptions). installer/allowlist-read.txt lists what it may read.
`scan_nsis` and `scan_powershell` read the SOURCE and report every write, every read and every elevated marker so a
test (and CI) can refuse a change that goes beyond the lists. Expected refusals are typed errors.

  python -m installer.footprint check     scan installer/nsis/*.nsh|nsi and installer/*.ps1; exit 2 on a violation
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRUST_DIR = "$LOCALAPPDATA\\EcosystemInstaller"
TRUST_VAR = "$TrustStoreFile"
FOOTPRINT = HERE / "footprint.json"
ALLOWLIST = HERE / "allowlist-read.txt"
UNELEVATED_FILES = ("main.nsi", "trust.nsh", "screens.nsh")
TOKEN = re.compile(r'"[^"]*"|\'[^\']*\'|`[^`]*`|\S+')
LABEL = re.compile(r"^\s*[A-Za-z_][\w.]*:\s+(?=\S)")
DEFINE = re.compile(r"^\s*!define\s+(\w+)\s+(.+)$", re.I)
FUNCTION = re.compile(r"^\s*Function\s+(\S+)", re.I)
FUNCTION_END = re.compile(r"^\s*FunctionEnd\b", re.I)

REG_WRITE = {"writeregstr", "writeregdword", "writeregbin", "writeregexpandstr", "deleteregkey", "deleteregvalue"}
PATH_WRITE = {"createdirectory", "setoutpath", "delete", "rmdir", "writeuninstaller", "createshortcut", "file",
              "writeinistr", "deleteinisec", "deleteinistr", "flushini"}
PATH_WRITE_SECOND = {"copyfiles", "rename"}
EXEC = {"exec", "execwait", "execshell", "execshellwait", "!system", "!execute"}
EXEC_PREFIXES = ("nsexec::", "execdos::", "system::", "inetc::", "nsisdl::", "nsisdl", "inetc")
# The one System plugin call that is a path write and not a command: RemoveDirectoryW on one quoted path (installer/nsis/tree.nsh), checked like RMDir.
SYSTEM_REMOVE_DIRECTORY = re.compile(r'^kernel32::RemoveDirectoryW\(\s*w\s+"([^"]+)"\s*\)\s*i\s*\.s$', re.I)
# Exact complete instructions, including opcode, registers and protected descriptor.
SECURE_CREATE_OPERATIONS = frozenset((
    """System::Call 'advapi32::ConvertStringSecurityDescriptorToSecurityDescriptorW(w "O:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)", i 1, *p .r1, p 0) i .r0'""",
    """System::Call '*(&l4, p r1, i 0)p.r2'""",
    r"""System::Call 'kernel32::CreateDirectoryW(w "$APPDATA\EcosystemRunner", p r2) i .r0'""",
    "System::Free $2",
    """System::Call 'kernel32::LocalFree(p r1) p'""",
))
# The one exact complete instruction that Elevate_Raise (installer/nsis/elevate.nsh) may execute: the relaunch with runas.
ELEVATE_RAISE_OPERATIONS = frozenset(('ExecShell "runas" "$EXEPATH" "$carry_args"',))
PS_WRITE_CMDLETS = (
    "Set-Content|Add-Content|Out-File|New-Item|Remove-Item|Set-ItemProperty|New-ItemProperty|Remove-ItemProperty|"
    "Copy-Item|Move-Item|Rename-Item|New-Service|Set-Service|Remove-Service|Start-Process|Invoke-Expression|"
    "Register-ScheduledTask|Tee-Object|Export-Csv|Export-Clixml|Set-Acl|Expand-Archive|Compress-Archive|"
    "Invoke-WebRequest|Invoke-RestMethod|Clear-Content|Set-Location")
PS_ALIASES = "ni|del|rm|mkdir|md|cp|mv|copy|move|erase|rd|rmdir|ri|rni|mi|ci|ac|sc|sp|si|clc|tee|iwr|irm|iex|saps|start|curl|wget"
PS_WRITE = re.compile(
    rf"\b({PS_WRITE_CMDLETS})\b"
    rf"|(?:^|[;|({{&]|\bthen\b)\s*({PS_ALIASES})\b(?![-.\w])"
    r"|\b(sc\.exe|reg|reg\.exe|schtasks|netsh)\s+\w|\[\s*(System\.)?IO\.File\s*\]\s*::\s*(Write|Append|Delete|Copy|Move)",
    re.I)
PS_BACKTICK = re.compile(r"[A-Za-z0-9]`[A-Za-z0-9-]")
PS_REDIRECT = re.compile(r">(?!&\d)")
PS_STRINGS = re.compile(r"'[^']*'|\"[^\"]*\"")
PS_READ_CMDLETS = re.compile(r"\b(Get-Content|Test-Path|Get-ChildItem|Get-ItemProperty|Select-String|Import-Csv|Get-Item)\b([^|;\r\n]*)", re.I)


class FootprintError(Exception):
    """A refusal: a damaged footprint file, or a source that goes beyond it."""


def load_footprint(path=None):
    path = Path(path or FOOTPRINT)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FootprintError(f"cannot read footprint file {path.name}: {exc}")
    for key, sub in (("folder", "path"), ("service", "name"), ("service", "account"), ("uninstall_entry", "key")):
        if not isinstance(data.get(key), dict) or not isinstance(data[key].get(sub), str) or not data[key][sub]:
            raise FootprintError(f"footprint file lacks {key}.{sub}")
    for key in ("rights", "elevated_markers", "per_user_exceptions", "ps_input_variables"):
        if not isinstance(data.get(key), list) or not data[key]:
            raise FootprintError(f"footprint file lacks a non-empty {key}")
    for e in data["per_user_exceptions"]:
        p = e.get("path", "") if isinstance(e, dict) else ""
        if p != TRUST_VAR and not _under(p, TRUST_DIR):
            raise FootprintError(f"per-user exception {p!r} is not under {TRUST_DIR}")
    code = data.get("exit_codes", {}).get("not-elevated")
    if not isinstance(code, int) or isinstance(code, bool) or code <= 0:
        raise FootprintError("footprint file lacks exit_codes.not-elevated")
    return data


def load_allowlist(path=None):
    path = Path(path or ALLOWLIST)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise FootprintError(f"cannot read allow-list {path.name}: {exc}")
    entries = [l.strip() for l in lines if l.strip() and not l.lstrip().startswith("#")]
    if not entries:
        raise FootprintError("the read allow-list is empty")
    return entries


def _under(target, prefix):
    t, p = target.lower().rstrip("\\"), prefix.lower().rstrip("\\")
    return t == p or t.startswith(p + "\\")


def write_targets_allowed(fp):
    return [fp["folder"]["path"], fp["uninstall_entry"]["key"]] + [e["path"] for e in fp["per_user_exceptions"]]


def _clean(line):
    line = line.strip()
    if line.startswith((";", "#")):
        return ""
    return line


def _tokens(line):
    return [t[1:-1] if len(t) > 1 and t[0] in "\"'`" and t[-1] == t[0] else t for t in TOKEN.findall(line)]


def scan_nsis(text, markers=()):
    """Returns dicts {line, function, kind: write|read|exec|marker, target} for every relevant NSIS line."""
    out, func, defines = [], None, {}
    for n, raw in enumerate(text.splitlines(), 1):
        line = _clean(raw)
        if not line:
            continue
        line = LABEL.sub("", line)
        d = DEFINE.match(line)
        if d:
            defines[d.group(1)] = d.group(2).strip()
        for dn, dv in defines.items():
            line = line.replace("${%s}" % dn, dv)
        m = FUNCTION.match(line)
        if m:
            func = m.group(1)
            continue
        if FUNCTION_END.match(line):
            func = None
            continue
        toks = _tokens(line)
        op = toks[0].lower() if toks else ""
        args = toks[1:]
        oname = next((a[7:] for a in args if op == "file" and a.lower().startswith("/oname=")), None)
        while args and args[0].startswith("/"):
            args = args[1:]

        def add(kind, target):
            out.append({"line": n, "function": func, "kind": kind, "target": target})

        if op in REG_WRITE and len(args) >= 2:
            add("write", f"{args[0]}\\{args[1]}")
        elif op in PATH_WRITE and args:
            add("write", oname or args[-1] if op == "file" else args[0])
        elif op in PATH_WRITE_SECOND and len(args) >= 2:
            add("write", args[-1])
        elif op == "fileopen" and len(args) >= 3:
            add("read" if args[2].lower() == "r" else "write", args[1])
        elif op in ("readregstr", "readregdword") and len(args) >= 4:
            add("read", f"{args[1]}\\{args[2]}\\{args[3]}")
        elif op == "iffileexists" and args:
            add("read", args[0])
        elif op == "findfirst" and len(args) >= 3:
            add("read", args[2])
        elif op == "readenvstr" and len(args) >= 2:
            add("read", "$" + args[1])
        elif op == "system::call" and SYSTEM_REMOVE_DIRECTORY.match(" ".join(args)):
            add("write", SYSTEM_REMOVE_DIRECTORY.match(" ".join(args)).group(1))
        elif op in EXEC or op.startswith(EXEC_PREFIXES):
            add("exec", " ".join(args))
        flat = " ".join(line.lower().split())
        if any(" ".join(mk.lower().split()) in flat for mk in markers):
            add("marker", line)
    return out


def _ps_read_path(rest):
    """The path argument of a read cmdlet: the token after -Path/-LiteralPath, else the first positional token."""
    toks = [t.rstrip(")") for t in TOKEN.findall(rest) if t.rstrip(")")]
    for i, t in enumerate(toks):
        if t.lower() in ("-path", "-literalpath", "-filepath") and i + 1 < len(toks):
            return toks[i + 1]
    for t in toks:
        if not t.startswith("-"):
            return t
    return None


def scan_powershell(text, input_vars=()):
    out = []
    for n, raw in enumerate(text.splitlines(), 1):
        if raw.lstrip().startswith("#"):
            continue
        bare = PS_STRINGS.sub("''", raw)
        bare = bare.split("#", 1)[0]
        line = raw if ("'" in raw or '"' in raw) else raw.split("#", 1)[0]
        if PS_BACKTICK.search(bare):
            out.append({"line": n, "kind": "write", "target": "backtick in a command word"})
        if PS_REDIRECT.search(bare):
            out.append({"line": n, "kind": "write", "target": "redirection"})
        m = PS_WRITE.search(bare)
        if m:
            out.append({"line": n, "kind": "write", "target": m.group(0).strip(" ;|({&")})
        for m in PS_READ_CMDLETS.finditer(line):
            path = _ps_read_path(m.group(2))
            if path is None:
                out.append({"line": n, "kind": "write", "target": f"{m.group(1)} without a determinable path"})
            elif path[:1] in "'\"" and "$" not in path:
                out.append({"line": n, "kind": "read", "target": path.strip("'\"")})
            elif path in input_vars:
                continue
            else:
                out.append({"line": n, "kind": "write", "target": f"{m.group(1)} with a non-literal path {path}"})
    return out


def read_allowed(target, allow):
    return any(_under(target, a) for a in allow)


def _exec_allowed(fp, name, finding):
    """A listed file and function may run exactly the listed command lines (the service removal), nothing else."""
    return any(e["file"] == name and e["function"] == finding["function"] and finding["target"] in e["commands"]
               for e in fp.get("exec_allowed", []))


def check_source(sources, fp=None, allow=None):
    """sources: {file name: text}. Returns a list of violation strings (empty = within the footprint)."""
    fp = fp or load_footprint()
    allow = allow or load_allowlist()
    writes = write_targets_allowed(fp)
    bad = []
    # Resolve the log alias only for its two operations, never as a new allowed root.
    log_init = (
        "SetShellVarContext all",
        f'StrCpy $MachineFolder "{fp["folder"]["path"]}"',
        r'StrCpy $LogPath "$MachineFolder\steps.jsonl"',
        "SetShellVarContext current",
    )
    log_source = sources.get("log.nsh", "")
    init = re.search(r"(?ms)^Function Log_InitPaths\n(.*?)^FunctionEnd", log_source)
    pinned = init and tuple(_clean(line) for line in init[1].splitlines() if _clean(line)) == log_init
    init_lines = range(log_source.count("\n", 0, init.start(1)) + 1,
                       log_source.count("\n", 0, init.end(1)) + 1) if pinned else ()
    for name, text in sorted(sources.items()):
        if name.endswith(".ps1"):
            for f in scan_powershell(text, fp["ps_input_variables"]):
                if f["kind"] == "write" or not read_allowed(f["target"], allow):
                    bad.append(f"{name}:{f['line']}: {f['kind']} {f['target']!r} is outside the footprint")
            continue
        lines = text.splitlines()
        for n, raw in enumerate(lines, 1):
            line = _clean(raw)
            if re.search(r"\$(LogPath|MachineFolder)\b", line, re.I):
                if name == "log.nsh" and (n in init_lines or line in (
                        'FileOpen $LogHandle "$LogPath" a', 'IfFileExists "$LogPath" log_ready done')):
                    continue
                if name == "elevate.nsh" and line.startswith("${NSD_CreateLabel} ") and "$MachineFolder" in line:
                    continue
                bad.append(f"{name}:{n}: unrecognised machine path alias use")
        for f in scan_nsis(text, fp["elevated_markers"]):
            where = f"{name}:{f['line']}"
            if pinned and name == "log.nsh" and f["function"] == "LogStep" and f["target"] == "$LogPath":
                f["target"] = fp["folder"]["path"] + r"\steps.jsonl"
            if f["kind"] == "write" and not any(_under(f["target"], w) for w in writes):
                bad.append(f"{where}: write to {f['target']!r} is outside the footprint")
            elif f["kind"] == "read" and not read_allowed(f["target"], allow):
                bad.append(f"{where}: read of {f['target']!r} is not in the allow-list")
            elif f["kind"] == "exec" and not (name == "elevate.nsh" and f["function"] == "Elevate_Raise"
                                              and lines[f["line"] - 1].strip() in ELEVATE_RAISE_OPERATIONS) \
                    and not (name == "winsys.nsh" and f["function"] == "Winsys_FolderCreate"
                             and lines[f["line"] - 1].strip() in SECURE_CREATE_OPERATIONS) \
                    and not _exec_allowed(fp, name, f):
                bad.append(f"{where}: command execution {f['target']!r} is outside the footprint")
            elif f["kind"] == "marker":
                if name in UNELEVATED_FILES:
                    bad.append(f"{where}: administrator action before the elevation screen: {f['target']!r}")
                elif name == "elevate.nsh" and f["function"] != "Elevate_Raise":
                    bad.append(f"{where}: rights raised outside Elevate_Raise: {f['target']!r}")
    for name, text in sorted(sources.items()):
        for m in re.finditer(r"(?im)^\s*StrCpy\s+\$TrustStoreFile\s+(\S+)", text):
            if not _under(m.group(1).strip("\"'`"), TRUST_DIR):
                bad.append(f"{name}: $TrustStoreFile is set outside {TRUST_DIR}")
    return bad


def collect_sources(root=None):
    root = Path(root or HERE)
    files = list((root / "nsis").glob("*.nsh")) + list((root / "nsis").glob("*.nsi")) + list(root.glob("*.ps1"))
    return {p.name: p.read_text(encoding="utf-8") for p in files}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv != ["check"]:
        print("usage: python -m installer.footprint check", file=sys.stderr)
        return 2
    try:
        bad = check_source(collect_sources())
    except FootprintError as exc:
        print(f"footprint: {exc}", file=sys.stderr)
        return 2
    for b in bad:
        print(f"footprint: {b}", file=sys.stderr)
    return 2 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
