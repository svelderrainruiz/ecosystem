#!/usr/bin/env python3
"""Installer build script (ARCH-2): verify NSIS 3.10, check Git and the container engine, compile with fixed inputs, compare the hash.

  python3 -m installer.build check                          # Git and container engine present? versions only
  python3 -m installer.build fetch                          # download the pinned NSIS zip, verify sha256, unpack
  python3 -m installer.build build SRC OUT --runner-payload FILE [--test-build] [--published HASHFILE]
  python3 -m installer.build verify OUT HASHFILE            # compare a built installer with the published fingerprint

Every expected refusal is a BuildError subclass printed as one line (exit 2); nothing is ever installed (INST-REQ-071).
The NSIS zip is downloaded per user into a cache folder of the user's home, never with elevation (INST-REQ-069).
The only source of hashes is installer/pins.json (INST-REQ-007).
The runner payload (SL-14) is a build input, never in Git (INST-REQ-005): a release build needs its sha256 to equal pins.json runner_payload.sha256;
--test-build embeds any payload (a stub) without that pin and says so, so a release gate can tell the two apart.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

from installer import trust

HERE = Path(__file__).resolve().parent
PINS_PATH = HERE / "pins.json"
ENGINES = ("docker", "podman")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
DATE_MACROS = re.compile(r"__DATE__|__TIME__|__TIMESTAMP__", re.I)
CHUNK = 1 << 20
RUN_TIMEOUT = 600


class BuildError(Exception):
    """Base of every expected refusal."""


class PinsError(BuildError):
    pass


class HashMismatch(BuildError):
    pass


class MissingTool(BuildError):
    pass


class ElevationRefused(BuildError):
    pass


class PayloadError(BuildError):
    pass


class PayloadMismatch(BuildError):
    pass


class CompileError(BuildError):
    pass


class PublishedMismatch(BuildError):
    pass


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def load_pins(path=PINS_PATH):
    try:
        pins = json.loads(Path(path).read_text(encoding="utf-8"))
        nsis = pins["nsis"]
        digest = nsis["sha256"]
        nsis["url"], nsis["version"], nsis["root"], pins["compile"]["defines"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise PinsError(f"pins file {path} is unreadable or incomplete: {e!r}") from None
    if not isinstance(digest, str) or not HEX64.match(digest):
        raise PinsError("pins file: nsis.sha256 is not a lowercase 64-hex sha256")
    pin = pins.get("runner_payload", {}).get("sha256") if isinstance(pins.get("runner_payload", {}), dict) else 0
    if pin is not None and (not isinstance(pin, str) or not HEX64.match(pin)):
        raise PinsError("pins file: runner_payload.sha256 must be null or a lowercase 64-hex sha256")
    return pins


def check_payload(pins, payload, test_build):
    """Returns (payload path or None, digest or None). A release build needs the pinned digest; a test build needs only a file."""
    if payload is None:
        raise PayloadError("no runner payload: pass --runner-payload FILE (the installer embeds one file by digest; it is never in Git)")
    path = Path(payload)
    if not path.is_file():
        raise PayloadError(f"runner payload is not a file: {path}")
    got = sha256_file(path)
    if test_build:
        return str(path), got
    pin = pins.get("runner_payload", {}).get("sha256")
    if pin is None:
        raise PayloadError("REFUSED release build: runner_payload.sha256 in pins.json is not set, so no runner payload is pinned yet; "
                           "use --test-build for a test build")
    if got != pin:
        raise PayloadMismatch(f"REFUSED runner payload: sha256 {got} differs from the pinned {pin}; nothing was built")
    return str(path), got


def download_dir(env=None, euid=None):
    """Per-user folder; refuses to run elevated (INST-REQ-069)."""
    env = os.environ if env is None else env
    euid = os.geteuid() if euid is None and hasattr(os, "geteuid") else euid
    if euid == 0:
        raise ElevationRefused("refusing to run as root: the build downloads per user and needs no elevation")
    base = env.get("XDG_CACHE_HOME") or os.path.join(env.get("HOME") or os.path.expanduser("~"), ".cache")
    return Path(base) / "ecosystem-installer"


def default_download(url, dest):
    if not url.startswith("https://"):
        raise PinsError(f"download url is not https: {url}")
    with urllib.request.urlopen(url, timeout=120) as r, open(dest, "wb") as f:  # nosec: https only, hash checked after
        shutil.copyfileobj(r, f)


def default_run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=RUN_TIMEOUT, check=False)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def check_tools(which=shutil.which, run=default_run):
    """INST-REQ-009/010: report versions of Git and the container engine; name what is missing, install nothing."""
    found = {}
    if not which("git"):
        raise MissingTool("Git is not installed: install Git yourself, this script never installs it")
    found["git"] = _version(run, ["git", "--version"])
    engine = next((e for e in ENGINES if which(e)), None)
    if engine is None:
        raise MissingTool("no container engine found: install docker or podman yourself, this script never installs one")
    found[engine] = _version(run, [engine, "--version"])
    return found


def _version(run, cmd):
    rc, out = run(cmd)
    return out.strip().splitlines()[0] if rc == 0 and out.strip() else "version unknown"


def fetch_nsis(pins, cache, download=default_download, which=shutil.which, platform=sys.platform):
    """Download the pinned zip, use it only when its sha256 equals the pin (INST-REQ-007/008/070), return makensis path."""
    nsis = pins["nsis"]
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    zip_path = cache / f"nsis-{nsis['version']}.zip"
    target = cache / f"nsis-{nsis['version']}"
    download(nsis["url"], str(zip_path))
    got = sha256_file(zip_path)
    if got != nsis["sha256"]:
        zip_path.unlink(missing_ok=True)
        raise HashMismatch(
            f"REFUSED NSIS zip: sha256 {got} differs from the pinned {nsis['sha256']}; the file was deleted and not used")
    if target.exists():
        shutil.rmtree(target)
    _safe_extract(zip_path, cache)
    exe = cache / nsis["root"] / "makensis.exe"
    unix = cache / nsis["root"] / "Bin" / "makensis"
    if unix.exists():
        return str(unix)
    if platform == "win32":
        return str(exe)
    # The pinned zip is verified above; its makensis.exe cannot run here, so the host's own makensis compiles.
    host = which("makensis")
    if not host:
        raise MissingTool("makensis: the pinned makensis.exe cannot run on this system and no makensis is installed")
    return host


def _safe_extract(zip_path, dest):
    root = Path(dest).resolve()
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            if not (root / name).resolve().is_relative_to(root):
                raise HashMismatch(f"REFUSED NSIS zip: entry escapes the folder: {name}")
        z.extractall(root)


def collect_files(src):
    """Sorted, forward-slash relative file list: the input order never depends on the file system (INST-REQ-013)."""
    src = Path(src)
    out = []
    for dirpath, dirs, files in os.walk(src):
        dirs[:] = sorted(d for d in dirs if d != ".git")
        out.extend((Path(dirpath) / f).relative_to(src).as_posix() for f in files)
    return sorted(out)


def compile_command(makensis, pins, nsi, outfile, filelist, payload=None, test_build=False):
    """The fixed compile command: pinned defines in sorted order, pinned script commands, no date or time macro."""
    c = pins["compile"]
    cmd = [makensis, *c.get("flags", [])]
    cmd += [f"-D{k}={v}" for k, v in sorted(c["defines"].items())]
    cmd += [f"-D{k}={v}" for k, v in (("FILELIST", filelist), ("OUTFILE", outfile))]
    if payload is not None:
        cmd.append(f"-DRUNNER_PAYLOAD={payload}")
        if test_build:
            cmd.append("-DRUNNER_TEST_BUILD=1")
    cmd += [f"-X{s}" for s in c.get("script_commands", [])]
    cmd.append(str(nsi))
    if any(DATE_MACROS.search(a) for a in cmd):
        raise PinsError("compile command contains a date or time macro")
    return cmd


def read_published(path):
    """Strict format of the trust chain: exactly one fingerprint (installer.trust.parse_fingerprint)."""
    try:
        return trust.read_fingerprint_file(path)
    except trust.FingerprintFormatError as e:
        raise PublishedMismatch(str(e)) from None


def compare_published(built, published):
    """INST-REQ-006/068: report match, or stop with both hashes."""
    got = sha256_file(built)
    if got != published:
        raise PublishedMismatch(f"MISMATCH: built {got}, published {published}")
    return got


def build(src, out, pins, makensis, work, run=default_run, published=None, payload=None, test_build=False):
    src, out, work = Path(src), Path(out), Path(work)
    nsi = src / "installer" / "nsis" / "main.nsi"
    if not nsi.is_file():
        raise CompileError(f"installer script not found: {nsi}")
    work.mkdir(parents=True, exist_ok=True)
    filelist = work / "filelist.txt"
    filelist.write_text("\n".join(collect_files(src / "installer")) + "\n", encoding="utf-8", newline="\n")
    cmd = compile_command(makensis, pins, nsi, out, filelist, payload, test_build)
    rc, output = run(cmd)
    if rc != 0 or not out.is_file():
        raise CompileError(f"makensis failed (exit {rc}): {output.strip()[-400:]}")
    digest = sha256_file(out)
    if published is not None:
        compare_published(out, published)
    return digest


def main(argv=None, download=default_download, run=default_run, which=shutil.which, env=None, euid=None):
    ap = argparse.ArgumentParser(prog="installer.build", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    sub.add_parser("fetch")
    b = sub.add_parser("build")
    b.add_argument("src")
    b.add_argument("out")
    b.add_argument("--published")
    b.add_argument("--runner-payload")
    b.add_argument("--test-build", action="store_true")
    v = sub.add_parser("verify")
    v.add_argument("out")
    v.add_argument("hashfile")
    a = ap.parse_args(argv)
    try:
        pins = load_pins()
        cache = download_dir(env, euid)
        if a.cmd == "check":
            for tool, ver in check_tools(which, run).items():
                print(f"{tool}: {ver}")
        elif a.cmd == "fetch":
            print(f"NSIS {pins['nsis']['version']} verified: {fetch_nsis(pins, cache, download)}")
        elif a.cmd == "verify":
            print(f"MATCH {compare_published(a.out, read_published(a.hashfile))}")
        else:
            payload, payload_sha = check_payload(pins, a.runner_payload, a.test_build)
            check_tools(which, run)
            makensis = fetch_nsis(pins, cache, download)
            pub = read_published(a.published) if a.published else None
            digest = build(a.src, a.out, pins, makensis, cache / "work", run, pub, payload, a.test_build)
            print(f"built {a.out} sha256 {digest}" + (" MATCH" if pub else ""))
            if a.test_build:
                print("TEST BUILD: the runner payload is not pinned; this installer is not a release")
            else:
                print(f"runner payload sha256 {payload_sha} (pinned)")
    except BuildError as e:
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
