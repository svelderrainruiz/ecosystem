#!/usr/bin/env python3
"""Compare the agent's rebuild with the release (INST-REQ-072).

  python3 installer/rebuild-compare.py RELEASE_INSTALLER REBUILT_INSTALLER

Exit 0 on MATCH, 1 on DIFFER, 2 on a refusal. Only sha256 hashes are printed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from installer import proof  # noqa: E402

if __name__ == "__main__":
    sys.exit(proof.compare_main(sys.argv[1:]))
