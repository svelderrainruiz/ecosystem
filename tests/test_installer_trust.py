"""SL-2 tests: trust chain (INST-REQ-001..004, 056, 067, 086). Reference model plus the strict fingerprint file format."""
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from installer import build, trust

ROOT = Path(__file__).resolve().parent.parent
A = "a" + hashlib.sha256(b"signer-A").hexdigest()[1:]
B = "b" + hashlib.sha256(b"signer-B").hexdigest()[1:]
C = "c" + hashlib.sha256(b"signer-C").hexdigest()[1:]
A_LAST = A[:-1] + ("0" if A[-1] != "0" else "1")  # differs from A in the final character only


def fake_verify_factory(signer_fp, calls=None):
    """Fake signature check: a signature is valid when it equals the first 8 bytes of sha256(signer + message)."""
    def verify(old_fp, message, sig):
        if calls is not None:
            calls.append(old_fp)
        return old_fp == signer_fp and sig == hashlib.sha256(signer_fp.encode() + message).digest()[:8]
    return verify


def sign(signer_fp, old, new):
    return hashlib.sha256(signer_fp.encode() + trust.signed_message(old, new)).digest()[:8].hex()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = self.tmp / "sub" / "signer.sha256"


class TestStateMachine(Base):
    def test_first_run_requires_two_place_confirmation(self):
        """INST-REQ-001, 004: no build step before the user confirms; the screen gets the fingerprint."""
        seen = []
        with self.assertRaises(trust.FirstRunNotConfirmed):
            trust.run(self.store, A, lambda old, new: seen.append((old, new)) or False)
        self.assertEqual(seen, [(None, A)])
        self.assertFalse(self.store.exists())
        with self.assertRaises(trust.FirstRunNotConfirmed):
            trust.run(self.store, A, lambda old, new: "yes")  # only a real True confirms
        self.assertFalse(self.store.exists())

    def test_confirmed_fingerprint_is_stored(self):
        """INST-REQ-002: stored locally in the one defined format."""
        d = trust.run(self.store, A.upper(), lambda old, new: True)
        self.assertEqual(d.action, trust.PROCEED)
        self.assertEqual(self.store.read_text(), A + "\n")
        self.assertEqual(trust.read_stored(self.store), A)
        self.assertFalse(list(self.store.parent.glob("*.tmp")))

    def test_same_signer_skips_the_pause(self):
        """INST-REQ-067, TC-002: second run asks nothing."""
        trust.run(self.store, A, lambda o, n: True)

        def never(o, n):
            raise AssertionError("asked")
        self.assertEqual(trust.run(self.store, A, never).action, trust.PROCEED)

    def test_different_signer_stops_and_shows_both(self):
        """INST-REQ-003, TC-003: old and new shown, stop before any build step, stored file untouched."""
        trust.run(self.store, A, lambda o, n: True)
        seen = []
        with self.assertRaises(trust.SignerChanged) as cm:
            trust.run(self.store, B, lambda o, n: seen.append((o, n)) or False)
        self.assertEqual(seen, [(A, B)])
        self.assertIn(A, str(cm.exception))
        self.assertIn(B, str(cm.exception))
        self.assertEqual(trust.read_stored(self.store), A)

    def test_different_signer_asked_again_and_confirmed_replaces(self):
        """INST-REQ-003: after the user confirms again, the new signer is stored."""
        trust.run(self.store, A, lambda o, n: True)
        trust.run(self.store, B, lambda o, n: True)
        self.assertEqual(trust.read_stored(self.store), B)

    def test_near_misses_are_a_different_signer(self):
        """INST-REQ-003: one differing character, at the end or early, is a change; a prefix is no match."""
        trust.run(self.store, A, lambda o, n: True)
        early = ("0" if A[0] != "0" else "1") + A[1:]
        for other in (A_LAST, early):
            seen = []
            with self.assertRaises(trust.SignerChanged):
                trust.run(self.store, other, lambda o, n: seen.append((o, n)) or False)
            self.assertEqual(seen, [(A, other)])
        with self.assertRaises(trust.FingerprintFormatError):  # prefix of the stored one is malformed, never equal
            trust.evaluate(self.store, A[:16])
        self.store.write_text(A[:32] + "\n")
        with self.assertRaises(trust.FingerprintFormatError):  # a stored prefix is damage, not a first run
            trust.evaluate(self.store, A)

    def test_damaged_store_is_not_a_first_run(self):
        self.store.parent.mkdir(parents=True)
        for bad in ("", "garbage", A + "\n" + B + "\n"):
            self.store.write_text(bad)
            with self.assertRaises(trust.FingerprintFormatError):
                trust.run(self.store, A, lambda o, n: True)

    def test_malformed_signer_is_refused(self):
        for bad in ("abc", "g" * 64, None, A + "0"):
            with self.assertRaises(trust.FingerprintFormatError):
                trust.evaluate(self.store, bad)


class TestReplacement(Base):
    def setUp(self):
        super().setUp()
        trust.run(self.store, A, lambda o, n: True)

    def test_replacement_key_needs_old_key_signature(self):
        """INST-REQ-056, 086, TC-046: signed by A accepted; unsigned or signed by B refused."""
        verify = fake_verify_factory(A)
        text = trust.format_replacement(A, B, sign(A, A, B))
        self.assertEqual(trust.accept_replacement(self.store, text, verify), B)
        self.assertEqual(trust.read_stored(self.store), B)
        self.assertEqual(trust.run(self.store, B, lambda o, n: 1 / 0).action, trust.PROCEED)

    def test_unsigned_replacement_is_refused(self):
        verify = fake_verify_factory(A)
        for sig in (sign(B, A, B), "00", sign(A, A, C)):
            text = trust.format_replacement(A, B, sig)
            with self.assertRaises(trust.ReplacementRefused):
                trust.accept_replacement(self.store, text, verify)
            self.assertEqual(trust.read_stored(self.store), A)
        with self.assertRaises(trust.ReplacementRefused):
            trust.accept_replacement(self.store, trust.signed_message(A, B).decode(), verify)

    def test_replacement_naming_other_old_key_or_same_key_is_refused(self):
        calls = []
        verify = fake_verify_factory(B, calls)
        with self.assertRaises(trust.ReplacementRefused):
            trust.accept_replacement(self.store, trust.format_replacement(B, C, sign(B, B, C)), verify)
        verify = fake_verify_factory(A, calls)
        with self.assertRaises(trust.ReplacementRefused):
            trust.accept_replacement(self.store, trust.format_replacement(A, A, sign(A, A, A)), verify)
        self.assertEqual(calls, [])  # refused before any signature check

    def test_replacement_without_trusted_key_is_refused(self):
        self.store.unlink()
        with self.assertRaises(trust.ReplacementRefused):
            trust.accept_replacement(self.store, trust.format_replacement(A, B, sign(A, A, B)), fake_verify_factory(A))

    def test_verify_must_return_true(self):
        text = trust.format_replacement(A, B, sign(A, A, B))
        with self.assertRaises(trust.ReplacementRefused):
            trust.accept_replacement(self.store, text, lambda o, m, s: "yes")

    def test_malformed_statements_are_refused(self):
        good = trust.format_replacement(A, B, "aabb")
        bad = ["", "x", good.replace("v1", "v2"), good + "extra: 1\n", good.replace("signature: aabb", "signature: zz"),
               good.replace("signature: aabb", "signature: "), good.replace("old:", "older:"),
               good.replace("new: " + B, "old: " + B)]
        for text in bad:
            with self.assertRaises(trust.ReplacementRefused, msg=text):
                trust.parse_replacement(text)
        self.assertEqual(trust.parse_replacement(good), (A, B, bytes.fromhex("aabb")))


class TestFingerprintFormat(Base):
    def test_one_fingerprint_with_other_words_is_accepted(self):
        self.assertEqual(trust.parse_fingerprint(A.upper() + "  installer.exe\n"), A)
        self.assertEqual(trust.parse_fingerprint(f"# release\n{A}\n{A.upper()}\n"), A)

    def test_none_is_refused(self):
        for text in ("", "no hash", "a" * 63, "a" * 65, "z" * 64):
            with self.assertRaises(trust.FingerprintFormatError):
                trust.parse_fingerprint(text)

    def test_two_different_fingerprints_are_refused(self):
        with self.assertRaises(trust.FingerprintFormatError) as cm:
            trust.parse_fingerprint(f"{A} a.exe\n{B} b.exe\n")
        self.assertIn("2 different", str(cm.exception))

    def test_unreadable_file_is_typed(self):
        with self.assertRaises(trust.FingerprintFormatError):
            trust.read_fingerprint_file(self.tmp / "missing")
        (self.tmp / "bin").write_bytes(b"\xff\xfe\x00")
        with self.assertRaises(trust.FingerprintFormatError):
            trust.read_fingerprint_file(self.tmp / "bin")

    def test_build_uses_the_strict_parser(self):
        """The published file of SL-1 follows the same format: none or two different are PublishedMismatch."""
        f = self.tmp / "pub"
        f.write_text(f"{A}  x.exe\n")
        self.assertEqual(build.read_published(f), A)
        for text in ("", f"{A}\n{B}\n"):
            f.write_text(text)
            with self.assertRaises(build.PublishedMismatch):
                build.read_published(f)


class TestNsis(unittest.TestCase):
    def test_main_includes_trust_and_has_confirmation_screen(self):
        """INST-REQ-001, 003, 004: the screen exists in the installer source; main.nsi has one include line per .nsh."""
        main = (ROOT / "installer" / "nsis" / "main.nsi").read_text()
        self.assertIn('!include "trust.nsh"', main)
        nsh = (ROOT / "installer" / "nsis" / "trust.nsh").read_text()
        for needle in ("two independent places", "IfSilent", "$TrustStored", "$TrustSigner", "signer.sha256"):
            self.assertIn(needle, nsh)
        boxes = [ln for ln in nsh.splitlines() if ln.strip().startswith("MessageBox MB_YESNO")]
        self.assertEqual(len(boxes), 2)
        self.assertTrue(all("MB_DEFBUTTON2" in ln for ln in boxes), "Enter must never accept a fingerprint")
        self.assertEqual(nsh.count("Call TrustCanonicalHex64"), 2)
        self.assertIn("TrustStoreBad", nsh)  # an existing but damaged stored file is refused, not a first run
        self.assertEqual(nsh.count("IfErrors TrustWriteBad"), 2)
        self.assertIn('"$TrustStoreFile" r\n  IfErrors TrustStoreBad', nsh)  # unreadable existing file is refused
        for var in ("TrustSigner", "TrustStored"):
            self.assertIn(f'Pop ${var}\n  StrCmp ${var} "" ', nsh)
        self.assertIn('StrCmp $3 "$\\r$\\n" TrustTrimmed\n  Goto TrustStoreBad', nsh)  # trailing text is damage
        self.assertEqual(nsh.count("IfSilent TrustStopSilent\n  MessageBox MB_YESNO"), 2)  # silent runs never ask

    @unittest.skipUnless(shutil.which("makensis"), "makensis not installed")
    def test_nsis_compiles(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copytree(ROOT / "installer" / "nsis", Path(tmp) / "nsis")  # OutFile lands beside the script
        p = subprocess.run(["makensis", "-V1", str(Path(tmp) / "nsis" / "main.nsi")],
                           capture_output=True, text=True, timeout=120, cwd=tmp)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


if __name__ == "__main__":
    unittest.main()
