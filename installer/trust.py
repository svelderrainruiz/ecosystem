"""Trust chain reference model (ARCH-1): first-run confirmation, stored signer, signer change, key replacement.

The NSIS code in installer/nsis/trust.nsh implements the same rules; this module is the tested model and the only
parser of the fingerprint file format, for the published file and for the stored file alike (INST-REQ-002).

Fingerprint file format: text holding exactly one sha256 fingerprint (64 hex digits, any case, as a whole word).
The same fingerprint may repeat; other words (a file name, a comment) are allowed. No fingerprint, or two different
ones, is refused. The stored file is written in the canonical form: 64 lowercase hex digits and one newline.

Key replacement statement (INFERRED mechanism, INST-REQ-056/086; the format is a design choice of this slice):
  ecosystem-key-replacement v1
  old: <fingerprint of the key being replaced>
  new: <fingerprint of the replacement key>
  signature: <hex of the old key's signature over signed_message()>
The signature check itself is a callable given by the caller (verify(old_fp, message, signature) -> bool): on the
target it is the platform signature check, on the host a fake. No key material is read, stored or printed here.
"""
import os
import re
from collections import namedtuple
from pathlib import Path

FINGERPRINT = re.compile(r"\b([0-9a-fA-F]{64})\b")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
REPLACEMENT_HEADER = "ecosystem-key-replacement v1"
Decision = namedtuple("Decision", "action old new")
FIRST_RUN, PROCEED, SIGNER_CHANGED = "first_run", "proceed", "signer_changed"


class TrustError(Exception):
    """Base of every expected refusal."""


class FingerprintFormatError(TrustError):
    pass


class FirstRunNotConfirmed(TrustError):
    pass


class SignerChanged(TrustError):
    def __init__(self, old, new):
        super().__init__(f"STOPPED signer changed: stored {old}, new {new}; no build step was started")
        self.old, self.new = old, new


class ReplacementRefused(TrustError):
    pass


def parse_fingerprint(text, what="fingerprint file"):
    """Exactly one distinct fingerprint, returned lowercase."""
    found = {m.lower() for m in FINGERPRINT.findall(text)}
    if not found:
        raise FingerprintFormatError(f"no sha256 fingerprint found in {what}")
    if len(found) > 1:
        raise FingerprintFormatError(f"{what} holds {len(found)} different fingerprints; exactly one is allowed")
    return found.pop()


def read_fingerprint_file(path):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        reason = getattr(e, "strerror", None) or "not valid UTF-8 text"
        raise FingerprintFormatError(f"cannot read the fingerprint file {path}: {reason}") from None
    return parse_fingerprint(text, str(path))


def read_stored(store):
    """None on a first run (no file); a damaged file is refused, never treated as a first run."""
    if not Path(store).exists():
        return None
    return read_fingerprint_file(store)


def write_stored(store, fingerprint):
    fingerprint = _check(fingerprint)
    store = Path(store)
    store.parent.mkdir(parents=True, exist_ok=True)
    tmp = store.with_name(store.name + ".tmp")
    tmp.write_text(fingerprint + "\n", encoding="utf-8")
    os.replace(tmp, store)


def _check(fingerprint):
    if not isinstance(fingerprint, str) or not HEX64.match(fingerprint.lower()):
        raise FingerprintFormatError("fingerprint is not 64 hex digits")
    return fingerprint.lower()


def evaluate(store, signer):
    signer = _check(signer)
    stored = read_stored(store)
    if stored is None:
        return Decision(FIRST_RUN, None, signer)
    if stored == signer:
        return Decision(PROCEED, stored, signer)
    return Decision(SIGNER_CHANGED, stored, signer)


def run(store, signer, ask):
    """Gate before any build step. ask(old, new) -> bool is the confirmation screen (old is None on a first run).

    Same signer: no question (INST-REQ-067). First run: the user must confirm the fingerprint against the two
    published places, then it is stored (INST-REQ-001/002). Other signer: ask again showing both, silent runs
    (ask returns False) stop (INST-REQ-003)."""
    d = evaluate(store, signer)
    if d.action == PROCEED:
        return d
    if ask(d.old, d.new) is not True:
        if d.action == FIRST_RUN:
            raise FirstRunNotConfirmed("STOPPED first run: the fingerprint was not confirmed; no build step was started")
        raise SignerChanged(d.old, d.new)
    write_stored(store, d.new)
    return Decision(PROCEED, d.old, d.new)


def signed_message(old, new):
    return f"{REPLACEMENT_HEADER}\nold: {_check(old)}\nnew: {_check(new)}\n".encode("ascii")


def format_replacement(old, new, signature_hex):
    return signed_message(old, new).decode("ascii") + f"signature: {signature_hex}\n"


def parse_replacement(text):
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) != 4 or lines[0] != REPLACEMENT_HEADER:
        raise ReplacementRefused("replacement statement is not in the defined format")
    fields = {}
    for ln in lines[1:]:
        key, sep, val = ln.partition(": ")
        if not sep or key in fields or key not in ("old", "new", "signature"):
            raise ReplacementRefused("replacement statement is not in the defined format")
        fields[key] = val.strip()
    if set(fields) != {"old", "new", "signature"}:
        raise ReplacementRefused("replacement statement is not in the defined format")
    try:
        old, new = _check(fields["old"]), _check(fields["new"])
        sig = bytes.fromhex(fields["signature"])
    except (FingerprintFormatError, ValueError):
        raise ReplacementRefused("replacement statement has a malformed fingerprint or signature") from None
    if not sig:
        raise ReplacementRefused("replacement statement has an empty signature")
    return old, new, sig


def accept_replacement(store, text, verify):
    """Store the new key's fingerprint only when the stored (old) key signed the statement (INST-REQ-056/086)."""
    old, new, sig = parse_replacement(text)
    stored = read_stored(store)
    if stored is None:
        raise ReplacementRefused("REFUSED replacement: no key is trusted yet, so there is no old key to sign it")
    if old != stored:
        raise ReplacementRefused("REFUSED replacement: it names an old key other than the stored one")
    if new == old:
        raise ReplacementRefused("REFUSED replacement: the new key equals the old key")
    if verify(old, signed_message(old, new), sig) is not True:
        raise ReplacementRefused("REFUSED replacement: the old key's signature does not verify")
    write_stored(store, new)
    return new
