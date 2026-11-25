"""UNINST (ecosystem-control#64): the uninstall path hardened. INST-REQ-043, 078, 084.
U1 (Python): uninstall.exe is owned and a read-only file no longer stops the removal.
U2 (NSIS): wait for the service to stop, read every result, retry the folder, keep the uninstall entry when something is left.
U3 (NSIS): un.onInit refuses a non-administrator before anything is touched.
UNINSTC (NSIS): uninstall.exe is deleted last, after the contents, so a leftover can never take it along (RMDir /r would).
UNINSTD (Python): the same order in update.OWNED: uninstall.exe is its last name, so no stuck file can lose it before the entry.
The NSIS logic cannot run on this host (the guest run proves it for real). Its control flow is tested by running the instruction subset
that uninstall.nsh uses (class Nsis) against a scripted Windows; the text is pinned and compiled with makensis -WX. No network."""
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from installer import footprint, update, winsys
from installer.guest import pack
from tests.test_installer_update import Base, FakeSystem

ROOT = Path(__file__).resolve().parent.parent
NSIS = ROOT / "installer" / "nsis"
UNINSTALL = (NSIS / "uninstall.nsh").read_text()
ELEVATE = (NSIS / "elevate.nsh").read_text()
INSTALL = (NSIS / "install.nsh").read_text()
README = (ROOT / "installer" / "README.md").read_text()
FOLDER = r"C:\ProgramData\EcosystemRunner"
ENTRY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\EcosystemRunner"
SC = r'"$SYSDIR\sc.exe"'


def body(text, name):
    m = re.search(rf"^Function {re.escape(name)}\b(.*?)^FunctionEnd", text, re.S | re.M)
    assert m, name
    return m.group(1)


def code(text):
    return "\n".join(l for l in text.splitlines() if l.strip() and not l.lstrip().startswith(";"))


def tree_text(prefix="un."):
    """The functions tree.nsh defines under `prefix`, as the macro expands them (what `!include "tree.nsh"` brings into uninstall.nsh)."""
    text = (NSIS / "tree.nsh").read_text()
    m = re.search(r"^!macro Tree_Define P\n(.*?)^!macroend", text, re.S | re.M)
    assert m, "tree.nsh has no Tree_Define macro"
    root = re.search(r"^!define TREE_ROOT (\S+)$", text, re.M).group(1)
    return m.group(1).replace("${P}", prefix).replace("${TREE_ROOT}", root)


class Quit(Exception):
    pass


class Escaped(AssertionError):
    """The code asked about a path above the product folder (a walk that went up through a ".." entry)."""


class Runaway(AssertionError):
    """A walk that never ends (an entry named "." or ".." that is entered again and again): far more paths asked about than any real tree needs."""


def inside(path, rel):
    return rel == "" or path == rel or path.startswith(rel + "\\")


class World:
    """A scripted Windows: the service answers from lists (the last answer repeats). The folder holds `files` (paths relative to it, with
    backslashes; their parents are real folders, `dirs` adds empty ones). Delete and RMDir /r do what Windows does: they remove everything
    they can reach and leave a `locked` file and the folders above it. `unlock_after` releases the locks after that many seconds of Sleep;
    `stuck_folder`: even the empty folder cannot be removed (something holds it).
    SL-23, reparse points: `links` maps a path in the folder to (kind "dir" or "file", the absolute target or None for a dangling link);
    the key "" makes the folder itself a link. `outside` holds the absolute files the links point to. As on a real Windows guest (MEASURED: probe
    P1, and GUEST7A, winev-run-afbbd3e1) the recursive RMDir FOLLOWS a directory link and empties its target; the plain RMDir removes a directory
    link and never its target and leaves a file link; Delete removes a file link and does nothing to a directory link; a code that lists or
    enters a link sees the target. `attr_errors`, `attr_blank` and `attr_flagged` name the attribute reads that fail: a path (every read of that
    entry) or a pair (path, attribute) for one read, for example the DIRECTORY read of a link (see `attributes`)."""

    def __init__(self, stop=(0,), query=("STOPPED",), delete=(0,), files=(), locked=(), unlock_after=None, stuck_folder=False,
                 admin=True, silent=True, exedir=r"C:\Users\u\AppData\Local\Temp\~nsu.tmp", exefile="Au_.exe",
                 dirs=(), links=None, outside=(), attr_errors=(), attr_blank=(), attr_flagged=(), list_errors=(), stuck_links=()):
        self.answers = {"stop": list(stop), "query": list(query), "delete": list(delete)}
        self.files, self.locked, self.unlock_after = set(files), set(locked), unlock_after
        self.stuck_folder, self.folder, self.slept = stuck_folder, True, 0
        self.admin, self.silent, self.exedir, self.exefile = admin, silent, exedir, exefile
        self.links, self.outside, self.attr_errors = dict(links or {}), set(outside), set(attr_errors)
        self.attr_blank, self.attr_flagged = set(attr_blank), set(attr_flagged)
        self.list_errors, self.stuck_links = set(list_errors), set(stuck_links)
        self.asked = []  # every path the code asked about, as written (before "." and ".." are resolved)
        self.listed = []  # every folder a FindFirst was run on, so a test can show that a link was never entered
        self.dirs = set(dirs)
        for p in (*self.files, *self.dirs, *self.links):
            parts = p.split("\\")
            self.dirs |= {"\\".join(parts[:i]) for i in range(1, len(parts))}

    def run(self, verb):
        a = self.answers[verb]
        answer = a.pop(0) if len(a) > 1 else a[0]
        if verb != "query":
            return answer
        if isinstance(answer, int) or answer == "error":
            return answer, ""
        state = {"RUNNING": "4  RUNNING\n                                (STOPPABLE, NOT_PAUSABLE, ACCEPTS_SHUTDOWN)",
                 "STOP_PENDING": "3  STOP_PENDING", "STOPPED": "1  STOPPED"}[answer]
        return 0, "SERVICE_NAME: EcosystemRunner\n        TYPE               : 10  WIN32_OWN_PROCESS\n        STATE              : " + state

    def rel(self, path):
        """The path below the product folder. As on Windows, "." and ".." are resolved first (an entry named "." is the folder itself, ".." its
        parent), so a walk that does not skip them really loops or climbs; `asked` keeps what was written."""
        assert path == FOLDER or path.startswith(FOLDER + "\\"), path
        raw = path[len(FOLDER) + 1:]
        self.asked.append(raw)
        if len(self.asked) > 5000:
            raise Runaway(raw)
        parts = []
        for seg in raw.split("\\"):
            if seg in ("", "."):
                continue
            if seg == "..":
                if not parts:
                    raise Escaped(path)
                parts.pop()
            else:
                parts.append(seg)
        return "\\".join(parts)

    def split(self, rel):
        """(link, rest) when the path runs through a link (the code entered it), else (None, rel)."""
        if "" in self.links:
            return "", rel
        parts = rel.split("\\")
        for i in range(1, len(parts) + 1):
            head = "\\".join(parts[:i])
            if head in self.links:
                return head, "\\".join(parts[i:])
        return None, rel

    def isdir(self, path):
        rel = self.rel(path)
        link, rest = self.split(rel)
        if link is not None:
            kind, target = self.links[link]
            return rest == "" and kind == "dir" and target is not None
        return self.folder if rel == "" else rel in self.dirs

    def exists(self, path):
        if path.endswith("\\*.*"):  # how NSIS asks whether a directory exists
            return self.isdir(path[:-4])
        rel = self.rel(path)
        link, rest = self.split(rel)
        if link is not None:  # a link exists even when it dangles; below it only what the target holds
            return rest == "" or (self.links[link][1] is not None and self.links[link][1] + "\\" + rest in self.outside)
        return self.folder if rel == "" else rel in self.files or rel in self.dirs

    def listing(self, path):
        assert path.endswith("\\*.*"), path
        rel = self.rel(path[:-4])
        self.listed.append(rel)
        if rel in self.list_errors:  # a folder that cannot be listed answers with an empty first name, not even "." or ".."
            return []
        link, rest = self.split(rel)
        if link is not None:  # a code that lists a link lists what it points to
            target = self.links[link][1]
            if target is None or rest != "":
                return []
            return [".", ".."] + sorted(f.rsplit("\\", 1)[1] for f in self.outside if f.rsplit("\\", 1)[0] == target)
        if not self.isdir(path[:-4]):
            return []
        under = [p for p in (*self.files, *self.dirs, *self.links) if inside(p, rel) and p != rel]
        return [".", ".."] + sorted({p[len(rel) + 1 if rel else 0:].split("\\")[0] for p in under})

    def delete(self, path):
        rel = self.rel(path)
        link, rest = self.split(rel)
        if link is not None:
            kind, target = self.links[link]
            if rest == "" and kind == "file":
                del self.links[link]  # Delete removes a file link, never what it points to; a folder link it refuses
            elif rest and target is not None:
                self.outside.discard(target + "\\" + rest)
            return
        if rel not in self.locked:
            self.files.discard(rel)

    def follow(self, link):
        """What the recursive RMDir does with a link it meets: it empties the target (probe P1) and removes the link."""
        target = self.links.pop(link)[1]
        if target is not None:
            self.outside = {f for f in self.outside if not f.startswith(target + "\\")}

    def rmdir(self, path, recursive):
        rel = self.rel(path)
        link, rest = self.split(rel)
        if link is not None:
            if rest == "" and self.links[link][0] == "dir":  # RMDir works on directories only; a file link it leaves
                if recursive:
                    self.follow(link)
                elif link not in self.stuck_links:
                    del self.links[link]  # MEASURED (GUEST7A): the plain RMDir removes the link itself, whether its target is full, empty or gone
            return
        if recursive:
            for l in [l for l in self.links if inside(l, rel)]:
                self.follow(l)
            self.files = {f for f in self.files if not inside(f, rel) or f in self.locked}
            self.dirs = {d for d in self.dirs if not inside(d, rel) or any(inside(f, d) for f in self.files)}
        elif rel != "" and rel in self.dirs and not any(inside(p, rel) and p != rel for p in (*self.files, *self.dirs, *self.links)):
            self.dirs.discard(rel)
        if rel == "" and not (self.files or self.dirs or self.links) and not self.stuck_folder:
            self.folder = False

    def remove_directory(self, path):
        """The Win32 RemoveDirectoryW as Microsoft documents it: it removes the directory entry itself, so a junction or a directory symbolic
        link goes as a link (never its target), a real folder only when it is empty. Answers 1 or 0. `stuck_links`: links whose removal fails
        (an open handle holds them). The tree code gives it the path WITHOUT a trailing backslash, the form SL-23 pins; GUEST7A measured that
        Windows treats both forms alike."""
        assert not path.endswith("\\"), "the tree code must give RemoveDirectoryW the path without a trailing backslash: " + path
        rel = self.rel(path)
        link, rest = self.split(rel)
        if link is not None:
            if rest != "" or link == "" or self.links[link][0] != "dir" or link in self.stuck_links:
                return 0
            del self.links[link]
            return 1
        if rel != "" and rel in self.dirs and not any(inside(p, rel) and p != rel for p in (*self.files, *self.dirs, *self.links)):
            self.dirs.discard(rel)
            return 1
        return 0

    def attributes(self, path, name):
        """What the FileFunc macro reads from the entry itself, never from what a link points to: (answer, error flag). The real macro answers
        "1" or "0", or empty with the flag set. `attr_errors` is that failure; `attr_blank` and `attr_flagged` give the two half-failed answers
        the code must distrust on their own: empty with the flag clear, and the true answer with the flag set. Each holds paths (every read of
        the entry) or pairs (path, attribute) (that one read: the second read of a link is DIRECTORY)."""
        rel = self.rel(path)
        link, rest = self.split(rel)

        def hit(failing):
            return rel in failing or (rel, name) in failing

        if hit(self.attr_errors):
            return "", True
        if hit(self.attr_blank):
            return "", False
        if link is not None:
            kind, target = self.links[link]
            if rest == "":
                return {"REPARSE_POINT": "1", "DIRECTORY": "1" if kind == "dir" else "0"}[name], hit(self.attr_flagged)
            return ("0", hit(self.attr_flagged)) if target is not None and target + "\\" + rest in self.outside else ("", True)
        if not self.exists(path):
            return "", True
        return {"REPARSE_POINT": "0", "DIRECTORY": "1" if self.isdir(path) else "0"}[name], hit(self.attr_flagged)

    def sleep(self, ms):
        self.slept += ms
        if self.unlock_after is not None and self.slept >= self.unlock_after * 1000:
            self.locked = set()


class Nsis:
    """Runs the NSIS subset that uninstall.nsh uses. An instruction it does not know raises, so a new one forces this class to grow."""

    def __init__(self, text, world):
        self.w, self.fn = world, self.parse(text + ("\n" + tree_text() if '!include "tree.nsh"' in text else ""))
        self.v = {"SYSDIR": r"C:\Windows\System32", "APPDATA": r"C:\ProgramData", "EXEDIR": world.exedir, "EXEFILE": world.exefile}
        self.stack, self.log, self.sleeps, self.boxes, self.keys, self.finds, self.errorlevel = [], [], [], [], [], {}, 0
        self.errors, self.handles = False, 0  # the error flag; the last find handle handed out
        self.ops, self.called = [], []  # `log` holds the sc verbs; `ops` the Delete and RMDir calls; `called` every Call

    @property
    def open_handles(self):
        """The FindFirst handles that no FindClose has closed yet (a missing FindClose leaks one)."""
        return len(self.finds)

    @staticmethod
    def parse(text):
        fns, cur, blocks = {}, None, []
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith(";"):
                continue
            head = re.fullmatch(r'Function (\S+)|Section "Uninstall"', line)
            if head:
                cur, blocks = fns.setdefault(head.group(1) or "section", ([], {})), []
                continue
            if line in ("FunctionEnd", "SectionEnd"):
                cur = None
                continue
            if cur is None:
                continue
            ops, labels = cur
            if re.fullmatch(r"\w+:", line):
                labels[line[:-1]] = len(ops)
                continue
            t = footprint._tokens(line)
            op, args = t[0].lower(), t[1:]
            if op in ("${if}", "${ifnot}"):
                blocks.append(len(ops))
                ops.append(["if", op == "${ifnot}", args, None])
            elif op == "${else}":
                i = blocks.pop()
                blocks.append(len(ops))
                ops.append(["jump", None])
                ops[i][3] = len(ops)
            elif op == "${endif}":
                i = blocks.pop()
                ops[i][3 if ops[i][0] == "if" else 1] = len(ops)
            else:
                ops.append([op, args])
        return fns

    def s(self, text):
        return re.sub(r"\$(\w+)", lambda m: str(self.v.get(m.group(1), m.group(0))), text)

    def cond(self, c):
        if c == ["${Silent}"]:
            return self.w.silent
        a, op, b = c
        a, b = self.s(a), self.s(b)
        if op == "==":
            return a.lower() == b.lower()
        return int(a) < int(b) if op == "<" else int(a) > int(b)

    def start(self, name):
        """Runs one function (or "section"); True when the script quit."""
        try:
            self.call(name)
        except Quit:
            return True
        return False

    def call(self, name):
        self.called.append(name)
        ops, labels = self.fn[name]
        pc = 0
        while pc < len(ops):
            o = ops[pc]
            pc = self.step(o, labels, pc + 1)

    def jump(self, dest, labels, pc):
        return pc if dest == "0" else labels[dest]

    def step(self, o, labels, pc):
        op = o[0]
        if op == "jump":
            return o[1]
        if op == "if":
            return pc if self.cond(o[2]) != o[1] else o[3]
        a = o[1]
        if op == "strcpy":
            val = self.s(a[1])[int(self.s(a[3])) if len(a) > 3 else 0:]
            self.v[a[0][1:]] = val[:int(self.s(a[2]))] if len(a) > 2 else val
        elif op == "intop":
            x, y = int(self.s(a[1])), int(self.s(a[3]))
            self.v[a[0][1:]] = str(x + y if a[2] == "+" else x - y if a[2] == "-" else x * y)
        elif op == "strcmp":
            eq = self.s(a[0]).lower() == self.s(a[1]).lower()
            return self.jump(a[2] if eq else (a[3] if len(a) > 3 else "0"), labels, pc)
        elif op == "goto":
            return labels[a[0]]
        elif op == "return":
            return 1 << 30  # past the last instruction of the function
        elif op == "iffileexists":
            return self.jump(a[1] if self.w.exists(self.s(a[0])) else (a[2] if len(a) > 2 else "0"), labels, pc)
        elif op == "clearerrors":
            self.errors = False
        elif op == "iferrors":
            return self.jump(a[0] if self.errors else (a[1] if len(a) > 1 else "0"), labels, pc)
        elif op in ("${un.getfileattributes}", "${getfileattributes}"):
            # the FileFunc macro: "1" or "0", or an empty answer with the error flag set; on success it leaves the flag as it was
            answer, flag = self.w.attributes(self.s(a[0]), self.s(a[1]))
            if flag:
                self.errors = True
            self.v[a[2][1:]] = answer
        elif op == "sleep":
            self.sleeps.append(int(self.s(a[0])))
            self.w.sleep(self.sleeps[-1])
        elif op == "push":
            self.stack.append(self.s(a[0]))
        elif op == "pop":
            self.v[a[0][1:]] = self.stack.pop()
        elif op == "exch":  # Exch $var: the variable and the top of the stack swap places
            name = a[0][1:]
            self.v[name], self.stack[-1] = self.stack[-1], self.v.get(name, "")
        elif op == "system::call":
            m = re.fullmatch(r'kernel32::RemoveDirectoryW\(w "(.*)"\) i \.s', self.s(" ".join(a)))
            if not m:
                raise AssertionError("System call not supported by the test interpreter: " + " ".join(a))
            self.ops.append("removedirectory " + (self.w.rel(m.group(1)) or "."))
            self.stack.append(str(self.w.remove_directory(m.group(1))))
        elif op == "call":
            self.call(a[0])
        elif op in ("nsexec::exec", "nsexec::exectostack"):
            verb = self.s(" ".join(a)).rsplit(" ", 2)[-2]
            self.log.append(verb)
            r = self.w.run(verb)
            rc, out = r if isinstance(r, tuple) else (r, "")
            if op.endswith("tostack"):
                self.stack.append(out)
            self.stack.append(str(rc))
        elif op == "delete":
            path = self.s(a[0])
            self.ops.append("delete " + self.w.rel(path))
            self.w.delete(path)
        elif op == "rmdir":
            path, recursive = self.s([x for x in a if not x.startswith("/")][0]), "/r" in [x.lower() for x in a]
            self.ops.append(("rmdir /r " if recursive else "rmdir ") + (self.w.rel(path) or "."))
            self.w.rmdir(path, recursive)
        elif op == "findfirst":
            found = iter(self.w.listing(self.s(a[2])))
            first = self.v[a[1][1:]] = next(found, "")
            self.v[a[0][1:]] = ""
            if first:
                self.handles += 1
                self.finds[str(self.handles)] = found
                self.v[a[0][1:]] = str(self.handles)
        elif op == "findnext":
            self.v[a[1][1:]] = next(self.finds.get(self.v.get(a[0][1:]), iter(())), "")
        elif op == "findclose":
            self.finds.pop(self.v.get(a[0][1:]), None)
        elif op == "deleteregkey":
            self.keys.append(self.s(a[1]))
        elif op == "messagebox":
            if not (self.w.silent and "/SD" in a):
                self.boxes.append(self.s(a[1]))
        elif op == "seterrorlevel":
            self.errorlevel = int(a[0])
        elif op == "quit":
            raise Quit
        elif op == "userinfo::getaccounttype":
            self.stack.append("Admin" if self.w.admin else "User")
        elif op not in ("setshellvarcontext", "setregview"):
            raise AssertionError("NSIS instruction not supported by the test interpreter: " + op)
        return pc


def windows_like_unlink(real, denied=()):
    """os.unlink as Windows has it: a read-only file is refused (PermissionError) until its bit is cleared; names in `denied` always."""
    def unlink(path, *, dir_fd=None):
        st = os.stat(path, dir_fd=dir_fd, follow_symlinks=False)
        if not stat.S_ISLNK(st.st_mode) and (not st.st_mode & stat.S_IWRITE or Path(path).name in denied):
            raise PermissionError(13, "Access is denied", str(path))
        return real(path, dir_fd=dir_fd)
    return unlink


class U1OwnedAndReadOnly(Base):
    def setUp(self):
        super().setUp()
        self.state()
        (self.root / "uninstall.exe").write_text("nsis-uninstaller")

    def readonly(self, *parts):
        p = self.root.joinpath(*parts)
        p.chmod(stat.S_IREAD)
        return p

    def windows(self, denied=()):
        patcher = mock.patch("os.unlink", windows_like_unlink(os.unlink, denied))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_uninstall_exe_is_owned_so_the_folder_goes_u1(self):
        """U1, 043, 084: the NSIS install writes uninstall.exe into the folder; the removal owns it, so the folder itself goes."""
        rep = update.uninstall(self.root, FakeSystem())
        self.assertFalse(self.root.exists())
        self.assertEqual(rep.removed, ["service", "folder", "keys", "uninstall entry"])
        self.assertNotIn("other files kept", rep.text())

    def test_every_file_the_nsis_install_writes_into_the_folder_is_owned_u1(self):
        """U1: each WriteUninstaller target of install.nsh is a plain name in OWNED, so a file the install adds cannot be forgotten again."""
        names = re.findall(r'WriteUninstaller\s+"\$APPDATA\\EcosystemRunner\\([^"\\]+)"', INSTALL)
        self.assertEqual(names, ["uninstall.exe"])
        for name in names:
            self.assertIn(name, update.OWNED)

    def test_a_foreign_file_still_keeps_the_folder_u1(self):
        """043: owning uninstall.exe does not widen the removal; a file the installer did not write stays and so does the folder."""
        (self.root / "notes.txt").write_text("mine")
        rep = update.uninstall(self.root, FakeSystem())
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["notes.txt"])
        self.assertIn("other files kept", rep.text())

    def test_a_read_only_file_in_program_no_longer_stops_the_uninstall_u1(self):
        """U1: Windows refuses to delete a read-only file; the bit is cleared and the delete retried once, so the folder goes."""
        self.readonly("program", "runner.exe")
        self.windows()
        rep = update.uninstall(self.root, FakeSystem())
        self.assertFalse(self.root.exists())
        self.assertEqual(rep.removed, ["service", "folder", "keys", "uninstall entry"])

    def test_a_read_only_single_file_of_the_folder_is_removed_too_u1(self):
        """U1: the same for the files that sit directly in the folder (config.toml, uninstall.exe)."""
        self.readonly("config.toml")
        self.readonly("uninstall.exe")
        self.windows()
        update.uninstall(self.root, FakeSystem())
        self.assertFalse(self.root.exists())

    def test_a_file_that_stays_denied_still_stops_the_uninstall_as_before_u1(self):
        """U1: one retry only. When the file still cannot go the error is the one raised before: UninstallStopped caused by PermissionError."""
        self.readonly("program", "runner.exe")
        self.windows(denied=("runner.exe",))
        with self.assertRaises(update.UninstallStopped) as cm:
            update.uninstall(self.root, FakeSystem())
        self.assertIsInstance(cm.exception.__cause__, PermissionError)
        self.assertIn("uninstall stopped after: service (PermissionError", str(cm.exception))
        self.assertTrue((self.root / "program" / "runner.exe").exists())

    def test_a_stuck_file_in_program_leaves_uninstall_exe_and_the_entry_c(self):
        """UNINSTC, the Python mirror of the NSIS order: uninstall.exe comes after program in OWNED, so while program cannot be removed it
        stays, and so does the uninstall entry."""
        self.windows(denied=("runner.exe",))
        system = FakeSystem()
        with self.assertRaises(update.UninstallStopped):
            update.uninstall(self.root, system)
        self.assertTrue((self.root / "uninstall.exe").exists())
        self.assertTrue(system.entry_present)

    def assert_a_stuck_file_keeps_the_uninstaller_and_the_entry(self, name):
        """UNINSTD: `name` is refused for good (Windows keeps a file that is open). Everything before it in OWNED is removed, so the stop
        must find `name`, uninstall.exe and the uninstall entry all still there: the uninstall can be run again."""
        self.windows(denied=(name,))
        system = FakeSystem()
        with self.assertRaises(update.UninstallStopped):
            update.uninstall(self.root, system)
        self.assertTrue((self.root / name).exists())
        self.assertTrue((self.root / "uninstall.exe").exists())
        self.assertTrue(system.entry_present)

    def test_a_stuck_state_file_leaves_uninstall_exe_and_the_entry_d(self):
        """UNINSTD (REV96C): the state file came after uninstall.exe in OWNED, so a stuck one had already lost uninstall.exe, the bug
        UNINSTC fixed in uninstall.nsh. The test above only covers program, which is earlier in OWNED."""
        self.assert_a_stuck_file_keeps_the_uninstaller_and_the_entry(update.STATE_FILE)

    def test_a_stuck_state_temp_file_leaves_uninstall_exe_and_the_entry_d(self):
        (self.root / (update.STATE_FILE + ".tmp")).write_text("{}")
        self.assert_a_stuck_file_keeps_the_uninstaller_and_the_entry(update.STATE_FILE + ".tmp")

    def test_uninstall_exe_is_the_last_owned_name_d(self):
        """UNINSTD: pins the order the two tests above rely on, as in uninstall.nsh; a name added to OWNED later goes before it."""
        self.assertEqual(update.OWNED[-1], "uninstall.exe")
        self.assertEqual(update.OWNED.count("uninstall.exe"), 1)

    def test_the_hook_clears_the_bit_and_retries_exactly_once_u1(self):
        f = self.readonly("config.toml")
        seen, real = [], os.unlink

        def unlink(path, **kw):
            seen.append(bool(os.stat(path).st_mode & stat.S_IWRITE))
            return real(path, **kw)
        with mock.patch("os.unlink", unlink):
            update._clear_readonly_and_retry(os.unlink, str(f), PermissionError(13, "Access is denied"))
        self.assertEqual(seen, [True])
        self.assertFalse(f.exists())

    def test_a_second_failure_raises_the_original_error_u1(self):
        d = self.root / "program"
        original = PermissionError(13, "Access is denied", str(d))
        with self.assertRaises(PermissionError) as cm:
            update._clear_readonly_and_retry(os.rmdir, str(d), original)
        self.assertIs(cm.exception, original)
        self.assertTrue(d.exists())

    def test_other_errors_pass_through_unchanged_and_nothing_is_touched_u1(self):
        f = self.root / "config.toml"
        for exc, func in ((FileNotFoundError(2, "gone"), os.unlink), (OSError(5, "io"), os.unlink), (PermissionError(13, "denied"), os.open)):
            with self.subTest(exc=exc, func=func.__name__):
                with self.assertRaises(type(exc)) as cm:
                    update._clear_readonly_and_retry(func, str(f), exc)
                self.assertIs(cm.exception, exc)
        self.assertTrue(f.exists())

    def test_the_hook_never_follows_a_link_u1(self):
        target = self.tmp / "outside.txt"
        target.write_text("keep")
        target.chmod(stat.S_IREAD)
        link = self.root / "link"
        link.symlink_to(target)
        with self.assertRaises(PermissionError):
            update._clear_readonly_and_retry(os.unlink, str(link), PermissionError(13, "denied"))
        self.assertFalse(os.stat(target).st_mode & stat.S_IWRITE)
        self.assertTrue(link.is_symlink())


class EntrySystem(FakeSystem):
    """Notes what is already gone at the moment the uninstall entry is removed."""
    def __init__(self, root):
        super().__init__()
        self.root, self.at_entry = root, None

    def remove_uninstall_entry(self):
        self.at_entry = {"service": self.service_present, "folder": self.root.exists()}
        super().remove_uninstall_entry()


class UninstallEntryLastAndNamedRemains(Base):
    """UNINSTB: the reference model removes the uninstall entry last, like uninstall.nsh, and a stop names what is left (044, 045)."""
    def setUp(self):
        super().setUp()
        self.state()
        (self.root / "uninstall.exe").write_text("nsis-uninstaller")

    def deny(self, *names):
        patcher = mock.patch("os.unlink", windows_like_unlink(os.unlink, names))
        patcher.start()
        self.addCleanup(patcher.stop)

    def stopped(self, system):
        with self.assertRaises(update.UninstallStopped) as cm:
            update.uninstall(self.root, system)
        return cm.exception

    def left(self):
        return [str(p) for p in sorted(self.root.iterdir())]

    def test_the_uninstall_entry_is_removed_last_b1(self):
        """The entry goes when the service and the folder are already gone, as in uninstall.nsh."""
        s = EntrySystem(self.root)
        rep = update.uninstall(self.root, s)
        self.assertEqual(s.at_entry, {"service": False, "folder": False})
        self.assertEqual(rep.removed, ["service", "folder", "keys", "uninstall entry"])
        self.assertEqual(rep.remaining, [])
        self.assertEqual(s.calls, ["delete_service", "remove_uninstall_entry"])

    def test_the_entry_stays_while_the_folder_is_not_gone_b1(self):
        """A file that cannot be deleted stops the run before the entry step; the entry stays like the file does."""
        self.deny("runner.exe")
        s = FakeSystem()
        self.stopped(s)
        self.assertTrue(s.entry_present)
        self.assertNotIn("remove_uninstall_entry", s.calls)
        self.assertFalse(s.service_present)
        self.assertTrue((self.root / "program" / "runner.exe").exists())

    def test_a_failing_entry_step_leaves_the_entry_and_the_rerun_finishes_b1(self):
        """084: the entry step is last, so the folder is already gone when it fails; running again removes service and entry."""
        s = FakeSystem(fail="remove_uninstall_entry")
        err = self.stopped(s)
        self.assertFalse(self.root.exists())
        self.assertTrue(s.entry_present)
        self.assertEqual(err.report.removed, ["service", "folder", "keys"])
        self.assertEqual(err.report.remaining, ["uninstall entry"])
        self.assertIn("after: service, folder, keys (OSError); remaining: uninstall entry; run it again", str(err))
        again = FakeSystem()
        rep = update.uninstall(self.root, again)
        self.assertEqual(again.calls, ["delete_service", "remove_uninstall_entry"])
        self.assertEqual(rep.removed, ["service", "uninstall entry"])
        self.assertFalse(again.entry_present)

    def test_a_folder_that_is_gone_is_accepted_only_under_the_right_name_b1(self):
        """043: the re-run above needs a missing folder to pass the check; a missing folder that is not the installer's own does not."""
        shutil.rmtree(self.root)
        real = self.tmp / "real"
        real.mkdir()
        (self.tmp / "via").symlink_to(real)
        dangling = self.tmp / "x" / "EcosystemRunner"
        dangling.parent.mkdir()
        dangling.symlink_to(self.tmp / "nowhere")
        for bad in (self.tmp / "Other", self.tmp / "EcosystemRunner2", self.tmp / "via" / "EcosystemRunner", dangling):
            with self.subTest(root=str(bad)):
                s = FakeSystem()
                with self.assertRaises(update.UnsafeFolder):
                    update.uninstall(bad, s)
                self.assertEqual(s.calls, [])
        s = FakeSystem()
        with self.assertRaises(update.UnsafeFolder):
            update.uninstall(self.root, s, state_dir=self.tmp / "state")
        self.assertEqual(s.calls, [])
        update.uninstall(self.root, s)
        self.assertEqual(s.calls, ["delete_service", "remove_uninstall_entry"])

    def test_a_stop_at_the_service_names_what_remains_b2(self):
        """044, 045: message and report list the service, every path still in the folder and the entry; nothing was removed."""
        err = self.stopped(FakeSystem(fail="delete_service"))
        paths = self.left()
        self.assertTrue(str(err).startswith("uninstall stopped after: nothing (OSError)"))
        self.assertIn("remaining: service, " + ", ".join(paths) + ", uninstall entry; run it again", str(err))
        self.assertEqual(err.report.removed, [])
        self.assertEqual(err.report.remaining, ["service"] + paths + ["uninstall entry"])
        self.assertIn(str(self.root / "program"), err.report.text())
        self.assertIsNone(update.UninstallStopped("x").report)

    def test_a_stop_in_the_folder_names_the_file_and_the_paths_left_b2(self):
        """044, 045: the file that could not go is named with the cause, and so is every path still in the folder."""
        self.deny("runner.exe")
        err = self.stopped(FakeSystem())
        self.assertIn("uninstall stopped after: service (PermissionError at %s); remaining: " % err.__cause__.filename, str(err))
        self.assertIn("remaining: " + ", ".join(self.left()) + ", uninstall entry; run it again", str(err))
        self.assertEqual(err.report.removed, ["service"])
        self.assertEqual(err.report.remaining, self.left() + ["uninstall entry"])
        self.assertIn(str(self.root / "program"), err.report.remaining)

    def test_the_stop_report_keeps_the_forge_place_and_claims_nothing_unconfirmed_b2(self):
        """044, 045: a stop does not lose the place to delete by hand; the registration is called removed only when confirmed."""
        self.state(mode="gitlab", address="https://gl.example/")
        s = FakeSystem(fail="delete_service")
        s.reachable = False
        err = self.stopped(s)
        self.assertEqual(err.report.leftovers, [{"forge": "gitlab", "place": "https://gl.example/admin/runners"}])
        self.assertIn("still to do at the gitlab: delete this runner by hand at https://gl.example/admin/runners", err.report.text())
        self.assertNotIn("confirmed", err.report.text())
        self.assertFalse(err.report.unregistered)
        err = self.stopped(FakeSystem(fail="delete_service"))
        self.assertTrue(err.report.unregistered)
        self.assertEqual(err.report.leftovers, [])
        self.assertIn("confirmed", err.report.text())

    def test_the_report_names_the_foreign_files_that_kept_the_folder_b2(self):
        """043, 045: a file the installer did not write keeps the folder; the report names it, and the entry still goes."""
        (self.root / "notes.txt").write_text("mine")
        rep = update.uninstall(self.root, FakeSystem())
        self.assertEqual(rep.removed, ["service", "folder contents (other files kept)", "keys", "uninstall entry"])
        self.assertEqual(rep.remaining, [str(self.root / "notes.txt")])
        self.assertIn("other files kept", rep.text())
        self.assertIn("remaining: " + str(self.root / "notes.txt"), rep.text())


def service(world, name="un.Uninstall_RemoveService"):
    n = Nsis(UNINSTALL, world)
    return n, n.start(name)


class U2Service(unittest.TestCase):
    def test_the_service_is_polled_until_stopped_then_deleted_u2(self):
        """U2, 084: after sc stop the state is queried until STOPPED (a state word that only looks similar is not enough), then sc delete."""
        n, quit_ = service(World(query=("RUNNING", "STOP_PENDING", "STOPPED")))
        self.assertFalse(quit_)
        self.assertEqual(n.log, ["stop", "query", "query", "query", "delete"])
        self.assertEqual(n.sleeps, [1000, 1000])

    def test_a_service_that_never_stops_ends_the_uninstall_before_it_is_deleted_u2(self):
        """U2: 30 polls, one second apart (winsys.STATE_POLLS), then the uninstall stops with code 40; nothing is deleted."""
        n, quit_ = service(World(query=("RUNNING",), silent=False))
        self.assertTrue(quit_)
        self.assertEqual(n.log, ["stop"] + ["query"] * winsys.STATE_POLLS)
        self.assertEqual(n.sleeps, [1000] * (winsys.STATE_POLLS - 1))
        self.assertEqual(n.errorlevel, 40)
        self.assertIn("did not stop within 30 seconds", n.boxes[-1])

    def test_a_stop_refused_with_1061_is_retried_with_the_python_backoff_u2(self):
        """U2: winsys.STOP_RETRY_SECONDS (1, 2, 4, 8, 8, 8 s): seven tries, then the uninstall stops with code 40 and nothing else is done."""
        n, quit_ = service(World(stop=(winsys.RC_CANNOT_ACCEPT_CONTROL,)))
        self.assertTrue(quit_)
        self.assertEqual(n.log, ["stop"] * (len(winsys.STOP_RETRY_SECONDS) + 1))
        self.assertEqual(n.sleeps, [s * 1000 for s in winsys.STOP_RETRY_SECONDS])
        self.assertEqual(n.errorlevel, 40)

    def test_a_stop_that_works_on_a_retry_goes_on_u2(self):
        n, quit_ = service(World(stop=(1061, 1061, 0)))
        self.assertFalse(quit_)
        self.assertEqual(n.log, ["stop", "stop", "stop", "query", "delete"])
        self.assertEqual(n.sleeps, [1000, 2000])

    def test_a_service_that_is_not_there_or_not_running_is_fine_u2(self):
        for rc in (winsys.RC_NOT_INSTALLED, winsys.RC_NOT_RUNNING):
            with self.subTest(rc=rc):
                n, quit_ = service(World(stop=(rc,), delete=(winsys.RC_NOT_INSTALLED,)))
                self.assertFalse(quit_)
                self.assertEqual((n.log, n.sleeps), (["stop", "delete"], []))

    def test_a_service_that_vanishes_while_polled_counts_as_stopped_u2(self):
        n, quit_ = service(World(query=("RUNNING", winsys.RC_NOT_INSTALLED)))
        self.assertFalse(quit_)
        self.assertEqual(n.log, ["stop", "query", "query", "delete"])

    def test_unexpected_results_end_the_uninstall_with_code_40_u2(self):
        """U2: the results of stop, query and delete were ignored; now anything not listed is a stopped uninstall (nsExec's "error" is not 0)."""
        for what, world in (("stop 5", World(stop=(5,))), ("stop error", World(stop=("error",))), ("query 5", World(query=(5,))),
                            ("delete 5", World(delete=(5,))), ("delete error", World(delete=("error",)))):
            with self.subTest(what=what):
                n, quit_ = service(world)
                self.assertTrue(quit_)
                self.assertEqual(n.errorlevel, 40)

    def test_a_delete_of_a_service_marked_for_deletion_is_fine_u2(self):
        for rc in (0, winsys.RC_NOT_INSTALLED, winsys.RC_MARKED_FOR_DELETE):
            with self.subTest(rc=rc):
                self.assertFalse(service(World(delete=(rc,)))[1])


def files(world):
    n = Nsis(UNINSTALL, world)
    return n, n.start("un.Uninstall_RemoveFiles")


class U2Files(unittest.TestCase):
    def test_a_removed_folder_is_followed_by_the_entry_u2(self):
        w = World(files={"program", "uninstall.exe"})
        n, quit_ = files(w)
        self.assertFalse(quit_)
        self.assertEqual((n.keys, n.sleeps, w.folder), ([ENTRY], [], False))
        self.assertEqual(n.ops, ["delete program", "delete uninstall.exe", "rmdir ."])

    def test_a_locked_file_is_retried_five_times_then_the_entry_is_kept_u2(self):
        """U2, 084, commander (b): runner.exe may still be mapped. Five retries, one second apart; when the folder is still there the
        uninstall entry stays and the run ends with code 40. In the default start no exit code reaches the caller: folder and entry ARE the signal."""
        w = World(files={"uninstall.exe", "runner.exe"}, locked={"runner.exe"}, silent=False)
        n, quit_ = files(w)
        self.assertTrue(quit_)
        self.assertEqual(n.called.count("un.Uninstall_ClearFolder"), 6)
        self.assertEqual(n.sleeps, [1000] * 5)
        self.assertEqual(n.keys, [])
        self.assertEqual(n.errorlevel, 40)
        self.assertIn("uninstall entry was kept", n.boxes[-1])
        self.assertEqual(w.files, {"uninstall.exe", "runner.exe"})

    def test_a_file_released_during_the_retries_lets_the_run_finish_u2(self):
        w = World(files={"uninstall.exe", "runner.exe"}, locked={"runner.exe"}, unlock_after=2)
        n, quit_ = files(w)
        self.assertFalse(quit_)
        self.assertEqual((n.called.count("un.Uninstall_ClearFolder"), n.sleeps, n.keys), (3, [1000, 1000], [ENTRY]))
        self.assertEqual((w.files, w.folder), (set(), False))

    def test_started_in_place_the_running_uninstaller_alone_is_not_a_leftover_u2(self):
        """uninstall.exe /S _?=<folder> runs the file inside the folder and a running file cannot delete itself; it alone is not a leftover."""
        n, quit_ = files(World(files={"uninstall.exe"}, locked={"uninstall.exe"}, exedir=FOLDER, exefile="uninstall.exe"))
        self.assertFalse(quit_)
        self.assertEqual((n.ops, n.sleeps, n.keys, n.errorlevel), (["delete uninstall.exe", "rmdir ."], [], [ENTRY], 0))

    def test_started_in_place_any_other_file_is_still_a_leftover_u2(self):
        both = {"uninstall.exe", "runner.exe"}
        n, quit_ = files(World(files=both, locked=both, exedir=FOLDER, exefile="uninstall.exe"))
        self.assertTrue(quit_)
        self.assertEqual((n.keys, n.errorlevel, len(n.sleeps)), ([], 40, 5))

    def test_started_by_the_registered_strings_a_stuck_uninstall_exe_is_a_leftover_u2(self):
        """The default start runs a copy from TEMP, so the folder's uninstall.exe is not running; if it is still there something holds it."""
        n, quit_ = files(World(files={"uninstall.exe"}, locked={"uninstall.exe"}))
        self.assertTrue(quit_)
        self.assertEqual((n.keys, n.errorlevel), ([], 40))

    def test_a_file_named_like_the_running_one_counts_when_the_running_one_is_elsewhere_u2(self):
        """The exemption is for the file that is running: a same-named file in the folder, while a copy runs from another folder, is a leftover."""
        n, quit_ = files(World(files={"uninstall.exe"}, locked={"uninstall.exe"}, exedir=r"C:\Users\u\Desktop", exefile="uninstall.exe"))
        self.assertTrue(quit_)
        self.assertEqual((n.keys, n.errorlevel), ([], 40))

    def test_the_whole_uninstall_runs_in_order_and_stops_at_the_first_failure_u2(self):
        """084: service first, folder second, entry last, and a stopped service touches neither folder nor entry."""
        w = World(files={"program"})
        n = Nsis(UNINSTALL, w)
        self.assertFalse(n.start("section"))
        self.assertEqual((n.log, n.keys, w.files), (["stop", "query", "delete"], [ENTRY], set()))
        self.assertEqual(n.ops, ["delete program", "delete uninstall.exe", "rmdir ."])
        w = World(query=("RUNNING",), files={"program"})
        n = Nsis(UNINSTALL, w)
        self.assertTrue(n.start("section"))
        self.assertEqual((n.keys, w.files, n.ops, "delete" in n.log), ([], {"program"}, [], False))


class UninstallExeGoesLastC(unittest.TestCase):
    """UNINSTC, measured on the real guest: RMDir /r deletes everything it can reach, uninstall.exe included, even when a locked file keeps
    the folder, and the uninstall entry then pointed at nothing. So the contents go first; uninstall.exe, the folder and the entry only
    when nothing else is left."""

    TREE = {"uninstall.exe", "program\\runner.exe", "program\\lib.dll", "config.toml", "state\\db.json"}

    def section(self, **kw):
        w = World(**kw)
        n = Nsis(UNINSTALL, w)
        return w, n, n.start("section")

    def test_a_locked_leftover_in_the_default_start_keeps_uninstall_exe_and_the_entry_c(self):
        """The registered strings start a copy from TEMP: the service is gone, exit code 40, the key and uninstall.exe stay."""
        w, n, quit_ = self.section(files=self.TREE, locked={"program\\runner.exe"}, silent=False)
        self.assertTrue(quit_)
        self.assertEqual((n.errorlevel, n.keys), (40, []))
        self.assertEqual(w.files, {"uninstall.exe", "program\\runner.exe"})
        self.assertNotIn("delete uninstall.exe", n.ops)
        self.assertEqual((n.log.count("delete"), n.sleeps), (1, [1000] * 5))
        self.assertIn("Run the uninstall again", n.boxes[-1])

    def test_the_same_started_in_place_keeps_uninstall_exe_and_the_entry_c(self):
        w, n, quit_ = self.section(files=self.TREE, locked={"program\\runner.exe", "uninstall.exe"}, exedir=FOLDER, exefile="uninstall.exe")
        self.assertTrue(quit_)
        self.assertEqual((n.errorlevel, n.keys, w.files), (40, [], {"uninstall.exe", "program\\runner.exe"}))
        self.assertEqual(n.sleeps, [1000] * 5)

    def test_nothing_locked_removes_everything_with_uninstall_exe_and_the_folder_last_then_the_entry_c(self):
        w, n, quit_ = self.section(files=self.TREE)
        self.assertFalse(quit_)
        self.assertEqual((w.files, w.folder, n.keys, n.errorlevel, n.sleeps), (set(), False, [ENTRY], 0, []))
        self.assertEqual(n.ops, ["delete config.toml", "delete program\\lib.dll", "delete program\\runner.exe", "rmdir program",
                                 "delete state\\db.json", "rmdir state", "delete uninstall.exe", "rmdir ."])

    def test_a_lock_released_during_the_retries_lets_the_whole_run_finish_c(self):
        w, n, quit_ = self.section(files=self.TREE, locked={"program\\runner.exe"}, unlock_after=2)
        self.assertFalse(quit_)
        self.assertEqual((w.files, w.folder, n.keys, n.sleeps), (set(), False, [ENTRY], [1000, 1000]))
        self.assertEqual(n.ops[-2:], ["delete uninstall.exe", "rmdir ."])
        self.assertEqual(n.ops.count("delete uninstall.exe"), 1)

    def test_an_empty_folder_that_cannot_go_ends_the_entry_and_names_the_folder_c(self):
        """The one edge, decided: uninstall.exe is already deleted, so nothing can be run again. The entry goes, the message names the
        folder to delete by hand (no 'run again'), and the exit code stays 40."""
        w, n, quit_ = self.section(files={"uninstall.exe"}, stuck_folder=True, silent=False)
        self.assertTrue(quit_)
        self.assertEqual((n.errorlevel, n.keys, w.files, w.folder), (40, [ENTRY], set(), True))
        self.assertIn(FOLDER, n.boxes[-1])
        self.assertNotIn("Run the uninstall again", n.boxes[-1])
        self.assertEqual(n.sleeps, [1000] * 5)

    def test_every_service_stop_message_still_says_to_run_the_uninstall_again_c(self):
        """The advice moved from un.Uninstall_Stopped into its callers (the edge above must not say it): each service step keeps it."""
        for answers in ({"stop": (5,)}, {"query": ("RUNNING",)}, {"query": ("error",)}, {"delete": (5,)}):
            with self.subTest(answers):
                n = Nsis(UNINSTALL, World(silent=False, **answers))
                self.assertTrue(n.start("un.Uninstall_RemoveService"))
                self.assertIn("Run the uninstall again", n.boxes[-1])


class U3AdminGate(unittest.TestCase):
    def test_a_non_administrator_in_silent_mode_exits_38_and_touches_nothing_u3(self):
        """U3, 078: nothing is touched before the gate; the code is the footprint's not-elevated."""
        n = Nsis(UNINSTALL, World(admin=False, silent=True))
        self.assertTrue(n.start("un.onInit"))
        self.assertEqual((n.errorlevel, n.log, n.boxes, n.keys), (38, [], [], []))

    def test_a_non_administrator_in_interactive_mode_gets_one_message_u3(self):
        n = Nsis(UNINSTALL, World(admin=False, silent=False))
        self.assertTrue(n.start("un.onInit"))
        self.assertEqual((n.errorlevel, n.log, n.keys), (38, [], []))
        self.assertEqual(len(n.boxes), 1)
        self.assertIn("administrator", n.boxes[0])

    def test_an_administrator_passes_the_gate_u3(self):
        for silent in (True, False):
            with self.subTest(silent=silent):
                n = Nsis(UNINSTALL, World(admin=True, silent=silent))
                self.assertFalse(n.start("un.onInit"))
                self.assertEqual((n.errorlevel, n.log, n.boxes), (0, [], []))

    def test_the_gate_code_is_the_footprints_not_elevated_code_u3(self):
        gate = body(UNINSTALL, "un.onInit")
        self.assertEqual(int(re.search(r"SetErrorLevel (\d+)", gate).group(1)), footprint.load_footprint()["exit_codes"]["not-elevated"])
        self.assertLess(gate.index("Call un.Elevate_IsAdmin"), gate.index("SetErrorLevel"))
        self.assertLess(gate.index("SetErrorLevel"), gate.index("Quit"))

    def test_the_un_admin_check_is_the_install_check_under_an_un_name_u3(self):
        """U3: the same UserInfo test as Elevate_IsAdmin (elevate.nsh); uninstaller code can only call un. functions, hence the copy."""
        want = body(ELEVATE, "Elevate_IsAdmin").replace("elev_isadmin", "unelev_isadmin")
        self.assertIn("UserInfo::GetAccountType", want)
        self.assertEqual(body(UNINSTALL, "un.Elevate_IsAdmin"), want)

    def test_the_file_is_self_contained_for_the_guest_harness_u3(self):
        """The guest harness includes uninstall.nsh alone: it brings LogicLib and its own variable, not elevate.nsh's."""
        self.assertRegex(UNINSTALL, r'(?m)^!include "LogicLib.nsh"$')
        self.assertRegex(UNINSTALL, r"(?m)^Var unelev_isadmin$")
        self.assertNotIn("$elev_isadmin", UNINSTALL.replace("$unelev_isadmin", ""))


class Pins(unittest.TestCase):
    def test_the_entry_is_deleted_once_and_only_after_the_folder_check_u2(self):
        """U2, commander (b): the leftover path never reaches DeleteRegKey."""
        text = code(UNINSTALL)
        self.assertEqual(text.count("DeleteRegKey"), 1)
        b = body(UNINSTALL, "un.Uninstall_RemoveFiles")
        self.assertGreater(b.index("DeleteRegKey"), b.index("\nforget_entry:\n"))
        leftover = b[b.index("\nkept:\n"):b.index("\nfolder_stuck:\n")]
        self.assertIn("the uninstall entry was kept", leftover)
        self.assertIn("Call un.Uninstall_Stopped", leftover)
        self.assertNotIn("DeleteRegKey", leftover)
        self.assertNotIn("DeleteRegKey", body(UNINSTALL, "un.Uninstall_Stopped"))

    def test_the_contents_are_cleared_before_uninstall_exe_and_the_folder_go_c(self):
        """UNINSTC: removing the folder takes uninstall.exe along even when a locked file keeps the folder, so it runs only after the
        contents are cleared and uninstall.exe is deleted; ClearFolder never touches uninstall.exe and never removes the folder itself.
        SL-23: the folder goes with the plain RMDir (a recursive one follows a junction), the contents through un.Tree_Remove."""
        b = code(body(UNINSTALL, "un.Uninstall_RemoveFiles"))
        delete_self = 'Delete "$APPDATA\\EcosystemRunner\\uninstall.exe"'
        rmdir_all = 'RMDir "$APPDATA\\EcosystemRunner"'
        self.assertEqual((b.count(delete_self), b.count(rmdir_all)), (1, 1))
        self.assertLess(b.index("remove_again:"), b.index("Call un.Uninstall_ClearFolder"))
        self.assertLess(b.index("Call un.Uninstall_ClearFolder"), b.index(delete_self))
        self.assertLess(b.index(delete_self), b.index(rmdir_all))
        self.assertLess(b.index(rmdir_all), b.index("DeleteRegKey"))
        clear = code(body(UNINSTALL, "un.Uninstall_ClearFolder"))
        self.assertIn('StrCmp $4 "uninstall.exe" clear_skip', clear)
        self.assertRegex(clear, r'Push "\$4"\s+Call un\.Tree_Remove')
        self.assertNotIn(rmdir_all, clear)

    def test_a_stopped_uninstall_has_its_own_exit_code_u2(self):
        """U2: update.UninstallStopped has no numeric code anywhere before; 40 is new, keyed by its kind in footprint.json (winsys.exit_code)."""
        codes = footprint.load_footprint()["exit_codes"]
        self.assertEqual(codes["uninstall-stopped"], 40)
        self.assertEqual(update.UninstallStopped.kind, "uninstall-stopped")
        self.assertEqual(winsys.exit_code(update.UninstallStopped("x")), 40)
        stopped = body(UNINSTALL, "un.Uninstall_Stopped")
        self.assertRegex(stopped, r"SetErrorLevel 40\s+Quit\s*$")
        self.assertEqual(len(set(codes.values())), len(codes))
        used = {int(c) for f in NSIS.iterdir() if f.name != "uninstall.nsh" for c in re.findall(r"SetErrorLevel (\d+)", f.read_text())}
        schema = json.loads((ROOT / "installer" / "schema.json").read_text())["exit_codes"].values()
        self.assertNotIn(40, used | set(schema))

    def test_the_footprint_check_passes_and_lists_the_query_command_u2(self):
        self.assertEqual(footprint.check_source(footprint.collect_sources()), [])
        entry = [e for e in footprint.load_footprint()["exec_allowed"]
                 if e["file"] == "uninstall.nsh" and e["function"] == "un.Uninstall_RemoveService"]
        self.assertEqual(len(entry), 1)
        self.assertEqual(entry[0]["commands"], [f"{SC} {verb} EcosystemRunner" for verb in ("stop", "query", "delete")])

    def test_a_command_outside_the_listed_ones_is_refused_u2(self):
        srcs = footprint.collect_sources()
        bad = dict(srcs, **{"uninstall.nsh": srcs["uninstall.nsh"].replace("query EcosystemRunner'", "query Other'")})
        self.assertTrue(footprint.check_source(bad))

    def test_registered_uninstall_strings_are_unchanged_and_have_no_in_place_switch_d(self):
        """Commander (d): UninstallString and QuietUninstallString stay as registered; neither carries _?= (see the README)."""
        found = dict(re.findall(r'"(UninstallString|QuietUninstallString)" (.+)$', INSTALL, re.M))
        self.assertEqual(found, {"UninstallString": r"""'"$APPDATA\EcosystemRunner\uninstall.exe"'""",
                                 "QuietUninstallString": r"""'"$APPDATA\EcosystemRunner\uninstall.exe" /S'"""})
        self.assertNotIn("_?=", code(INSTALL))

    def test_the_readme_says_what_a_caller_can_see_in_each_start_form_a(self):
        """Commander (a), (c): measured on the guest, written down."""
        for needle in ("`_?=`", "default start", "no exit code", "standard user", "exit code 40", "exit code 38", "uninstall entry",
                       "cannot delete itself"):
            self.assertIn(needle, README)


@unittest.skipUnless(shutil.which("makensis"), "makensis absent")
class Compile(unittest.TestCase):
    def test_main_nsi_compiles_with_warnings_as_errors(self):
        with tempfile.TemporaryDirectory() as d:
            shutil.copytree(NSIS, Path(d) / "nsis")
            r = subprocess.run(["makensis", "-WX", "-V1", f"-DOUTFILE={d}/o.exe", str(Path(d) / "nsis" / "main.nsi")],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_the_guest_harness_still_compiles_from_uninstall_nsh_alone_with_warnings_as_errors_u3(self):
        pins = json.loads((ROOT / "installer" / "pins.json").read_text())
        with tempfile.TemporaryDirectory() as d:
            cmd = pack.harness_command("makensis", pins, ROOT / "installer" / "guest" / "uninstall-harness.nsi", Path(d) / "h.exe")
            cmd.insert(1, "-WX")
            r = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
