#!/usr/bin/env python3
"""Host side of the guest proof (ecosystem-control#64): build the installer, the installer with a stand-in program file (update cases), the three harnesses, the five NSIS probes and the link probe, write them as base64 text.

  python3 -m installer.guest.pack OUTDIR [--makensis PATH]

The pinned makensis.exe cannot run on this Linux host, so the distribution's makensis is used with the pinned compile flags and
script commands. Binaries are written only to OUTDIR as text (base64) for a throw-away local commit that `winev run` ships; none is
ever committed to the repository (INST-REQ-005). Standard library only.
"""
import argparse
import base64
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from installer import build

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
HARNESSES = ("log", "uninstall", "local")
PROBES = ("p1", "p2", "p3", "p4", "p5")
LINK_PROBES = ("p6",)
# The program file the update-mode guest cases embed (installer\guest\update-smoke.ps1): ASCII text, never run, written beside the installer as update-payload.bin.b64 so the driver compares exact bytes.
UPDATE_PAYLOAD = b"GUEST7D stand-in for the runner program file; the update writes it, nothing runs it\r\n"


def harness_command(makensis, pins, nsi, out, defines=()):
    c = pins["compile"]
    cmd = [makensis, *c.get("flags", [])]
    cmd += [f"-D{d}" for d in defines]
    cmd += [f"-X{s}" for s in c.get("script_commands", [])]
    cmd += [f"-XOutFile {out}", str(nsi)]
    return cmd


def to_b64_text(exe, dest):
    data = Path(exe).read_bytes()
    Path(dest).write_text(base64.b64encode(data).decode("ascii") + "\n", encoding="ascii", newline="\n")
    return hashlib.sha256(data).hexdigest()


def pack(outdir, makensis, run=None):
    run = run or build.default_run
    pins = build.load_pins()
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    digests = {}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src = tmp / "src"
        shutil.copytree(ROOT / "installer", src / "installer")
        payload = tmp / "update-payload.bin"
        payload.write_bytes(UPDATE_PAYLOAD)
        main_nsi = src / "installer" / "nsis" / "main.nsi"
        update_exe = tmp / "installer-update.exe"
        jobs = [("installer", main_nsi, src / "installer" / "nsis" / "installer.exe", ()),
                ("installer-update", main_nsi, update_exe, (f"RUNNER_PAYLOAD={payload}", f"OUTFILE={update_exe}"))]
        for name in HARNESSES:
            jobs.append((f"{name}-harness", src / "installer" / "guest" / f"{name}-harness.nsi", tmp / f"{name}-harness.exe", ()))
        for name in PROBES + LINK_PROBES:
            jobs.append((f"probe-{name}", src / "installer" / "guest" / f"probe-{name}.nsi", tmp / f"probe-{name}.exe", ()))
        for name, nsi, target, defines in jobs:
            rc, output = run(harness_command(makensis, pins, nsi, target, defines))
            if rc != 0 or not target.is_file():
                raise build.CompileError(f"{name} failed (exit {rc}): {output.strip()[-300:]}")
            digests[name] = to_b64_text(target, outdir / f"{target.name}.b64")
        digests["update-payload"] = to_b64_text(payload, outdir / f"{payload.name}.b64")
    return digests


def main(argv=None, run=None):
    ap = argparse.ArgumentParser(prog="installer.guest.pack", description=__doc__.splitlines()[0])
    ap.add_argument("outdir")
    ap.add_argument("--makensis", default=shutil.which("makensis"))
    a = ap.parse_args(argv)
    if not a.makensis:
        print("MissingTool: makensis not found", file=sys.stderr)
        return 2
    try:
        for k, v in sorted(pack(a.outdir, a.makensis, run).items()):
            print(f"{k} sha256 {v}")
    except build.BuildError as e:
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
