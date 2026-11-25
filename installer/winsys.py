"""Windows system adapter (ARCH-7 and ARCH-8): the real `system` that installer/runners.py and installer/update.py take.

Thin wrappers over sc.exe, icacls.exe, reg.exe and powershell.exe with FIXED argument lists: no shell, no secret on any
command line (the GitLab token only ever goes to config.toml), every expected failure a typed error. INST-REQ-036, 038,
040 to 043, 091 to 094. The process runner and the clock are injected, so tests prove the exact argv with fakes and
nothing here starts a process on import. Forge calls are injected too (`forge`), so this module opens no network."""
import ctypes
import hashlib
import os
import re
import struct
import subprocess
import time
from pathlib import Path

from installer import footprint, schema
from installer.runners import LogonRightMissing, RunnerError
from installer.update import UpdateError

PROGRAM_EXE = "program\\runner.exe"
FOLDER_SDDL = "O:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
VIRTUAL_PREFIX = "NT SERVICE\\"
FALLBACK_ROOT = "C:\\Windows"
_ROOT = re.compile(r"^[A-Za-z]:\\[A-Za-z0-9_ .\\-]*$")
_ACCOUNT = re.compile(r"^(NT SERVICE\\[A-Za-z0-9][A-Za-z0-9_.-]{0,63}|BUILTIN\\Administrators|NT AUTHORITY\\SYSTEM)$")
_DRIVE_PATH = re.compile(r"^[A-Za-z]:[\\/]")


def system_root(environ=None):
    root = (os.environ if environ is None else environ).get("SystemRoot", "")
    return root.rstrip("\\") if _ROOT.match(root) and ".." not in root else FALLBACK_ROOT


def tool(name):
    """Absolute path of a system tool, so a planted copy earlier on the search path is never run."""
    sub = "WindowsPowerShell\\v1.0\\" if name == "powershell.exe" else ""
    return "%s\\System32\\%s%s" % (system_root(), sub, name)


SC, ICACLS, REG, POWERSHELL = "sc.exe", "icacls.exe", "reg.exe", "powershell.exe"
RC_LOGON_FAILURE = 1069
RC_NOT_INSTALLED = 1060
RC_NOT_RUNNING = 1062
RC_MARKED_FOR_DELETE = 1072
RC_ALREADY_RUNNING = 1056
RC_CANNOT_ACCEPT_CONTROL = 1061
STATE_POLLS = 30
STOP_RETRY_SECONDS = (1, 2, 4, 8, 8, 8)
ADMIN_CHECK = ("([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent())"
               ".IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)")
_BAD = re.compile(r"[\x00-\x1f\"'`%^&|<>]")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_DOTDOT = re.compile(r"(^|[\\/])\.\.([\\/]|$)")
MAX_OUTPUT = 64 * 1024
_START_TYPES = {"auto": "AUTO_START", "demand": "DEMAND_START", "disabled": "DISABLED"}


class WinSysError(RunnerError, UpdateError):
    pass


class ServiceCommandFailed(WinSysError):
    pass


class ServiceTimeout(WinSysError):
    """The service did not reach the expected state in the bounded time."""


class ServiceNotStopped(ServiceCommandFailed):
    """The service kept refusing the stop command or never reached STOPPED."""


class LogonFailure(LogonRightMissing, WinSysError):
    pass


class UnsafeValue(WinSysError):
    pass


class FolderNotOurs(WinSysError):
    """The install folder exists and is not provably the installer's own (INST-REQ-030): nothing is written; an administrator removes it."""
    kind = "folder-not-ours"


class Result:
    def __init__(self, returncode, stdout=""):
        self.returncode, self.stdout = returncode, stdout


def subprocess_runner(argv):
    """The only place a process starts: fixed argv list, no shell, no input, bounded time."""
    try:
        p = subprocess.run(list(argv), capture_output=True, text=True, shell=False, stdin=subprocess.DEVNULL, timeout=120)
    except subprocess.TimeoutExpired as e:
        raise ServiceCommandFailed("%s did not finish in time" % argv[0]) from e
    return Result(p.returncode, (p.stdout or "")[:MAX_OUTPUT])


def _safe(value, what, name_only=False):
    if (not isinstance(value, str) or not value or _BAD.search(value) or _DOTDOT.search(value) or value.startswith("-")
            or (name_only and not _NAME.match(value))):
        raise UnsafeValue("the %s contains a character that is not allowed on a command line" % what)
    return value


def create_argv(name, account, folder):
    _safe(name, "service name", True)
    _safe(account, "service account")
    if account != VIRTUAL_PREFIX + name:
        raise UnsafeValue("the service account must be the dedicated virtual account of the service")
    folder = _safe(folder, "install folder")
    binpath = '"%s\\%s"' % (folder.rstrip("\\/"), PROGRAM_EXE)
    return [tool(SC), "create", name, "binPath=", binpath, "obj=", account, "start=", "auto"]


def acl_argv(path, accounts):
    """Removes inherited rights and grants only the listed accounts; the virtual service account gets read, the rest full control."""
    if not _DRIVE_PATH.match(str(path)):
        raise UnsafeValue("the config path must be an absolute drive path")
    argv = [tool(ICACLS), _safe(path, "config path"), "/inheritance:r"]
    for a in accounts:
        if not _ACCOUNT.match(a):
            raise UnsafeValue("the account is not one of the accounts the config file may be granted to")
        argv += ["/grant:r", "%s:(%s)" % (a, "R" if a.upper().startswith(VIRTUAL_PREFIX) else "F")]
    return argv


SID_SYSTEM, SID_ADMINISTRATORS = "S-1-5-18", "S-1-5-32-544"
FOLDER_RIGHTS_FULL, FOLDER_RIGHTS_SERVICE = "(OI)(CI)F", "(OI)(CI)RX"
# One line, no double quote (the NSIS mirror passes it as one quoted argument) and no backtick. @P@ is the single-quoted folder path.
# It prints absent, fresh (an empty directory), ours (valid state file) or foreign (a link, another owner, or anything else).
FOLDER_PROBE = (
    "$p='@P@';if(!(Test-Path -LiteralPath $p)){'absent';exit}"
    "$i=Get-Item -LiteralPath $p -Force;"
    "$o=(Get-Acl -LiteralPath $p).GetOwner([Security.Principal.SecurityIdentifier]).Value;"
    "if(!$i.PSIsContainer -or ($i.Attributes -band 1024) -or ($o -ne 'S-1-5-18' -and $o -ne 'S-1-5-32-544')){'foreign';exit}"
    "if(@(Get-ChildItem -LiteralPath $p -Force).Count -eq 0){'fresh';exit}"
    "$s=Join-Path $p 'installer-state.json';"
    "try{$f=Get-Item -LiteralPath $s -Force;$j=Get-Content -LiteralPath $s -Raw|ConvertFrom-Json;"
    "if(!($f.Attributes -band 1024) -and $j.schema_version -eq 1 -and $j.installer_version){'ours';exit}}catch{}'foreign'")
PROBE_WORDS = ("absent", "fresh", "ours")
# After the lock: walks the tree without following any link and prints links (a reparse point or a hard link anywhere),
# empty (no child at all), owners (a child owned by anyone but SYSTEM or Administrators) or clean. Any error ends non-zero.
FOLDER_AUDIT = (
    "$ErrorActionPreference='Stop';$p='@P@';$b=0;$w=0;$n=0;$q=New-Object System.Collections.Queue;$q.Enqueue($p);"
    "while($q.Count){$d=$q.Dequeue();foreach($c in @(Get-ChildItem -LiteralPath $d -Force)){$n++;"
    "if($c.Attributes -band 1024){$b=1;continue};"
    "if(!$c.PSIsContainer -and $c.LinkType -eq 'HardLink'){$b=1};"
    "$o=(Get-Acl -LiteralPath $c.FullName).GetOwner([Security.Principal.SecurityIdentifier]).Value;"
    "if($o -ne 'S-1-5-18' -and $o -ne 'S-1-5-32-544'){$w=1};"
    "if($c.PSIsContainer){$q.Enqueue($c.FullName)}}}"
    "if($b){'links'}elseif($n -eq 0){'empty'}elseif($w){'owners'}else{'clean'}")
AUDIT_WORDS = ("links", "empty", "owners", "clean")


def service_sid(name):
    """The well-known SID of a service's virtual account (SHA-1 of the upper-case name), usable before the service exists."""
    digest = hashlib.sha1(_safe(name, "service name", True).upper().encode("utf-16-le")).digest()
    return "S-1-5-80-" + "-".join(str(n) for n in struct.unpack("<5I", digest))


def folder_acl_argv(path, name, with_service=True):
    """The install folder's ACL (INST-REQ-030): inheritance removed; SYSTEM and Administrators full control, inherited by everything
    created later; the service account read and execute only; Users and Authenticated Users get nothing (no entry). Windows cannot
    resolve the service SID before the service exists (icacls rc 1332), so the first install locks with `with_service=False` and
    adds the service entry with service_grant_argv once the service exists and before it starts."""
    if not _DRIVE_PATH.match(str(path)):
        raise UnsafeValue("the install folder must be an absolute drive path")
    argv = [tool(ICACLS), _safe(path, "install folder"), "/inheritance:r"]
    grants = [(SID_SYSTEM, FOLDER_RIGHTS_FULL), (SID_ADMINISTRATORS, FOLDER_RIGHTS_FULL)]
    if with_service:
        grants.append((service_sid(name), FOLDER_RIGHTS_SERVICE))
    for sid, rights in grants:
        argv += ["/grant:r", "*%s:%s" % (sid, rights)]
    return argv


def service_grant_argv(path, name, rights=FOLDER_RIGHTS_SERVICE):
    """Adds the service account's entry (keeps every other entry); only valid once the service exists."""
    if not _DRIVE_PATH.match(str(path)):
        raise UnsafeValue("the install folder must be an absolute drive path")
    return [tool(ICACLS), _safe(path, "install folder"), "/grant:r", "*%s:%s" % (service_sid(name), rights)]


def folder_probe_argv(path):
    if not _DRIVE_PATH.match(str(path)):
        raise UnsafeValue("the install folder must be an absolute drive path")
    return [tool(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", FOLDER_PROBE.replace("@P@", _safe(path, "install folder"))]


def folder_audit_argv(path):
    if not _DRIVE_PATH.match(str(path)):
        raise UnsafeValue("the install folder must be an absolute drive path")
    return [tool(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", FOLDER_AUDIT.replace("@P@", _safe(path, "install folder"))]


def folder_reset_argvs(path):
    """Existing children only (the reset never names the folder itself). The setowner call does name the folder: that is fine, it is already owned by Administrators after the lock. No /C, so a per-file failure makes icacls exit non-zero and the install fails closed."""
    if not _DRIVE_PATH.match(str(path)):
        raise UnsafeValue("the install folder must be an absolute drive path")
    p = _safe(path, "install folder")
    return [[tool(ICACLS), p, "/setowner", "*" + SID_ADMINISTRATORS, "/T", "/L"],
            [tool(ICACLS), p + "\\*", "/reset", "/T", "/L"]]


def parse_qc(text):
    """Reads `sc qc` output into a definition: binary, account, start type."""
    out = {}
    for line in text.splitlines():
        key, _, val = line.strip().partition(":")
        key = key.strip()
        val = val.strip()
        if key == "BINARY_PATH_NAME":
            out["binary"] = val
        elif key == "SERVICE_START_NAME":
            out["account"] = val
        elif key == "START_TYPE":
            word = val.split()[-1] if val else ""
            out["start"] = next((k for k, v in _START_TYPES.items() if v == word), "auto")
    return out


class FolderDescriptorError(WinSysError):
    """Cannot prepare the protected descriptor; do not fall back to inherited permissions."""
    kind = "folder-descriptor-failed"


def create_secure_folder(path):
    if os.name != "nt":
        raise FolderDescriptorError("secure install folder creation requires Windows")

    class SecurityAttributes(ctypes.Structure):
        _fields_ = [("length", ctypes.c_uint32), ("descriptor", ctypes.c_void_p), ("inherit_handle", ctypes.c_int32)]

    convert = ctypes.WinDLL("advapi32", use_last_error=True).ConvertStringSecurityDescriptorToSecurityDescriptorW
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    convert.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint32)]
    convert.restype = ctypes.c_int32
    kernel.CreateDirectoryW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(SecurityAttributes)]
    kernel.CreateDirectoryW.restype = ctypes.c_int32
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p

    descriptor = ctypes.c_void_p()
    if not convert(FOLDER_SDDL, 1, ctypes.byref(descriptor), None):
        raise FolderDescriptorError("could not convert the install folder security descriptor (Win32 %d)" % ctypes.get_last_error())
    try:
        attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, 0)
        if not kernel.CreateDirectoryW(path, ctypes.byref(attributes)):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.LocalFree(descriptor)


class WinSystem:
    def __init__(self, folder, name=None, version="", run=subprocess_runner, sleep=time.sleep, forge=None, mkdir=create_secure_folder):
        fp = footprint.load_footprint()
        self.name = name or fp["service"]["name"]
        self.account = fp["service"]["account"]
        self.entry_key = fp["uninstall_entry"]["key"]
        self.folder, self.version = str(folder), version
        self._run, self._sleep, self.forge, self._mkdir = run, sleep, forge, mkdir

    def _sc(self, *args, ok=(0,)):
        r = self._run([tool(SC), *args])
        if r.returncode not in ok:
            raise ServiceCommandFailed("sc.exe %s failed with code %d" % (args[0], r.returncode))
        return r

    def is_elevated(self):
        r = self._run([tool(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", ADMIN_CHECK])
        return r.returncode == 0 and r.stdout.strip().lower() == "true"

    def has_logon_right(self, account):
        """The virtual service account carries the log-on-as-a-service right by construction; any other account is refused here
        and the real answer comes at start (LogonFailure)."""
        return account.upper().startswith(VIRTUAL_PREFIX) and account.split("\\", 1)[1] == self.name

    def restrict_acl(self, path, accounts):
        r = self._run(acl_argv(path, accounts))
        if r.returncode != 0:
            raise ServiceCommandFailed("icacls.exe failed with code %d" % r.returncode)

    def folder_status(self):
        """absent, fresh, ours or foreign; anything unexpected (a failed probe, odd output) is foreign: it fails closed."""
        try:
            r = self._run(folder_probe_argv(self.folder))
        except OSError:
            return "foreign"
        word = (r.stdout or "").strip().lower()
        return word if r.returncode == 0 and word in PROBE_WORDS else "foreign"

    def folder_audit(self):
        try:
            r = self._run(folder_audit_argv(self.folder))
        except OSError:
            return "error"
        word = (r.stdout or "").strip().lower()
        return word if r.returncode == 0 and word in AUDIT_WORDS else "error"

    def _icacls(self, argv):
        r = self._run(argv)
        if r.returncode != 0:
            raise ServiceCommandFailed("icacls.exe failed with code %d" % r.returncode)

    def lock_folder(self):
        """Refuses a folder that is not ours, applies the folder ACL, then audits the children (the folder is already closed to
        standard users, so nothing can change between the audit and what follows). A fresh folder must still be empty: any child
        was planted before the lock and the folder is refused. A folder that is ours (upgrade, repair, rollback, an older
        installer's) must hold no link and no hard link; every child is then handed to Administrators and gets the folder's ACL.
        Idempotent and never looser."""
        status = self.folder_status()
        if status not in ("fresh", "ours"):
            raise FolderNotOurs("the install folder exists and was not created by this installer; nothing was changed. "
                                "An administrator must remove or rename it first")
        self._icacls(folder_acl_argv(self.folder, self.name, with_service=self.service_exists()))
        found = self.folder_audit()
        if status == "fresh":
            if found != "empty":
                raise FolderNotOurs("something was placed in the new install folder before it was locked; nothing was installed. "
                                    "An administrator must delete the folder %s first" % self.folder)
            return
        if found not in ("clean", "owners"):
            raise FolderNotOurs("the install folder holds a link or a hard link (or could not be checked); nothing was changed. "
                                "An administrator must remove it, or delete the folder, first")
        for argv in folder_reset_argvs(self.folder):
            self._icacls(argv)
        if self.folder_audit() != "clean":
            raise FolderNotOurs("the files in the install folder could not be handed to Administrators; nothing more was changed. "
                                "An administrator must delete the folder first")

    def prepare_folder(self):
        """First install: refuse a foreign folder, create it if absent, then lock it before anything is written into it."""
        status = self.folder_status()
        if status == "foreign":
            raise FolderNotOurs("the install folder exists and was not created by this installer; nothing was installed. "
                                "An administrator must remove or rename it first")
        if status == "absent":
            try:
                self._mkdir(self.folder)
            except OSError as e:
                raise FolderNotOurs("could not securely create the install folder %s; nothing was installed: %s" % (self.folder, e)) from e
        self.lock_folder()

    def install_service(self, name, account, folder, files=()):
        """Create, then give the service SID its read-and-execute on the folder (and read on `files`, which have their own ACL),
        then start. The SID resolves only once the service exists; a failed grant removes the service and leaves the folder locked."""
        self._sc(*create_argv(name, account, folder)[1:])
        try:
            self._sc("sidtype", name, "unrestricted")
            self._icacls(service_grant_argv(folder, name))
            for f in files:
                self._icacls(service_grant_argv(f, name, "(R)"))
            self.start_service(name)
        except BaseException:
            self._cleanup(name)
            raise

    def _cleanup(self, name):
        """A half-installed service is removed, best effort, so the next try starts clean."""
        for verb in ("stop", "delete"):
            try:
                if verb == "stop" and name == self.name:
                    self.stop_service()
                else:
                    self._run([tool(SC), verb, name])
            except Exception:
                pass

    def service_exists(self):
        return self._sc("query", self.name, ok=(0, RC_NOT_INSTALLED)).returncode == 0

    def start_service(self, name=None):
        r = self._run([tool(SC), "start", name or self.name])
        if r.returncode == RC_LOGON_FAILURE:
            raise LogonFailure("logon failure: %s could not log on as a service" % self.account)
        if r.returncode not in (0, RC_ALREADY_RUNNING):
            raise ServiceCommandFailed("sc.exe start failed with code %d" % r.returncode)
        self._wait_state("RUNNING", name or self.name)

    def _query_state(self, name):
        """The state word of `sc query` (RUNNING, STOPPED, START_PENDING ...), or None when the service is not installed."""
        r = self._sc("query", name, ok=(0, RC_NOT_INSTALLED))
        if r.returncode != 0:
            return None
        m = re.search(r"STATE\s*:\s*\d+\s+([A-Z_]+)", r.stdout)
        return m.group(1) if m else ""

    def _wait_state(self, want, name):
        """Bounded poll of `sc query` until the service is in the wanted state; a typed error otherwise, never a hang.
        Worst case about STATE_POLLS seconds of sleeping plus the query time (each `sc query` runs up to the runner's own 120 s limit)."""
        state = ""
        for _ in range(STATE_POLLS):
            state = self._query_state(name)
            if state == want or (want == "STOPPED" and state is None):
                return
            if want == "RUNNING" and state in ("STOPPED", None):
                raise ServiceCommandFailed("the service stopped or vanished right after it was started")
            self._sleep(1)
        raise ServiceTimeout("the service did not reach %s in %d seconds (last state %s)" % (want, STATE_POLLS, state or "unknown"))

    def stop_service(self):
        """Stop and wait for STOPPED. 1061 (cannot accept control yet) is retried with a bounded backoff, then typed."""
        for delay in STOP_RETRY_SECONDS + (None,):
            r = self._run([tool(SC), "stop", self.name])
            if r.returncode in (RC_NOT_RUNNING, RC_NOT_INSTALLED):
                return
            if r.returncode == 0:
                self._wait_state("STOPPED", self.name)
                return
            if r.returncode != RC_CANNOT_ACCEPT_CONTROL:
                raise ServiceCommandFailed("sc.exe stop failed with code %d" % r.returncode)
            if delay is None:
                raise ServiceNotStopped("the service kept refusing the stop command (code %d)" % r.returncode)
            self._sleep(delay)

    def delete_service(self):
        """Idempotent: a service that is already gone (or marked for deletion) is not an error."""
        self.stop_service()
        self._sc("delete", self.name, ok=(0, RC_NOT_INSTALLED, RC_MARKED_FOR_DELETE))

    def service_definition(self):
        d = parse_qc(self._sc("qc", self.name).stdout)
        d["name"] = self.name
        return d

    def apply_service_definition(self, d):
        if d.get("name") != self.name:
            raise UnsafeValue("the saved service definition is for another service")
        args = ["config", self.name]
        if "binary" in d:
            binary = d["binary"]
            if not isinstance(binary, str) or binary.count('"') % 2:
                raise UnsafeValue("the saved binary path has unbalanced quotes")
            _safe(binary.replace('"', ""), "saved binary path")
            args += ["binPath=", binary]
        if "account" in d:
            if d["account"] != VIRTUAL_PREFIX + self.name:
                raise UnsafeValue("the saved account is not the dedicated virtual account")
            args += ["obj=", d["account"]]
        if d.get("start") in _START_TYPES:
            args += ["start=", d["start"]]
        self._sc(*args)

    def _state(self):
        return self._query_state(self.name) == "RUNNING"

    def stays_running(self, seconds):
        """Running now and still running at each second until `seconds` have passed (INST-REQ-040 health check)."""
        for _ in range(int(seconds)):
            if not self._state():
                return False
            self._sleep(1)
        return self._state()

    def runner_online(self):
        if self.forge is not None:
            return self.forge.runner_online() is True
        return self._state()

    def forge_reachable(self):
        return self.forge is not None and self.forge.reachable() is True

    def unregister_runner(self):
        return self.forge is not None and self.forge.unregister() is True

    def _reg(self, *args, ok=(0,)):
        r = self._run([tool(REG), *args, "/reg:64"])
        if r.returncode not in ok:
            raise ServiceCommandFailed("reg.exe %s failed with code %d" % (args[0], r.returncode))
        return r

    def uninstall_entry_exists(self):
        return self._reg("query", self.entry_key, ok=(0, 1)).returncode == 0

    def write_uninstall_entry(self):
        folder = _safe(self.folder, "install folder")
        values = (("DisplayName", "Ecosystem Runner"), ("InstallLocation", folder),
                  ("UninstallString", '"%s\\uninstall.exe"' % folder.rstrip("\\/")))
        if self.version:
            values += (("DisplayVersion", _safe(self.version, "version")),)
        for k, v in values:
            self._reg("add", self.entry_key, "/v", k, "/t", "REG_SZ", "/d", v, "/f")

    def remove_uninstall_entry(self):
        self._reg("delete", self.entry_key, "/f", ok=(0, 1))


def exit_code(error=None):
    """The process exit code of a refusal: 0, or the code footprint.json names for its kind (39 for a folder that is not ours)."""
    if isinstance(error, FolderDescriptorError):
        return schema.load_schema()["exit_codes"][error.kind]
    return 0 if error is None else int(footprint.load_footprint()["exit_codes"][error.kind])


def main(argv=None, system=None):
    """`python -m installer.winsys prepare-folder FOLDER`: the first-install folder step for the Python path. Returns the exit code."""
    import sys
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2 or args[0] != "prepare-folder":
        print("usage: python -m installer.winsys prepare-folder FOLDER", file=sys.stderr)
        return 2
    try:
        (system or WinSystem(args[1])).prepare_folder()
    except FolderNotOurs as e:
        print("folder-not-ours: %s" % e, file=sys.stderr)
        return exit_code(e)
    except FolderDescriptorError as e:
        print("folder-descriptor: %s" % e, file=sys.stderr)
        return exit_code(e)
    return exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
