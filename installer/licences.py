"""Licence screens and the local licence record (INST-REQ-018, 019, 073, 074). Local only: this module opens no network."""
import json
import os
from pathlib import Path

RECORD_NAME = "licence-record.json"
BOXES = ("ni_licence_held", "engine_licence_accepted")


def licence_boxes(image_chosen):
    """The two separate boxes, both initially unticked, shown only when a container image is chosen (INST-REQ-018)."""
    return [{"id": b, "ticked": False} for b in BOXES] if image_chosen else []


def may_continue(ticks):
    """Continue only when both boxes are ticked (INST-REQ-073)."""
    return all(ticks.get(b) in (True, "yes") for b in BOXES)


def require_both(values):
    from installer.schema import LicenceNotAccepted
    if not may_continue(values):
        raise LicenceNotAccepted("both licence conditions must be accepted before an image is pulled")


def record_path(state_dir):
    return Path(state_dir) / RECORD_NAME


def write_record(state_dir, now):
    """Keep the 'yes, we hold a development licence' answer with a UTC date, in a 0600 file on this PC only."""
    from installer.schema import StateNotWritable
    path = record_path(state_dir)
    body = json.dumps({"ni_development_licence_held": "yes", "utc": now.strftime("%Y-%m-%dT%H:%M:%SZ")}, sort_keys=True)
    try:
        Path(state_dir).mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body + "\n")
        os.chmod(path, 0o600)
    except OSError as e:
        raise StateNotWritable("cannot write the licence record (%s)" % e.__class__.__name__) from e
    return path
