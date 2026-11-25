"""Update, rollback, repair and uninstall (ARCH-8, ARCH-9) and the extension's version-skew check (ARCH-13).

INST-REQ-011, 037 to 045, 081 to 084, 095, 096. Layout of the install folder `root`: `program/` holds the program files and is the
only part an update replaces; `backup/` is the update backup; everything else (config.toml, logs/, keys/, runner-forge.json,
the state file) is kept. The system, the forge and the clock are injected, so tests use fakes and this module opens no network.
Every refusal is a typed error; no secret is read, printed or logged here."""
import json
import os
import re
import shutil
import time
import stat
from pathlib import Path

from installer import footprint, licences, log, runners
from installer.schema import SchemaError, StateNotWritable

STATE_FILE = "installer-state.json"
PROGRAM = "program"
BACKUP = "backup"
SERVICE_FILE = "service.json"
COMPLETE = "complete"  # written last into backup/, removed first on success: only a finished backup is a restore point
KEYS = "keys"
HEALTH_SECONDS = 30
RESTORED = "previous program files restored"
STATE_SCHEMA = Path(__file__).resolve().parent / "state.schema.json"
VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
STEPS = ("backup", "stop", "swap", "start", "health")
FORGE_PLACES = {"github": "/settings/actions/runners", "gitlab": "/admin/runners"}


class UpdateError(SchemaError):
    kind = "update-error"


class BadVersion(UpdateError):
    kind = "bad-version"


class MajorVersionMismatch(UpdateError):
    kind = "major-version-mismatch"


class StateMissing(UpdateError):
    kind = "state-missing"


class StateInvalid(UpdateError):
    kind = "state-invalid"


class NothingToUpdate(UpdateError):
    kind = "nothing-to-update"


class RestoreFailed(UpdateError):
    kind = "restore-failed"


class BackupFailed(UpdateError):
    kind = "backup-failed"


class UninstallStopped(UpdateError):
    kind = "uninstall-stopped"

    def __init__(self, message, report=None):
        super().__init__(message)
        self.report = report


class UnsafeFolder(UpdateError):
    kind = "unsafe-folder"


class RepairRefused(UpdateError):
    kind = "repair-refused"


def parse_version(text):
    m = VERSION.match(text) if isinstance(text, str) else None
    if not m:
        raise BadVersion("a version looks like 1.2.3 (three numbers)")
    return tuple(int(x) for x in m.groups())


def check_major(state_version, caller_version):
    """Pure. The state file's version against the caller's (installer or extension): a different major version is refused (039, 082)."""
    if parse_version(state_version)[0] != parse_version(caller_version)[0]:
        raise MajorVersionMismatch("the installer is major version %d and the caller is major version %d; they will not drive each other"
                                   % (parse_version(state_version)[0], parse_version(caller_version)[0]))


def extension_may_drive(state_dir_or_root, extension_version):
    """Host check of the extension contract (011, 081, 082): reads one state file and answers; never fetches or runs installer code."""
    check_major(read_state(state_dir_or_root)["installer_version"], extension_version)
    return True


def update_available(state_version, offered_version):
    """Pure. The extension only tells (037): True when the offered version is newer and of the same major version."""
    check_major(state_version, offered_version)
    return parse_version(offered_version) > parse_version(state_version)


def load_state_schema(path=STATE_SCHEMA):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_state(data, schema=None):
    schema = schema or load_state_schema()
    if not isinstance(data, dict):
        raise StateInvalid("the installer state file is damaged; nothing was changed")
    props = schema["properties"]
    for key in schema["required"]:
        if key not in data:
            raise StateInvalid("the installer state file lacks %s; nothing was changed" % key)
    for key, value in data.items():
        if key not in props:
            raise StateInvalid("the installer state file holds an unknown key %s; nothing was changed" % key)
        spec = props[key]
        if spec["type"] == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
            raise StateInvalid("the installer state file holds a wrong value for %s; nothing was changed" % key)
        if spec["type"] == "string" and not isinstance(value, str):
            raise StateInvalid("the installer state file holds a wrong value for %s; nothing was changed" % key)
        if "enum" in spec and value not in spec["enum"]:
            raise StateInvalid("the installer state file holds a wrong value for %s; nothing was changed" % key)
        if "const" in spec and value != spec["const"]:
            raise StateInvalid("the installer state file holds a wrong value for %s; nothing was changed" % key)
    parse_version(data["installer_version"])
    return data


def _state_path(root):
    return Path(root) / STATE_FILE


def read_state(root):
    path = _state_path(root)
    if not path.exists():
        raise StateMissing("the installer state file is missing; nothing was changed")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise StateInvalid("the installer state file is damaged; nothing was changed") from e
    return validate_state(data)


def write_state(root, installer_version, mode=None, forge_address=None):
    """Written through a temporary file and one rename, so a failure never leaves half a state file (039)."""
    data = {"schema_version": 1, "installer_version": installer_version}
    if mode is not None:
        data["mode"] = mode
    if forge_address is not None:
        data["forge_address"] = forge_address
    validate_state(data)
    path = _state_path(root)
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(data, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError as e:
        raise StateNotWritable("cannot write the installer state file (%s)" % e.__class__.__name__) from e
    return data


_REPLACE_RETRY_SECONDS = (1, 2, 4, 8)
_sleep = time.sleep  # tests replace it and never wait


def _remove_tree(path):
    """A just-stopped service can leave its exe mapped for a moment (access denied): only PermissionError is retried; the last error is the original one."""
    for wait in _REPLACE_RETRY_SECONDS:
        try:
            shutil.rmtree(path)
            return
        except PermissionError:
            _sleep(wait)
    shutil.rmtree(path)


def _replace_tree(src, dst):
    if dst.exists():
        _remove_tree(dst)
    shutil.copytree(src, dst)


class UpdateResult:
    def __init__(self, status, message, version, cause=None):
        self.status, self.message, self.version, self.cause = status, message, version, cause

    def __repr__(self):
        return "UpdateResult(%r, %r)" % (self.status, self.message)


def _healthy(system, mode):
    if not system.stays_running(HEALTH_SECONDS):
        return False
    return system.runner_online() if mode in runners.FORGES else True


def _because(cause):
    """Class name only of the update error that started a rollback: never its text, which could carry a path or a secret."""
    return "" if cause is None else " after the update failed with %s" % cause


def _restore(root, system, mode=None, cause=None):
    """Puts the backed-up program folder and service definition back. Promises nothing beyond the program files (041)."""
    root = Path(root)
    backup = root / BACKUP
    try:
        system.stop_service()  # already stopped or gone is fine inside it; a service not confirmed stopped must not get its files swapped
        _replace_tree(backup / PROGRAM, root / PROGRAM)
        system.lock_folder()  # the same folder ACL after a rollback, never a looser one
        system.apply_service_definition(json.loads((backup / SERVICE_FILE).read_text(encoding="utf-8")))
        system.start_service()
        healthy = _healthy(system, mode)
    except Exception as e:
        raise RestoreFailed("the previous program files could not be restored (%s)%s; the backup folder was kept"
                            % (e.__class__.__name__, _because(cause))) from e
    if not healthy:
        raise RestoreFailed("the previous program files were put back but the service is not healthy%s; the backup folder was kept"
                            % _because(cause))


def update(root, staged, new_version, system, fault=lambda step: None):
    """Replace the program files only (038): backup, stop, swap, start, health check, restore on any failure (040).
    `fault(step)` is called before each step; tests raise from it to inject a failure."""
    root, staged = Path(root), Path(staged)
    state = read_state(root)
    check_major(state["installer_version"], new_version)
    if not (root / PROGRAM).is_dir() or not staged.is_dir():
        raise NothingToUpdate("there are no program files to update or no new program files to install; nothing was changed")
    mode = state.get("mode") or runners.read_mode(root)
    backup = root / BACKUP
    system.lock_folder()  # re-applied before anything changes: a folder that is not ours refuses here, nothing is touched
    if (backup / COMPLETE).exists():
        # A finished backup (the marker is written last, removed first on success) may be the only good copy (a failed earlier restore): restore it first,
        # never delete it. A backup without the marker is stale or half-made: it is removed below and never restored over a good program.
        # A failed restore raises RestoreFailed and the backup stays untouched.
        _restore(root, system, mode, "PreviousBackup")
    try:
        fault("backup")
        if backup.exists():
            shutil.rmtree(backup)
        backup.mkdir(parents=True)
        shutil.copytree(root / PROGRAM, backup / PROGRAM)
        (backup / SERVICE_FILE).write_text(json.dumps(system.service_definition(), sort_keys=True) + "\n", encoding="utf-8")
        (backup / COMPLETE).write_text("", encoding="utf-8")
    except Exception as e:
        shutil.rmtree(backup, ignore_errors=True)
        raise BackupFailed("the backup could not be made (%s); nothing was changed" % e.__class__.__name__) from e
    cause = "UnhealthyService"
    try:
        fault("stop")
        system.stop_service()
        fault("swap")
        _replace_tree(staged, root / PROGRAM)
        system.lock_folder()  # the new files are checked and locked before the service runs them
        fault("start")
        system.start_service()
        fault("health")
        ok = _healthy(system, mode)
    except Exception as e:
        ok, cause = False, e.__class__.__name__  # the first error is kept: it is what the operator needs to see
    if not ok:
        _restore(root, system, mode, cause)
        return UpdateResult("restored", RESTORED, state["installer_version"], cause)
    write_state(root, new_version, state.get("mode"), state.get("forge_address"))
    try:
        (backup / COMPLETE).unlink(missing_ok=True)  # first: a backup that then stays behind is stale, not a restore point
    except OSError:
        pass  # best effort, like the NSIS Delete: the update succeeded
    shutil.rmtree(backup, ignore_errors=True)  # the update succeeded: the backup is no longer needed
    return UpdateResult("updated", "program files updated to version %s" % new_version, new_version)


def repair(root, staged, system):
    """Same installer, repair mode (042): idempotent, touches only the folder, the service, the uninstall entry and the state file.
    It never creates a key and never registers (083); a missing registration or key stays missing."""
    root, staged = Path(root), Path(staged)
    state = read_state(root)
    if not staged.is_dir():
        raise NothingToUpdate("there are no program files to repair from; nothing was changed")
    system.lock_folder()
    changed = []
    for src in sorted(p for p in staged.rglob("*") if p.is_file()):
        dst = root / PROGRAM / src.relative_to(staged)
        if dst.is_symlink():
            dst.unlink()
        if not dst.exists() or dst.read_bytes() != src.read_bytes():
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.parent.resolve().is_relative_to((root / PROGRAM).resolve()):
                raise RepairRefused("a link inside the program folder points outside it; nothing outside it was written")
            shutil.copyfile(src, dst)
            changed.append(str(dst.relative_to(root)))
    if not system.service_exists():
        svc = footprint.load_footprint()["service"]
        system.install_service(svc["name"], svc["account"], str(root))
        changed.append("service")
    if not system.uninstall_entry_exists():
        system.write_uninstall_entry()
        changed.append("uninstall entry")
    write_state(root, state["installer_version"], state.get("mode"), state.get("forge_address"))
    return changed


def forge_leftovers(state):
    """What remains to be deleted at the forge, with the exact place (044, 096)."""
    forge = state.get("mode")
    address = state.get("forge_address")
    if forge not in runners.FORGES or not address:
        return []
    return [{"forge": forge, "place": address.rstrip("/") + FORGE_PLACES[forge]}]


class UninstallReport:
    def __init__(self, removed, unregistered, leftovers, remaining=()):
        self.removed, self.unregistered, self.leftovers, self.remaining = removed, unregistered, leftovers, list(remaining)

    def text(self):
        lines = ["removed: " + (", ".join(self.removed) or "nothing")]
        if self.remaining:
            lines.append("remaining: " + ", ".join(self.remaining))
        if self.unregistered:
            lines.append("the forge confirmed the runner registration was deleted")
        for item in self.leftovers:
            lines.append("still to do at the %s: delete this runner by hand at %s" % (item["forge"], log.redact(item["place"])))
        return "\n".join(lines)


# uninstall.exe is last, as in uninstall.nsh: while anything else cannot be removed it stays, and so does the uninstall entry.
OWNED = (PROGRAM, BACKUP, KEYS, "logs", "config.toml", runners.FORGE_FILE, runners.MODE_FILE, runners.SBOM_NAME,
         STATE_FILE, STATE_FILE + ".tmp", licences.RECORD_NAME, "uninstall.exe")


def _check_uninstall_target(root, state_dir):
    """Only the footprint's install folder may be removed (043): right name, no link, holds a state file and a program folder.
    Returns False for such a folder that is already gone: an earlier run removed it and stopped at the uninstall entry."""
    want = footprint.load_footprint()["folder"]["path"].replace("\\", "/").rsplit("/", 1)[-1]
    if root.is_symlink() or os.path.realpath(root) != os.path.abspath(root):
        raise UnsafeFolder("the install folder is or sits behind a link; nothing was removed")
    present = root.exists()
    if root.name != want or (present and not ((root / STATE_FILE).is_file() and (root / PROGRAM).is_dir())):
        raise UnsafeFolder("this is not the installer's folder; nothing was removed")
    if state_dir is not None and Path(state_dir) != root:
        raise UnsafeFolder("the state folder is not the installer's folder; nothing was removed")
    return present


def _still_there(root):
    """What is still in the install folder, as full paths (045); the folder itself when it is empty but could not be removed."""
    try:
        paths = [str(p) for p in sorted(root.iterdir())]
    except OSError:
        return []
    return paths or [str(root)]


def _clear_readonly_and_retry(func, path, exc):
    """Windows refuses to delete a read-only file: clear the bit and try once more. Anything else, a second failure and a link
    (never followed, so no file outside the folder is touched) raise the original error as before."""
    if isinstance(exc, PermissionError) and func in (os.unlink, os.remove, os.rmdir) \
            and not os.path.islink(path) and not os.path.isjunction(path):
        try:
            os.chmod(path, os.stat(path).st_mode | stat.S_IWRITE)
            func(path)
            return
        except OSError:
            pass
    raise exc


def _remove_owned(root):
    """Removes only what the installer put in its folder; other files stay and so does the folder then."""
    for name in OWNED:
        p = root / name
        if p.is_symlink() or p.is_file():
            try:
                p.unlink()
            except PermissionError as e:
                _clear_readonly_and_retry(os.unlink, p, e)
        elif p.is_dir():
            shutil.rmtree(p, onexc=_clear_readonly_and_retry)
    try:
        root.rmdir()
        return True
    except OSError:
        return False


def uninstall(root, system, state_dir=None, fault=lambda step: None):
    """Offline removal (043, 084): service, the installer's own files in its folder, keys, and last the uninstall entry, which
    stays for as long as anything of the folder is left to remove, as in uninstall.nsh. Foreign files keep the folder but not the
    entry: the NSIS uninstaller deletes the whole folder, so only a failed removal is a reason to keep it. Unregistering is
    attempted only when the forge is reachable (095); a registration is reported gone only when the forge confirmed it (045),
    else it is listed (044, 096). A stop names what remains, in the message and in its report. Refuses any folder that is not
    the installer's own (typed)."""
    root = Path(root)
    present = _check_uninstall_target(root, state_dir)
    state = None
    if present:
        try:
            state = read_state(root)
        except UpdateError:
            pass
    leftovers = forge_leftovers(state) if state else []
    unregistered = False
    if leftovers and system.forge_reachable():
        try:
            unregistered = system.unregister_runner() is True
        except Exception:
            unregistered = False
        if unregistered:
            leftovers = []
    removed, remaining, step = [], [], "service"
    try:
        fault(step)
        system.delete_service()
        removed.append(step)
        if present:
            step = "folder"
            fault(step)
            gone = _remove_owned(root)
            removed += ["folder" if gone else "folder contents (other files kept)", "keys"]
            remaining = [] if gone else _still_there(root)
        step = "uninstall entry"
        fault(step)
        system.remove_uninstall_entry()
        removed.append(step)
    except Exception as e:
        remaining = (["service"] if step == "service" else []) + _still_there(root) + ["uninstall entry"]
        where = " at %s" % e.filename if getattr(e, "filename", None) else ""
        raise UninstallStopped("uninstall stopped after: %s (%s%s); remaining: %s; run it again" % (
            ", ".join(removed) or "nothing", e.__class__.__name__, where, ", ".join(remaining)),
            UninstallReport(removed, unregistered, leftovers, remaining)) from e
    return UninstallReport(removed, unregistered, leftovers, remaining)
