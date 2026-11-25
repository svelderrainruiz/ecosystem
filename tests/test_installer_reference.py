"""The checked-in NSIS reference must describe the code, not just its vocabulary."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from installer import reference


class ReferenceTests(unittest.TestCase):
    def test_unit_gate_runs_the_reference_check(self):
        result = subprocess.run([sys.executable, "-m", "installer.reference", "check"],
                                cwd=reference.NSIS.parent.parent, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rebuilt_reference_rejects_invalid_row_paths(self):
        for name, field, bad in (
                ("FileWrite", "doc", "docs/Commands/FileWrit.md"),
                ("FileWrite", "doc", "docs/Commands/FileRead.md"),
                ("$carried", "doc", "docs/Commands/Exch.md"),
                ("$carried", "doc", "docs/Commands/!define.md"),
                ("${ENGINE_EXE}", "doc", "docs/Commands/Var.md"),
                ("FileWrite", "anchor", "Source/exehead/exe.c#L1401"),
                ("FileWrite", "anchor", "docs/Commands/FileWrite.md#L1"),
                ("System::Call", "doc", "Contrib/System/Missing.html")):
            with self.subTest(name=name, field=field, bad=bad), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "nsis"
                shutil.copytree(reference.NSIS, root)
                table = reference.catalogue()
                table[name] = replace(table[name], **{field: bad})
                with patch.object(reference, "catalogue", return_value=table):
                    (root / "REFERENCE.md").write_bytes(reference.render(root).encode("utf-8"))
                    with self.assertRaises(reference.ReferenceError) as caught:
                        reference.check(root)
                self.assertIn(name, str(caught.exception))
                self.assertIn(bad.partition("#")[0], str(caught.exception))

    def test_logiclib_command_page_aliases_are_exact(self):
        pages = reference.catalogue()
        for name, stem in (("${Errors}", "IfErrors"), ("${Silent}", "IfSilent")):
            self.assertEqual(pages[name].doc, f"docs/Commands/{stem}.md")
        with patch.object(reference, "catalogue", return_value={
                "${Errors}": pages["${Errors}"], "${Silent}": pages["${Silent}"]}):
            reference.verify_command_pages()
        with patch.object(reference, "catalogue", return_value={
                "${Abort}": reference.Page("docs/Commands/IfAbort.md")}):
            with self.assertRaisesRegex(reference.ReferenceError, r"\$\{Abort\}.*docs/Commands/IfAbort\.md"):
                reference.verify_command_pages()

    def test_pin_refuses_a_wrong_command_page_before_any_io(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(reference, "catalogue", return_value={
                    "FileWrite": reference.Page("docs/Commands/FileRead.md")}), \
                    patch.object(reference, "tree_paths", side_effect=AssertionError("tree read")) as trees:
                with self.assertRaisesRegex(reference.ReferenceError, r"FileWrite.*docs/Commands/FileRead\.md"):
                    reference.pin(root, root / "docs", root / "source")
            trees.assert_not_called()
            self.assertEqual(list(root.iterdir()), [])

    def test_command_page_stem_is_case_sensitive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "example.nsi").write_text('StrCpy $0 "test"\n')
            shutil.copy(reference.NSIS / reference.MANIFEST, root)
            table = reference.catalogue()
            with patch.object(reference, "catalogue", return_value={"strcpy": table["StrCpy"], "$0": table["$0"]}):
                (root / "REFERENCE.md").write_bytes(reference.render(root).encode("utf-8"))
                with self.assertRaisesRegex(reference.ReferenceError, r"strcpy.*docs/Commands/StrCpy\.md"):
                    reference.check(root)

    def test_only_a_token_initial_quote_protects_comment_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for quote in "'\"`":
                with self.subTest(quote=quote):
                    (root / "quote.nsi").write_text(
                        f"DetailPrint it{quote}s ; $NoSuchVar\n"
                        f"DetailPrint\t{quote}; $Visible{quote} ; $Hidden\n")
                    self.assertEqual(set(reference.collect(root)), {"DetailPrint", "$Visible"})

    def test_closing_quote_starts_the_next_token_without_whitespace(self):
        self.assertEqual(list(reference.code_lines('"a""; $Visible"; $Hidden')),
                         [(1, '"a""; $Visible"', False)])

    def test_pin_is_byte_identical_after_checkout_changes(self):
        def git(repo, *args):
            return subprocess.check_output(["git", "-C", repo, "-c", "user.name=Test",
                                            "-c", "user.email=test@example.invalid",
                                            "-c", "commit.gpgsign=false", *args], text=True).strip()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs, source = root / "manual", root / "source"
            for repo, paths in ((docs, ("docs/Used.md", "docs/sub/Unused.md", "Top.md", "docs/Skip.txt")),
                                (source, ("src/file.c", "src/other.c", "Manual.html"))):
                repo.mkdir()
                git(repo, "init", "-q")
                for path in paths:
                    (repo / path).parent.mkdir(parents=True, exist_ok=True)
                    (repo / path).touch()
                git(repo, "add", ".")
                git(repo, "commit", "-qm", "pin")
            git(source, "tag", "--no-sign", reference.SOURCE_TAG)
            pages = {"command": reference.Page("docs/Used.md", "src/file.c#L1"),
                     "plugin": reference.Page("Manual.html")}
            with patch.object(reference, "NSIS", root), patch.object(reference, "catalogue", return_value=pages), \
                    patch.object(reference, "DOC_COMMIT", git(docs, "rev-parse", "HEAD")):
                args = ["pin", "--docs", str(docs), "--source", str(source)]
                self.assertEqual(reference.main(args), 0)
                manifest = root / "reference-pins.txt"
                first = manifest.read_bytes()
                self.assertEqual(first.splitlines(), [b"doc\tdocs/Used.md", b"doc\tdocs/sub/Unused.md",
                                                      b"source\tManual.html", b"source\tsrc/file.c"])
                for repo, path in ((docs, "docs/Used.md"), (source, "src/file.c")):
                    git(repo, "rm", "-q", path)
                    git(repo, "commit", "-qm", "move checkout beyond pin")
                manifest.unlink()
                self.assertEqual(reference.main(args), 0)
                self.assertEqual(manifest.read_bytes(), first)

    def test_check_rejects_drift(self):
        for change, expected in (("extra site", "stale"), ("new token", "ExecWait"),
                                 ("missing row", "nsExec::Exec"), ("last use gone", "FileSeek"),
                                 ("hand edit", "stale")):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "nsis"
                shutil.copytree(reference.NSIS, root)
                table = reference.catalogue()
                if change in ("extra site", "new token"):
                    (root / "new.nsh").write_text(
                        'nsExec::Exec "example"\n' if change == "extra site" else 'ExecWait "example"\n')
                elif change == "missing row":
                    del table["nsExec::Exec"]
                elif change == "last use gone":
                    path = root / "log.nsh"
                    before = path.read_text()
                    self.assertEqual(before.count("\n  FileSeek "), 1)
                    path.write_text(before.replace("\n  FileSeek ", "\n  ;FileSeek "))
                else:
                    path = root / "REFERENCE.md"
                    path.write_text(path.read_text().replace("# NSIS", "# XSIS", 1))
                with patch.object(reference, "catalogue", return_value=table):
                    with self.assertRaisesRegex(reference.ReferenceError, expected):
                        reference.check(root)

    def test_tokens_come_from_syntax_not_from_the_knowledge_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sub").mkdir()
            (root / "sub/example.nsh").write_text(
                "; nsExec::Bogus $ignored\n"
                'here: StrCpy $0 "quoted ; # $APPDATA $$literal" ; ${Ignore}\n'
                "/*\nUnknown::Ignored\n*/\n"
                'Unknown::New "$1" \\\n'
                '  "$2"\n'
                '  ${If} ${UnexpectedPredicate}\n'
                '  !insertmacro UnseenMacro\n'
                '  ${${P}GetFileAttributes} "$R0" "DIRECTORY" $R1\n')
            uses = reference.collect(root)
            self.assertEqual(set(uses), {"StrCpy", "$0", "$APPDATA", "Unknown::New", "$1", "$2",
                                         "${If}", "${UnexpectedPredicate}", "!insertmacro",
                                         "${UnseenMacro}", "${P}", "${GetFileAttributes}",
                                         "${un.GetFileAttributes}", "$R0", "$R1"})
            self.assertEqual(uses["$2"], {("sub/example.nsh", 7)})
