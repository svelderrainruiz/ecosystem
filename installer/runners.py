"""Runner modes (ARCH-7): GitHub runner, "Local only (no forge)", GitLab runner behind one mode switch.

INST-REQ-034, 035, 036, 066, 091 to 094. A PC serves one forge (D-R6-12). Every refusal is a typed error. No secret is printed,
logged or put on a command line: error text names the option only, and the GitLab token lives only in the runner's config.toml.
The system and forge are injected, so tests use fakes and this module opens no network itself."""
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

from installer import footprint
from installer.schema import SchemaError, StateNotWritable

MODES = ("github", "local", "gitlab")
FORGES = ("github", "gitlab")
MODE_FILE = "runner-mode.json"
FORGE_FILE = "runner-forge.json"
ACL_ACCOUNTS = ("NT AUTHORITY\\SYSTEM", "BUILTIN\\Administrators")
GITLAB_CONFIG = "config.toml"
SBOM_NAME = "sbom.cdx.json"

# Pinned minimal local-only tooling (decision O-4): the repository's own checks, build and unittest, and an in-process stdlib SBOM.
LOCAL_COMMANDS = {
    "check": [sys.executable, "-m", "installer.footprint", "check"],
    "build": [sys.executable, "-m", "installer.build"],
    "tests": [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
}
LOCAL_STEPS = ("check", "build", "sbom", "tests")


class RunnerError(SchemaError):
    kind = "bad-value"


class BadMode(RunnerError):
    kind = "bad-mode"


class ForgeAddressMissing(RunnerError):
    kind = "forge-address-missing"


class SecondForgeRefused(RunnerError):
    kind = "second-forge-refused"


class NotElevated(RunnerError):
    kind = "not-elevated"


class LogonRightMissing(RunnerError):
    kind = "logon-failure"


class LocalStepFailed(RunnerError):
    kind = "local-step-failed"


class StateCorrupt(RunnerError):
    kind = "state-corrupt"


class BadSecret(RunnerError):
    kind = "bad-secret"


_BAD_TEXT = re.compile("[\\x00-\\x20\\x7f\"'`\\\\]")


def _read_json(path):
    path = Path(path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError
        return data
    except (OSError, ValueError) as e:
        raise StateCorrupt("the runner state file %s is damaged; nothing was changed" % path.name) from e


def _locations(state_dir, program_dir):
    return [Path(d) for d in (state_dir, program_dir) if d is not None]


def read_mode(state_dir):
    data = _read_json(Path(state_dir) / MODE_FILE)
    if data is None:
        return None
    if data.get("mode") not in MODES:
        raise StateCorrupt("the runner state file %s is damaged; nothing was changed" % MODE_FILE)
    return data["mode"]


def recorded_forge(state_dir, program_dir=None):
    """The forge this PC has ever been set up for, from the permanent marker, the mode file or a GitLab config.toml. Never cleared."""
    found = set()
    for d in _locations(state_dir, program_dir):
        data = _read_json(d / FORGE_FILE)
        if data is not None:
            if data.get("forge") not in FORGES:
                raise StateCorrupt("the runner state file %s is damaged; nothing was changed" % FORGE_FILE)
            found.add(data["forge"])
        mode = read_mode(d)
        if mode in FORGES:
            found.add(mode)
        if (d / GITLAB_CONFIG).exists():
            found.add("gitlab")
    if len(found) > 1:
        raise StateCorrupt("the runner state records two forges; nothing was changed")
    return found.pop() if found else None


def _refuse_second(state_dir, program_dir, forge):
    current = recorded_forge(state_dir, program_dir)
    if current is not None and current != forge:
        raise SecondForgeRefused("this PC already serves a %s runner; it can serve only one forge" % current)


def _claim_forge(state_dir, program_dir, forge):
    """Written BEFORE any registration, so an interrupted or failed one still counts. Two places, so one lost folder does not free the PC."""
    _refuse_second(state_dir, program_dir, forge)
    try:
        for d in _locations(state_dir, program_dir):
            d.mkdir(parents=True, exist_ok=True)
            (d / FORGE_FILE).write_text(json.dumps({"forge": forge}) + "\n", encoding="utf-8")
    except OSError as e:
        raise StateNotWritable("cannot record the forge for this PC (%s)" % e.__class__.__name__) from e


def set_mode(state_dir, mode, program_dir=None):
    """The one mode switch. A forge, once recorded, is never replaced by the other one."""
    if mode not in MODES:
        raise BadMode("unknown runner mode %r" % mode)
    if mode in FORGES:
        _claim_forge(state_dir, program_dir, mode)
    else:
        recorded_forge(state_dir, program_dir)
    Path(state_dir).mkdir(parents=True, exist_ok=True)
    _mode_path(state_dir).write_text(json.dumps({"mode": mode}) + "\n", encoding="utf-8")


def _mode_path(state_dir):
    return Path(state_dir) / MODE_FILE


def _typed_address(address, expected_host=None):
    """https only, a host, no user name or password, no space, control or quote character (INST-REQ-066)."""
    bad = ForgeAddressMissing("type the forge address (it must start with https); there is no default address")
    if not isinstance(address, str) or _BAD_TEXT.search(address):
        raise bad
    try:
        u = urlsplit(address)
        host = u.hostname
        u.port
    except ValueError:
        raise bad
    if u.scheme.lower() != "https" or not host or "@" in u.netloc:
        raise bad
    if expected_host is not None and host.lower() != expected_host.lower():
        raise ForgeAddressMissing("the forge address must be on the host %s" % expected_host)
    return address


def _typed_token(token):
    if not isinstance(token, str) or not token or _BAD_TEXT.search(token):
        raise BadSecret("the runner token is empty or holds a space, quote, backslash or control character")
    return token


def register_github(state_dir, program_dir, address, token, forge, expected_host=None):
    """Register only at the typed address (INST-REQ-066). The token goes to the forge call and is never stored here."""
    address = _typed_address(address, expected_host)
    _typed_token(token)
    _claim_forge(state_dir, program_dir, "github")
    forge.register(address, token)
    set_mode(state_dir, "github", program_dir)


def _write_config(cfg, address, token, system, accounts):
    """Fresh file, created 0600 and never followed through a link; the ACL is set while the file is still empty."""
    if cfg.is_symlink() or cfg.exists():
        cfg.unlink()
    fd = os.open(cfg, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        system.restrict_acl(str(cfg), accounts)
    except BaseException:
        os.close(fd)
        raise
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write('[[runners]]\n  url = "%s"\n  token = "%s"\n' % (address, token))


def install_gitlab(state_dir, program_dir, address, token, system, expected_host=None):
    """GitLab runner: elevated phase only (091), dedicated virtual account (092), typed log-on error (093), token in config.toml only (094)."""
    address = _typed_address(address, expected_host)
    _typed_token(token)
    _refuse_second(state_dir, program_dir, "gitlab")
    if not system.is_elevated():
        raise NotElevated("the GitLab runner is installed only after the administrator prompt")
    svc = footprint.load_footprint()["service"]
    if not system.has_logon_right(svc["account"]):
        raise LogonRightMissing("logon failure: %s lacks the right to log on as a service" % svc["account"])
    system.prepare_folder()  # the install folder is ours and locked before the first write of this step
    _claim_forge(state_dir, program_dir, "gitlab")
    program_dir = Path(program_dir)
    cfg = program_dir / GITLAB_CONFIG
    try:
        _write_config(cfg, address, token, system, ACL_ACCOUNTS)
        system.install_service(svc["name"], svc["account"], str(program_dir), files=(str(cfg),))
    except BaseException:
        try:
            cfg.unlink()
        except OSError:
            pass
        raise
    set_mode(state_dir, "gitlab", program_dir)


def write_sbom(root):
    """Minimal CycloneDX document: every file under root with its SHA-256 (stdlib only)."""
    root = Path(root)
    comps = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.is_symlink() and p.name not in (SBOM_NAME, GITLAB_CONFIG):
            comps.append({"type": "file", "name": p.relative_to(root).as_posix(),
                          "hashes": [{"alg": "SHA-256", "content": hashlib.sha256(p.read_bytes()).hexdigest()}]})
    out = root / SBOM_NAME
    out.write_text(json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.5", "components": comps}, indent=1) + "\n", encoding="utf-8")
    return out


def run_local(root, run):
    """Local only (INST-REQ-035): check, build, SBOM, tests by command; no service, no forge contact. `run(argv)` returns an exit code."""
    done = []
    for step in LOCAL_STEPS:
        if step == "sbom":
            write_sbom(root)
        elif run(LOCAL_COMMANDS[step]) != 0:
            raise LocalStepFailed("local step %s failed" % step)
        done.append({"step": step})
    return done
