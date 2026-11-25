"""Guest proof, GUEST6C1 (ecosystem-control#64): compares the licence record that the installer wrote with what
installer.licences.write_record writes for the same UTC string, and checks that the reader finds the record where the installer put it.
Run in the guest: python -m installer.guest.record_probe <record file the installer wrote> <scratch dir> <footprint folder>.
Prints key=value lines only; opens no network and keeps nothing outside the scratch dir."""
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from installer import licences

UTC_FIELD = re.compile(rb'"utc": "(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)Z"')


def line_end(data):
    if data.endswith(b"\r\n"):
        return "CRLF"
    if data.endswith(b"\n"):
        return "LF"
    return "none"


def compare(nsis_file, scratch, state_dir):
    """The facts, as a list of (key, value) pairs."""
    nsis = Path(nsis_file).read_bytes()
    facts = [("nsis_hex", nsis.hex()), ("nsis_line_end", line_end(nsis))]
    reader = licences.record_path(state_dir)
    same = os.path.normcase(os.path.abspath(reader)) == os.path.normcase(os.path.abspath(nsis_file))
    facts.append(("reader_path", str(reader)))
    found = UTC_FIELD.search(nsis)
    if not found:
        return facts + [("utc_found", "False")]
    when = datetime.strptime(found.group(1).decode("ascii"), "%Y-%m-%dT%H:%M:%S")
    written = licences.write_record(scratch, when)
    py = Path(written).read_bytes()
    facts += [("utc_found", "True"), ("python_hex", py.hex()), ("python_line_end", line_end(py)),
              ("identical", str(py == nsis)),
              ("identical_ignoring_line_end", str(py.rstrip(b"\r\n") == nsis.rstrip(b"\r\n"))),
              ("reader_path_is_the_nsis_file_when_state_dir_is_the_footprint_folder", str(same))]
    return facts


def main(argv):
    if len(argv) != 4:
        print("usage: record_probe <record file> <scratch dir> <footprint folder>")
        return 2
    for key, value in compare(argv[1], argv[2], argv[3]):
        print("%s=%s" % (key, value))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
