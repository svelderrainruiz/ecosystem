"""Build and verify the commit-named VM test kit (#197)."""
import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


KIT_FILES = ("installer.exe", "VM-TEST.md", "vm-state.ps1")


class KitError(Exception):
    """An expected kit refusal."""


def checked_run(argv, cwd, env=None):
    result = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True)
    if result.returncode:
        reason = " ".join((result.stderr or result.stdout).split())[-400:]
        raise KitError(f"{argv[0]} failed (exit {result.returncode}): {reason}")
    return result.stdout


def build_installer(repo, out, payload):
    with tempfile.TemporaryDirectory(prefix="vmkit-build-") as cache:
        env = dict(os.environ, XDG_CACHE_HOME=cache, PYTHONDONTWRITEBYTECODE="1")
        checked_run([sys.executable, "-m", "installer.build", "build", ".", str(out),
                     "--runner-payload", str(payload), "--test-build"], repo, env=env)


def checksums(kit):
    return "".join(f"{hashlib.sha256((kit / name).read_bytes()).hexdigest()}  {name}\n"
                   for name in KIT_FILES).encode("ascii")


def make_kit(out, payload, repo=Path("."), builder=build_installer):
    repo, out, payload = Path(repo).resolve(), Path(out).absolute(), Path(payload).resolve()
    if checked_run(["git", "status", "--porcelain", "--untracked-files=all"], repo):
        raise KitError("checkout is dirty")
    head = checked_run(["git", "rev-parse", "HEAD"], repo).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise KitError("HEAD must be a 40-digit git commit")
    if out.name != head[:12]:
        raise KitError("output folder name must equal the first 12 hex digits of HEAD")
    if out.is_symlink() or (out.exists() and (not out.is_dir() or any(out.iterdir()))):
        raise KitError("output folder must be absent or empty")
    if not payload.is_file():
        raise KitError("payload is not a file")
    sources = (repo / "installer" / "VM-TEST.md", repo / "installer" / "guest" / "vm-state.ps1")
    if any(not source.is_file() for source in sources):
        raise KitError("checkout is missing a VM kit source file")
    out.mkdir(parents=True, exist_ok=True)
    builder(repo, out / "installer.exe", payload)
    for source in sources:
        shutil.copyfile(source, out / source.name)
    with (out / "VM-TEST.md").open("ab") as stream:
        stream.write(f"built from: {head}\n".encode("ascii"))
    (out / "SHA256SUMS").write_bytes(checksums(out))
    verify(out)
    return out


def verify(kit):
    kit = Path(kit).absolute()
    if not kit.is_dir():
        raise KitError("kit is not a directory")
    if {p.name for p in kit.iterdir()} != {*KIT_FILES, "SHA256SUMS"}:
        raise KitError("kit must contain exactly installer.exe, VM-TEST.md, vm-state.ps1 and SHA256SUMS")
    if any(p.is_symlink() or not p.is_file() for p in kit.iterdir()):
        raise KitError("kit members must be regular files, not links")
    if (kit / "SHA256SUMS").read_bytes() != checksums(kit):
        raise KitError("SHA256SUMS does not match the three kit files in recipe order")
    lines = (kit / "VM-TEST.md").read_bytes().splitlines()
    match = re.fullmatch(rb"built from: ([0-9a-fA-F]{40})", lines[-1]) if lines else None
    if match is None or match[1].decode("ascii")[:12] != kit.name:
        raise KitError("last built from: line must contain 40 hex digits matching the folder name")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="installer.guest.vmkit", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    build = sub.add_parser("build")
    build.add_argument("--out", required=True, type=Path)
    build.add_argument("--payload", required=True, type=Path)
    build.add_argument("--repo", default=Path("."), type=Path)
    check = sub.add_parser("verify")
    check.add_argument("dir", type=Path)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "build":
            make_kit(args.out, args.payload, args.repo)
        else:
            verify(args.dir)
    except (KitError, OSError) as error:
        print(f"{type(error).__name__}: {' '.join(str(error).split())}", file=sys.stderr)
        return 2
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
