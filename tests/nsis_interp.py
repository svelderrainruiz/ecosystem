"""A small interpreter for the NSIS functions of the installer (Linux, no Windows): it runs the real text of the .nsh/.nsi files.
Only the instructions those functions use are known; an unknown one raises, so a new instruction must be added here on purpose.
Natives (Windows plug-ins and the other slices) are supplied by the World: TrustCheck, Elevate_IsAdmin's account, LogStep."""
import re
from pathlib import Path

NSIS = Path(__file__).resolve().parent.parent / "installer" / "nsis"
TOKEN = re.compile(r'"[^"]*"|\'[^\']*\'|`[^`]*`|\S+')


class Quit(Exception):
    pass


class Abort(Exception):
    pass


class Return(Exception):
    pass


def tokens(line):
    return [t[1:-1] if t[0] in "\"'`" and len(t) > 1 and t[-1] == t[0] else t for t in TOKEN.findall(line)]


def source_text():
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(NSIS.glob("*")) if p.suffix in (".nsh", ".nsi")}


def preprocess(text, defines, version):
    out, stack = [], []
    for raw in text.splitlines():
        line = raw.strip()
        m = re.match(r"!(ifdef|ifndef)\s+(\w+)", line, re.I)
        if m:
            stack.append((m.group(2) in defines) == (m.group(1).lower() == "ifdef"))
        elif re.match(r"!else\b", line, re.I):
            stack[-1] = not stack[-1]
        elif re.match(r"!endif\b", line, re.I):
            stack.pop()
        elif all(stack):
            out.append(raw.replace("${INSTALLER_VERSION}", version).replace("${RUNNER_PAYLOAD}", "payload.bin"))
    return "\n".join(out) + "\n"


class Program:
    def __init__(self, files=None, defines=None, version="0.0.0"):
        """`defines` (a set of names) turns on !ifdef/!ifndef/!else/!endif handling and the ${INSTALLER_VERSION} substitution; None leaves the text as is."""
        self.functions, self.macros, self.macro_params = {}, {}, {}
        for text in (files or source_text()).values():
            if defines is not None:
                text = preprocess(text, defines, version)
            for m in re.finditer(r"(?ms)^Function (\S+)\n(.*?)^FunctionEnd", text):
                self.functions.setdefault(m.group(1), m.group(2))
            for m in re.finditer(r"(?ms)^!macro (\S+)([^\n]*)\n(.*?)^!macroend", text):
                self.macros[m.group(1)], self.macro_params[m.group(1)] = m.group(3), m.group(2).split()

    def lines(self, body):
        out = []
        for raw in body.splitlines():
            line = raw.strip()
            if not line or line.startswith(";"):
                continue
            t = tokens(line)
            if t[0] == "${IfNot}":
                t = ["${If}", "!"] + t[1:]
            if t[0] == "!insertmacro":
                body = self.macros[t[1]]
                for param, arg in zip(self.macro_params[t[1]], t[2:]):  # !insertmacro substitutes ${param} by its argument text
                    body = body.replace("${%s}" % param, arg)
                out += self.lines(body)
            else:
                out.append(t)
        return out

    def compile(self, name):
        code, blocks, loops, labels = [], [], [], {}
        conds = ("${If}", "${ElseIf}", "${AndIf}", "${OrIf}")

        def patch(idxs, to):
            for i in idxs:
                code[i][2] = to

        prev_cond = False
        for t in self.lines(self.functions[name]):
            op = t[0]
            if prev_cond and op not in ("${AndIf}", "${OrIf}"):
                patch(blocks[-1]["jumps"], len(code))
                blocks[-1]["jumps"] = []
            prev_cond = op in conds
            if op in ("${If}", "${ElseIf}"):
                if op == "${ElseIf}":
                    b = blocks[-1]
                    b["ends"].append(len(code))
                    code.append(["jmp", None, None])
                    patch(b["falses"], len(code))
                    b["falses"] = []
                else:
                    blocks.append({"falses": [], "jumps": [], "ends": []})
                blocks[-1]["falses"].append(len(code))
                code.append(["brfalse", t[1:], None])
            elif op == "${Else}":
                b = blocks[-1]
                b["ends"].append(len(code))
                code.append(["jmp", None, None])
                patch(b["falses"], len(code))
                b["falses"] = []
            elif op == "${AndIf}":
                blocks[-1]["falses"].append(len(code))
                code.append(["brfalse", t[1:], None])
            elif op == "${OrIf}":
                b = blocks[-1]
                b["jumps"].append(len(code))
                code.append(["jmp", None, None])
                patch(b["falses"], len(code))
                b["falses"] = [len(code)]
                code.append(["brfalse", t[1:], None])
            elif op == "${Else}":
                b = blocks[-1]
                b["ends"].append(len(code))
                code.append(["jmp", None, None])
                patch(b["falses"], len(code))
                b["falses"] = []
            elif op == "${EndIf}":
                b = blocks.pop()
                patch(b["falses"] + b["ends"], len(code))
            elif op == "${Do}":
                loops.append({"start": len(code), "exits": []})
            elif op == "${ExitDo}":
                loops[-1]["exits"].append(len(code))
                code.append(["jmp", None, None])
            elif op == "${Loop}":
                lp = loops.pop()
                code.append(["jmp", None, lp["start"]])
                patch(lp["exits"], len(code))
            elif op.endswith(":") and len(t) == 1:
                labels[op[:-1]] = len(code)
            else:
                code.append(t)
        return code, labels


def word_find(text, delim, spec):
    """${WordFind} as in WordFunc.nsh (WordFindBody): only the +N form is modelled. Without the leading E an error leaves the
    input as the result and does not set the error flag; with E the flag is set and the result is 1, 2 or 3."""
    flag_e = False
    while spec[:1] == "E":
        flag_e, spec = True, spec[1:]
    if spec[:1] != "+":
        raise ValueError("the test interpreter models only the +N form of WordFind, not %r" % spec)

    def error(code):
        return (str(code), True) if flag_e else (text, False)

    n = int(spec[1:])
    if n == 0:
        return error(2)
    if text == "":
        return error(1)
    pos = start = count = 0
    while True:
        seg = text[pos:pos + len(delim)]
        if seg == "" and start == 0:
            return error(1)
        if seg != "" and seg != delim:
            pos += 1
            continue
        if start != pos:
            count += 1
            if count == n:
                return text[start:pos], False
        elif seg == "":
            return error(2)
        pos += len(delim)
        start = pos


def get_options(line, option):
    """${GetOptions} as in FileFunc.nsh (GetOptionsBody), the case-insensitive macro. Returns None when the option is not found."""
    first, rest = option[:1], option[1:]
    stage, s = 0, line
    i, quote = -1, ""
    while True:
        i += 1
        ch = s[i:i + 1]
        if ch == "":
            if stage == 0:
                return None
            break
        if ch in "\"'`":
            if quote == "":
                quote = ch
                continue
            if quote == ch:
                quote = ""
                continue
        if quote or ch.lower() != first.lower():
            continue
        if stage == 1:
            break
        i += 1
        seg = s[i:i + len(rest)]
        if seg == "":
            return None
        if seg.lower() != rest.lower():
            continue
        s = s[i + len(rest):].lstrip(" ")
        stage, i, quote = 1, -1, ""
    s = s[:i].rstrip(" ")
    if s[:1] == s[-1:] and s[:1] in ("\"", "'", "`"):
        s = s[1:-1]
    return s


PROGRAM_PATH = '"C:\\Program Files\\Ecosystem Installer\\setup.exe"'


def get_parameters(cmdline):
    """${GetParameters} as in FileFunc.nsh (GetParameters_, NSIS 3.10): $CMDLINE without the program name. The separator is a quote when
    the first character is one, else a blank; the scan for it starts at the THIRD character; only blanks are trimmed, on both sides.
    The real function saves and restores $0-$3, uses no $R register, leaves the stack as it was and never sets or clears the error flag."""
    if cmdline == "":
        return ""
    sep = '"' if cmdline[0] == '"' else " "
    n, pos = len(cmdline), 2
    while pos < n:
        ch = cmdline[pos]
        pos += 1
        if ch == sep:
            break
    while pos < n and cmdline[pos] == " ":
        pos += 1
    return cmdline[pos:].rstrip(" ")


LOOP_CAP = 5000


class World:
    """Scripted Windows: command line, silent flag, account type, radio states, and what the script did.
    A real $CMDLINE starts with the program path (quoted when it holds a blank): cmdline is what follows it, and exe is the path.
    exe=None makes $CMDLINE exactly cmdline."""

    def __init__(self, cmdline="", silent=False, admin=True, radios=None, program=None, texts=None, exe=PROGRAM_PATH):
        full = cmdline if exe is None else exe + (" " + cmdline if cmdline else "")
        self.var = {"CMDLINE": full, "EXEPATH": (exe or "").strip('"'), "APPDATA": "C:\\ProgramData"}
        self.silent, self.admin, self.radios = silent, admin, dict(radios or {})
        self.texts = dict(texts or {})
        self.details = []
        self.program = program or Program()
        self.stack, self.errors, self.exit_code = [], False, 0
        self.trace, self.log, self.boxes, self.files, self.handles = [], [], [], {}, {}
        self.open_handles = set()
        self.write_fails = set()
        self.dialog_result = "handle"
        self.quit_code = None
        self.limits = []
        self.shell = []

    def expand(self, s):
        s = s.replace("$\\t", "\t").replace("$\\r", "\r").replace("$\\n", "\n").replace("$$", "\0")
        s = re.sub(r"\$\{BST_CHECKED\}", "1", s)
        s = s.replace("${ENGINE_EXE}", self.defines["ENGINE_EXE"])
        s = re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*|\d)", lambda m: self.var.get(m.group(1), ""), s)
        return s.replace("\0", "$")

    def set(self, tok, value):
        self.var[tok.lstrip("$")] = value

    def cond(self, t):
        if t == ["${Errors}"]:
            return self.errors
        if t == ["${Silent}"]:
            return self.silent
        if t[0] == "!":
            return not self.cond(t[1:])
        a, op, b = t
        a, b = self.expand(a), self.expand(b)
        if op in (">", ">=", "<", "<="):
            x, y = int(a), int(b)
            return {">": x > y, ">=": x >= y, "<": x < y, "<=": x <= y}[op]
        if op == "==":
            return a.lower() == b.lower()
        if op == "!=":
            return a.lower() != b.lower()
        if op == "S==":
            return a == b
        if op == "S!=":
            return a != b
        raise ValueError("unknown comparison %r" % op)

    def run(self, name, expect_exit=True):
        """Runs one function; returns the exit code of a Quit, or None when it ended normally (an Abort is returned as 'abort')."""
        try:
            self.call(name)
        except Quit:
            return self.exit_code
        except Abort:
            return "abort"
        return None

    def call(self, name):
        native = getattr(self, "native_" + name, None)
        if native:
            return native()
        self.call_script(name)

    def call_script(self, name):
        code, labels = self.program.compile(name)
        pc = 0
        passes = {}
        try:
            while pc < len(code):
                ins = code[pc]
                passes[pc] = passes.get(pc, 0) + 1
                if passes[pc] > LOOP_CAP:
                    raise AssertionError("NSIS loop does not end")
                pc += 1
                if ins[0] == "jmp":
                    pc = ins[2]
                elif ins[0] == "brfalse":
                    if not self.cond(ins[1]):
                        pc = ins[2]
                else:
                    jump = self.step(ins, labels)
                    if jump is not None:
                        pc = pc - 1 + int(jump) if isinstance(jump, str) else jump
        except Return:
            pass

    def native_TrustCheck(self):
        self.trace.append("TrustCheck")

    def native_Elevate_IsAdmin(self):
        self.var["elev_isadmin"] = "1" if self.admin else "0"

    def native_LogStep(self):
        self.log.append(tuple(self.stack.pop() for _ in range(3))[::-1])

    def native_Winsys_FolderLock(self):
        self.trace.append("FolderLock")

    def step(self, t, labels):
        op = t[0].lower()
        a = t[1:]
        if op == "strcpy":
            v = self.expand(a[1])
            if len(a) > 2:
                start = int(self.expand(a[3])) if len(a) > 3 else 0
                length = self.expand(a[2])
                v = v[start:]
                v = v[:int(length)] if length != "" else v
            self.set(a[0], v)
        elif op == "intop":
            x, y = int(self.expand(a[1])), int(self.expand(a[3]))
            if a[2] not in ("+", "-", "^"):
                raise ValueError("the test interpreter does not know the IntOp operator %r" % a[2])
            self.set(a[0], str({"+": x + y, "-": x - y, "^": x ^ y}[a[2]]))
        elif op == "clearerrors":
            self.errors = False
        elif op == "seterrors":
            self.errors = True
        elif op == "call":
            self.trace.append(a[0])
            self.call(a[0])
        elif op == "push":
            self.stack.append(self.expand(a[0]))
        elif op == "seterrorlevel":
            self.exit_code = int(a[0])
        elif op == "quit":
            raise Quit()
        elif op == "abort":
            raise Abort()
        elif op == "return":
            raise Return()
        elif op == "messagebox":
            self.boxes.append(self.expand(" ".join(a)))
        elif op == "detailprint":
            self.details.append(self.expand(a[0]))
        elif op == "strlen":
            self.set(a[0], str(len(self.expand(a[1]))))
        elif op == "${nsd_gettext}":
            self.set(a[1], self.texts.get(a[0].lstrip("$"), ""))
        elif op == "goto":
            return labels[a[0]]
        elif op == "iferrors":
            dest = a[0] if self.errors else (a[1] if len(a) > 1 else "0")
            self.errors = False
            return None if dest == "0" else labels[dest]
        elif op == "fileopen":
            path, mode = self.expand(a[1]), a[2]
            if path in self.files and mode == "w" and self.files[path] is None:
                self.errors = True
            else:
                self.files[path] = ""
                self.handles[a[0].lstrip("$")] = path
                self.open_handles.add(a[0].lstrip("$"))
        elif op == "filewrite":
            h = a[0].lstrip("$")
            if h not in self.open_handles or self.handles[h] in self.write_fails:
                self.errors = True
            else:
                self.files[self.handles[h]] += self.expand(a[1])
        elif op == "delete":
            self.files.pop(self.expand(a[-1]), None)
        elif op == "fileclose":
            self.open_handles.discard(a[0].lstrip("$"))
        elif op == "${getoptions}":
            value = get_options(self.expand(a[0]), self.expand(a[1]))
            self.errors = value is None
            self.set(a[2], value or "")
        elif op == "${wordfind}":
            result, error = word_find(self.expand(a[0]), self.expand(a[1]), self.expand(a[2]))
            self.errors = error
            self.set(a[3], result)
        elif op == "${getparameters}":
            self.set(a[0], get_parameters(self.var["CMDLINE"]))
        elif op == "execshell":
            self.shell.append(tuple(self.expand(x) for x in a))
            if self.shell_fails:
                self.errors = True
        elif op == "sendmessage":
            self.limits.append((a[0].lstrip("$"), a[1], int(a[2])))
        elif op == "${strcase}":
            s = self.expand(a[1])
            self.set(a[0], s.upper() if a[2] == "U" else s.lower())
        elif op == "${strstr}":
            hay, needle = self.expand(a[1]), self.expand(a[2])
            self.set(a[0], hay[hay.index(needle):] if needle in hay else "")
        elif op == "${nsd_getstate}":
            self.set(a[1], "1" if self.radios.get(a[0].lstrip("$")) else "0")
        elif op == "setshellvarcontext":
            pass
        elif op == "iffileexists":
            return labels[a[2]] if len(a) > 2 and a[2] != "0" else None  # the plain World has no file system: nothing exists
        else:
            raise ValueError("the test interpreter does not know the NSIS instruction %r" % t[0])
        return None


ROOT = "C:\\ProgramData\\EcosystemRunner"
LOCKING = ("RUNNING", "STOP_PENDING", "START_PENDING")


class Service:
    """The EcosystemRunner service. A stop sets STOP_PENDING and queries then answer `stop_script`; every start takes the next entry of
    `start_scripts` (the last repeats). A running or pending service holds runner.exe open, as on Windows."""

    def __init__(self, exists=True, state="RUNNING", stop_codes=(0,), stop_script=("STOP_PENDING", "STOPPED"), start_codes=(0,),
                 start_scripts=(("RUNNING",),)):
        self.exists, self.state = exists, state
        self.stop_codes, self.stop_script = list(stop_codes), list(stop_script)
        self.start_codes, self.start_scripts = list(start_codes), [list(s) for s in start_scripts]
        self.script = [state]

    @staticmethod
    def _next(items):
        return items.pop(0) if len(items) > 1 else items[0]

    def stop(self):
        if not self.exists:
            return 1060
        code = self._next(self.stop_codes)
        if code == 0:
            if self.state == "STOPPED":
                return 1062
            self.state, self.script = "STOP_PENDING", list(self.stop_script)
        return code

    def start(self):
        if not self.exists:
            return 1060
        code = self._next(self.start_codes)
        if code == 0:
            if self.state == "RUNNING":
                return 1056
            self.state, self.script = "START_PENDING", list(self._next(self.start_scripts))
        return code

    def query(self):
        if not self.exists:
            return 1060, ""
        self.state = self._next(self.script)
        return 0, "SERVICE_NAME: EcosystemRunner\n        TYPE               : 10  WIN32_OWN_PROCESS\n        STATE              : 1  %s\n" \
                  "                                (STOPPABLE, NOT_PAUSABLE, ACCEPTS_SHUTDOWN)" % self.state

    @property
    def locks_files(self):
        return self.exists and self.state in LOCKING


class UpdateWorld(World):
    """The shared World plus a scripted Windows for update.nsh and winsys.nsh: a file system (path -> text, a directory exists while a file is under
    it), the service, the registry, Sleep, CopyFiles, RMDir, File with SetOverwrite, nsExec and the buffered FileOpen/FileRead/FileWrite.
    `fail` names operations that fail: backup, swap (the File write), restore, state (FileOpen of the state file). As in NSIS, a failing File
    under SetOverwrite on or ifdiff does not set the error flag: a silent installer aborts with exit code 2 ("abort-box" event)."""

    READ_LIMIT = 1023

    def __init__(self, files=None, service=None, admin=True, silent=True, answer="IDYES", payload="new-runner", fail=(), installer_version="0.2.0",
                 defines=("RUNNER_PAYLOAD",), swap_failures=0, restore_failures=0, pull_code=0, links=None, outside=(), stuck=()):
        super().__init__(silent=silent, admin=admin, program=Program(defines=set(defines), version=installer_version))
        self.files = dict(files or {})
        self.service, self.answer, self.payload, self.fail = service or Service(), answer, payload, set(fail)
        self.events, self.sleeps, self.regs, self.created = [], [], {}, 0
        self.folder_status, self.folder_create = "abse", "ok"
        self.folder_security = None
        # transient locks (runner.exe still mapped for a moment): that many writes / restore attempts fail, then they succeed
        self.swap_failures, self.restore_failures, self.swap_waits = swap_failures, restore_failures, []
        self.pull_code, self.pulls, self.probes = pull_code, [], []  # the container engine's answer to the image pull; the mode probes
        # SL-23b: `links` maps a directory link (absolute path) to its target; `outside` holds the files the targets contain (they must never change);
        # `stuck` names files that cannot be deleted (locked, or in a folder that cannot be listed); `tree_args` is every path pushed to Tree_Remove
        self.links, self.outside, self.stuck, self.tree_args = dict(links or {}), set(outside), set(stuck), []
        self.errorlevel, self.overwrite, self.fh, self.next_handle = None, "on", {}, 0
        # #335: icacls.exe and the folder probes, for a test that runs the real Winsys_FolderLock (native_Winsys_FolderLock = None). `acl_ops`
        # records every icacls call and every uninstaller write in order; `grants` maps a file to its explicit entries; `icacls_fail` names
        # the kinds (lock, setowner, reset, grant) that exit 5.
        self.acl_ops, self.grants, self.folder_acl, self.icacls_fail = [], {}, None, set()
        self.var.update({"SYSDIR": "C:\\Windows\\System32"})

    @property
    def v(self):
        return self.var

    @property
    def steps(self):
        return self.log

    def start(self, name):
        """Runs one function; returns "quit", "abort" or "done"."""
        try:
            self.call(name)
        except Quit:
            return "quit"
        except Abort:
            return "abort"
        return "done"

    def exists(self, path):
        for link, target in self.links.items():
            if path == link:
                return True
            if path.startswith(link + "\\"):  # a path that runs through a link sees the target
                return target + path[len(link):] in self.outside
        return path in self.files or any(f.startswith(path + "\\") for f in self.files)

    def under(self, prefix):
        return sorted(f for f in self.files if f.startswith(prefix + "\\"))

    def locked(self, path):
        return path in self.stuck or path.lower() == (ROOT + "\\program\\runner.exe").lower() and self.service.locks_files

    def jump(self, dest, labels):
        if dest and dest.startswith(("+", "-")):
            return dest
        return None if dest in ("0", None) else labels[dest]

    def native_Elevate_IsAdmin(self):
        self.var["elev_isadmin"] = "1" if self.admin else "0"

    def native_Tree_Remove(self):
        """The contract of tree.nsh (PR 118, tested there on its own text): the path below the product folder comes from the stack; $2 is the only register
        changed (1 = the entry or something below it is left, or the path was refused); a link goes as a link and its target stays."""
        rel = self.stack.pop()
        self.tree_args.append(rel)
        path = ROOT + "\\" + rel
        self.var["2"] = "1"
        if rel == "" or rel.endswith("\\"):
            return
        self.events.append("rmdir " + rel)
        if path in self.links:
            del self.links[path]
            self.events.append("unlink " + rel)
        elif path == ROOT + "\\program" and self.restore_failures > 0:
            self.restore_failures -= 1
            return
        else:
            for link in [k for k in self.links if k.startswith(path + "\\")]:
                del self.links[link]  # a link inside the tree goes as a link; its target stays
            if path in self.files and not self.locked(path):
                del self.files[path]
            for f in self.under(path):
                if not self.locked(f):
                    del self.files[f]
            if not self.under(path):
                self.files.pop(path + "\\.dir", None)
        self.var["2"] = "1" if self.exists(path) else "0"

    def native_Winsys_FolderLock(self):
        self.events.append("lock")

    def native_Winsys_FolderCheck(self):
        self.events.append("check")
        self.var["1"] = self.folder_status

    def native_Winsys_FolderCreate(self):
        self.events.append("folder-create")
        if self.folder_create not in ("ok", "create-fails", "descriptor-fails"):
            raise AssertionError(self.folder_create)
        self.call_script("Winsys_FolderCreate")  # stub only the native operations, not the failure branches

    def native_Winsys_Gate(self):
        pass

    def native_Install_Footprint(self):
        self.events.append("install-footprint")

    def native_Page_mode(self):
        self.events.append("mode-page")

    def native_Winsys_CreateService(self):
        self.events.append("create-service")
        self.service.exists = True
        self.service.state, self.service.script = "STOPPED", ["STOPPED"]
        self.created += 1

    def step(self, t, labels):
        op, a = t[0].lower(), t[1:]
        if op == "strcpy":
            v = self.expand(a[1])
            start = self.expand(a[3]) if len(a) > 3 else ""
            length = self.expand(a[2]) if len(a) > 2 else ""
            v = v[int(start):] if start != "" else v
            self.set(a[0], v[:int(length)] if length != "" else v)
        elif op == "strlen":
            self.set(a[0], str(len(self.expand(a[1]))))
        elif op == "intfmt":  # wsprintf with one integer: %c gives the character, %04X four upper-case hex digits
            self.set(a[0], self.expand(a[1]) % int(self.expand(a[2])))
        elif op == "intop":
            x, y = int(self.expand(a[1])), int(self.expand(a[3]))
            # "^" is the quote toggle of Cmdline_Next (IntOp $cl_q $cl_q ^ 1): it must not fall through to the product
            self.set(a[0], str(x + y if a[2] == "+" else x - y if a[2] == "-" else x ^ y if a[2] == "^" else x * y))
        elif op in ("strcmp", "strcmps"):
            x, y = self.expand(a[0]), self.expand(a[1])
            eq = x == y if op == "strcmps" else x.lower() == y.lower()
            return self.jump(a[2] if eq else (a[3] if len(a) > 3 else "0"), labels)
        elif op == "intcmp":
            x, y = int(self.expand(a[0])), int(self.expand(a[1]))
            dest = (a[2] if len(a) > 2 else "0") if x == y else (a[3] if len(a) > 3 else "0") if x < y else (a[4] if len(a) > 4 else "0")
            return self.jump(dest, labels)
        elif op == "iffileexists":
            return self.jump(a[1] if self.exists(self.expand(a[0])) else (a[2] if len(a) > 2 else "0"), labels)
        elif op == "pop":
            self.set(a[0], self.stack.pop())
        elif op == "exch":
            self.stack[-1], self.var[a[0][1:]] = self.var.get(a[0][1:], ""), self.stack[-1]
        elif op == "ifsilent":
            return self.jump(a[0] if self.silent else (a[1] if len(a) > 1 else None), labels)
        elif op == "iferrors":
            failed, self.errors = self.errors, False
            return self.jump(a[0] if failed else (a[1] if len(a) > 1 else None), labels)
        elif op == "sleep":
            self.sleeps.append(int(self.expand(a[0])))
            if self.events and self.events[-1] == "swap-failed":
                self.swap_waits.append(self.sleeps[-1])
            self.events.append("sleep")
        elif op in ("nsexec::exec", "nsexec::exectostack"):
            self.nsexec(op, self.expand(a[0]))
        elif op == "system::call" and a == ['advapi32::ConvertStringSecurityDescriptorToSecurityDescriptorW(w '
                                             '"O:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)", i 1, *p .r1, p 0) i .r0']:
            ok = self.folder_create != "descriptor-fails"
            self.var.update({"0": str(int(ok)), "1": "101" if ok else "0"})
        elif op == "system::call" and a == ["*(&l4, p r1, i 0)p.r2"]:
            self.var["2"] = "202"
        elif op == "system::call" and a == ['kernel32::CreateDirectoryW(w "$APPDATA\\EcosystemRunner", p r2) i .r0']:
            root = self.var["APPDATA"] + "\\EcosystemRunner"
            ok = self.folder_create == "ok" and self.folder_status == "abse" and not self.exists(root)
            self.var["0"] = str(int(ok))
            if ok:
                self.files[root + "\\.dir"] = ""
                self.folder_status = "fres"
                self.folder_security = {
                    "owner": "S-1-5-32-544", "protected": True,
                    "dacl": ("A;OICI;FA;;;SY", "A;OICI;FA;;;BA"),
                }
        elif op == "system::free" and a == ["$2"]:
            self.events.append("free-attributes")
        elif op == "system::call" and a == ["kernel32::LocalFree(p r1) p"]:
            self.events.append("free-descriptor")
        elif op == "createdirectory":
            self.errors = False
            self.files.setdefault(self.expand(a[0]) + "\\.dir", "")
        elif op == "rmdir":
            self.rmdir(self.expand([x for x in a if not x.startswith("/")][0]))
        elif op == "copyfiles":
            self.copyfiles(*[self.expand(x) for x in a if not x.startswith("/")])
        elif op == "fileopen":
            self.fileopen(a[0], self.expand(a[1]), a[2].lower())
        elif op == "fileread":
            self.fileread(a)
        elif op == "filewrite":
            h = self.fh[self.var[a[0].lstrip("$")]]
            if h["path"] in self.write_fails:
                self.errors = True
            else:
                h["buf"].append(self.expand(a[1]))
        elif op == "fileclose":
            h = self.fh.pop(self.var[a[0].lstrip("$")])
            if h["mode"] == "w":
                self.files[h["path"]] = "".join(h["buf"])
        elif op == "setoverwrite":
            self.overwrite = a[0].lower()
        elif op == "file":
            self.write_file(self.expand(a[0])[len("/oname="):])
        elif op == "writeuninstaller":
            path = self.expand(a[0])
            if "uninstaller" in self.fail:
                self.errors = True
                self.files.pop(path, None)
            else:
                if path not in self.files:
                    self.grants.pop(path, None)  # a new file has only the entries it inherits from the folder
                # CREATE_ALWAYS (exec.c EW_WRITEUNINSTALLER, v310) rewrites an existing file and keeps its DACL
                self.files[path] = "uninstaller"
                self.events.append("entry")
                self.acl_ops.append("write " + path[len(ROOT) + 1:])
        elif op == "writeregstr":
            self.regs[(self.expand(a[1]), self.expand(a[2]))] = self.expand(a[3])
        elif op == "messagebox":
            return self.messagebox(a, labels)
        elif op == "seterrorlevel":
            self.exit_code = self.errorlevel = int(self.expand(a[0]))
        elif op == "userinfo::getaccounttype":
            self.stack.append("Admin" if self.admin else "User")
        elif op in ("setshellvarcontext", "setregview"):
            pass
        else:
            return super().step(t, labels)
        return None

    def nsexec(self, op, command):
        if command.startswith('"%s\\icacls.exe" ' % self.var["SYSDIR"]):
            return self.icacls(command)
        if command.startswith('"%s\\WindowsPowerShell\\v1.0\\powershell.exe" ' % self.var["SYSDIR"]) and op.endswith("tostack"):
            return self.folder_probe(command)
        if command.endswith(" info --format {{.OSType}}"):
            # ENGINE-1 mode probe: answered as a failed read, so the update routes go on to the pull as before.
            self.probes.append(command)
            self.stack += ["", "error"]
            return
        verb = command.rsplit(" ", 2)[-2]
        self.events.append(verb)
        if verb == "stop":
            rc, out = self.service.stop(), ""
        elif verb == "start":
            rc, out = self.service.start(), ""
        elif verb == "query":
            rc, out = self.service.query()
        elif verb == "pull":
            self.pulls.append(command)
            rc, out = self.pull_code, ""
        else:
            raise AssertionError("command not scripted: " + command)
        if op.endswith("tostack"):
            self.stack.append(out)
        self.stack.append(str(rc))

    def icacls(self, command):
        """icacls.exe as winsys.nsh uses it: the folder lock (/inheritance:r with full control for SYSTEM and Administrators), the children's
        /setowner and /reset /T (a reset gives every child the folder's ACL only, so it drops their explicit entries), and /grant:r on a file
        (replaces that SID's explicit entry; a file that is not there exits 2, ERROR_FILE_NOT_FOUND)."""
        argv = tokens(command)
        target, verb = argv[1], argv[2]
        kind = {"/inheritance:r": "lock", "/setowner": "setowner", "/reset": "reset", "/grant:r": "grant"}[verb]
        self.acl_ops.append("%s %s" % (kind, target[len(ROOT) + 1:] or "folder"))
        rc = 5 if kind in self.icacls_fail else 0
        if kind == "grant" and target != ROOT and not self.exists(target):
            rc = 2
        if rc == 0:
            if kind == "lock":
                self.folder_acl = argv[3:]
            elif kind == "reset":
                assert target == ROOT + "\\*" and argv[3:] == ["/T", "/L"], argv
                self.grants = {f: g for f, g in self.grants.items() if not f.startswith(ROOT + "\\")}
            elif kind == "grant" and target != ROOT:
                entries = self.grants.setdefault(target, {})
                for i in range(3, len(argv), 2):
                    assert argv[i - 1] == "/grant:r", argv
                    sid, rights = argv[i].split(":", 1)
                    entries[sid] = rights
        self.stack.append(str(rc))

    def folder_probe(self, command):
        """The two powershell.exe probes of winsys.nsh: the audit (the one with a Queue) answers empty or clean from the file system, the status
        probe answers from folder_status."""
        if "Queue" in command:
            out = "clean" if [f for f in self.under(ROOT) if not f.endswith("\\.dir")] else "empty"
        else:
            out = {"abse": "absent", "fres": "fresh", "ours": "ours"}.get(self.folder_status, "foreign")
        self.acl_ops.append("audit" if "Queue" in command else "status")
        self.stack += [out + "\r\n", "0"]

    def rmdir(self, path):
        self.events.append("rmdir " + path[len(ROOT) + 1:])
        if path == ROOT + "\\program" and self.restore_failures > 0:
            self.restore_failures -= 1
            self.errors = True
            return
        for f in self.under(path):
            if not self.locked(f):
                del self.files[f]
        self.files.pop(path + "\\.dir", None)

    def copyfiles(self, src, dest):
        assert src.endswith("\\*.*"), src
        base = src[:-4]
        kind = "backup" if dest.startswith(ROOT + "\\backup") else "restore"
        self.events.append(kind + "-copy")
        files = [f for f in self.under(base) if not f.endswith("\\.dir")]
        if kind in self.fail or not files:
            self.errors = True
            return
        for f in files:
            self.files[dest + f[len(base):]] = self.files[f]

    def fileopen(self, var, path, mode):
        if mode == "r":
            if path not in self.files:
                self.errors = True
                return
            self.next_handle += 1
            self.set(var, "h%d" % self.next_handle)
            self.fh["h%d" % self.next_handle] = {"mode": "r", "path": path, "text": self.files[path], "pos": 0}
            return
        if path in self.fail or (path.endswith("installer-state.json") and "state" in self.fail):
            self.errors = True
            return
        self.events.append("write " + path[len(ROOT) + 1:])
        self.next_handle += 1
        self.set(var, "h%d" % self.next_handle)
        self.fh["h%d" % self.next_handle] = {"mode": "w", "path": path, "buf": []}

    def fileread(self, a):
        """One line, at most READ_LIMIT characters (the rest stays for the next read), line break included, as FileRead."""
        h = self.fh[self.var[a[0].lstrip("$")]]
        limit = int(self.expand(a[2])) if len(a) > 2 else self.READ_LIMIT
        rest = h["text"][h["pos"]:]
        if rest == "":
            self.errors = True
            self.set(a[1], "")
            return
        line = rest.splitlines(keepends=True)[0][:limit]
        h["pos"] += len(line)
        self.errors = False
        self.set(a[1], line)

    def write_file(self, dest):
        """File "/oname=..." : with SetOverwrite try a failure sets the error flag; with on or ifdiff NSIS asks Abort/Retry/Ignore, which a silent
        installer answers with Abort, exit code 2, before any IfErrors runs."""
        self.errors = False
        transient = self.swap_failures > 0
        if transient:
            self.swap_failures -= 1
        if "swap" in self.fail or transient or self.locked(dest):
            self.events.append("swap-failed")
            if self.overwrite == "try":
                self.errors = True
                return
            self.events.append("abort-box")
            self.exit_code = self.errorlevel = 2
            raise Quit()
        if self.overwrite == "ifdiff" and self.files.get(dest) == self.payload:
            return
        self.files[dest] = self.payload
        self.events.append("swap")

    def messagebox(self, a, labels):
        text = self.expand(a[1])
        default = a[a.index("/SD") + 1] if "/SD" in a else None
        answer = default if self.silent and default else self.answer
        if not (self.silent and default):
            self.boxes.append(text)
        for i, x in enumerate(a):
            if x in ("IDYES", "IDNO", "IDOK") and i > 1 and a[i - 1] != "/SD" and i + 1 < len(a) and x == answer:
                return labels[a[i + 1]]
        return None


# SL-16b: page creation (recorded only), nsExec::Exec (records the command line, answers a chosen code), Pop, IfFileExists, and the compile-time ENGINE_EXE define.
# ENGINE-1: nsExec::ExecToStack records its command line in self.stack_execs and, as nsexec.c (v310) does, pushes the output and then the exit code
# on top. Each call takes the next (code, output) of stack_answers; with none left it answers ("error", ""), what nsExec pushes when it cannot run.
# SL-21b: GetDlgItem (a handle that names the dialog and the control id) and EnableWindow (recorded in self.windows by handle).
def _sl16b_world_init(self, *a, exec_codes=None, shell_fails=False, stack_answers=None, **k):
    _sl16b_orig_init(self, *a, **k)
    self.shell_fails = shell_fails
    self.execs, self.exec_codes = [], list(exec_codes or [])
    self.stack_execs, self.stack_answers = [], list(stack_answers or [])
    self.windows = {}
    self.combos, self.callbacks = {}, {}
    self.var["PROGRAMFILES64"] = "C:\\Program Files"


def _sl16b_step(self, t, labels):
    op = t[0].lower()
    if op == "nsexec::exec":
        self.execs.append(tokens(self.expand(t[1])))
        self.stack.append(str(self.exec_codes.pop(0) if self.exec_codes else 0))
        return None
    if op == "nsexec::exectostack":
        self.stack_execs.append(tokens(self.expand(t[1])))
        rc, out = self.stack_answers.pop(0) if self.stack_answers else ("error", "")
        self.stack.append(out)
        self.stack.append(str(rc))
        return None
    if op.startswith(("nsdialogs::", "${nsd_create")):
        self.trace.append(t[0])
        if op == "nsdialogs::create":
            self.stack.append(self.dialog_result)
        elif op.startswith("${nsd_create"):
            self.stack.append("handle")
        return None
    if op == "getdlgitem":
        self.set(t[1], "%s/%s" % (self.expand(t[2]) or "parent", self.expand(t[3])))
        return None
    # #329 drop-down lists, keyed by the variable that holds the handle (as texts is): CB_ADDSTRING appends (the list has no CBS_SORT),
    # CB_RESETCONTENT empties the list and its selection, CB_SETCURSEL selects by index and clears the selection for an index out of range;
    # the selected item is what NSD_GetText reads. NSD_OnChange only records the callback: a test calls it as nsDialogs would.
    if op == "${nsd_cb_addstring}":
        self.combos.setdefault(t[1].lstrip("$"), []).append(self.expand(t[2]))
        return None
    if op == "${nsd_onchange}":
        self.callbacks[t[1].lstrip("$")] = t[2]
        return None
    if op == "sendmessage" and t[2] in ("${CB_RESETCONTENT}", "${CB_SETCURSEL}"):
        ctl = t[1].lstrip("$")
        items = self.combos.setdefault(ctl, [])
        if t[2] == "${CB_RESETCONTENT}":
            items.clear()
            self.texts[ctl] = ""
        else:
            n = int(self.expand(t[3]))
            self.texts[ctl] = items[n] if 0 <= n < len(items) else ""
        return None
    if op == "enablewindow":
        self.windows[self.expand(t[1])] = int(self.expand(t[2]))
        return None
    if op == "pop":
        self.set(t[1], self.stack.pop())
        return None
    if op == "iffileexists":
        target = t[2] if self.files.get(self.expand(t[1])) is not None else (t[3] if len(t) > 3 else "0")
        return None if target == "0" else labels[target]
    return _sl16b_orig_step(self, t, labels)


_sl16b_orig_init, _sl16b_orig_step = World.__init__, World.step
World.__init__, World.step = _sl16b_world_init, _sl16b_step
World.defines = {"ENGINE_EXE": ""}
