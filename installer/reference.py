"""Build or check the offline index of NSIS language items used by the installer."""
import argparse
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from itertools import groupby
from pathlib import Path


NSIS = Path(__file__).resolve().parent / "nsis"
DOC_COMMIT = "62da8911c4e488bb5df8bebb475f3930aca13ecd"
SOURCE_TAG = "v310"
DOC_REPO = "github.com/nsis-dev/Documentation"
SOURCE_REPO = "github.com/nsis-dev/nsis"
MANIFEST = "reference-pins.txt"


class ReferenceError(Exception):
    """A source item or the generated reference is not accounted for."""


@dataclass(frozen=True)
class Page:
    doc: str
    anchor: str = ""
    note: str = ""


def catalogue():
    """Only knowledge lives here; no project file names, line numbers or use counts."""
    pages = {}
    for cmd in """!define !else !endif !error !ifdef !ifndef !include !insertmacro !macro !macroend
                  !pragma Abort BrandingText Call Caption ClearErrors CopyFiles CreateDirectory Delete DeleteRegKey
                  DetailPrint EnableWindow Exch ExecShell File FileClose FileOpen FileRead FileSeek FileWrite FindClose
                  FindFirst FindNext Function FunctionEnd GetDlgItem Goto IfErrors IfFileExists IfSilent
                  IntCmp IntFmt IntOp MessageBox OutFile Page Pop Push Quit ReadRegDWORD ReadRegStr
                  RequestExecutionLevel Return RMDir Section SectionEnd SendMessage SetErrorLevel SetErrors
                  SetOverwrite SetRegView SetShellVarContext Sleep StrCmp StrCmpS StrCpy StrLen UninstallCaption
                  Unicode Var WriteRegStr WriteUninstaller""".split():
        pages[cmd] = Page(f"docs/Commands/{cmd}.md")

    # The line is the dispatch case at v310, not a line in the current upstream tree.
    runtime = {
        "Abort": (288, "Stops the current operation; in a page callback, prevents page progression."),
        "Call": (298, ""), "ClearErrors": (321, "Clear a stale flag immediately before a checked operation."),
        "CopyFiles": (1149, "A failed copy sets the flag; do not treat it as a completed backup or restore."),
        "CreateDirectory": (368, "Failure to create the directory sets the flag."),
        "Delete": (608, "Deletion failure can set the flag; the cleanup path also checks what remains."),
        "DeleteRegKey": (1237, "A failed registry deletion sets the flag."),
        "DetailPrint": (304, ""), "EnableWindow": (889, ""), "Exch": (771, "Exchange an argument or result with the stack."),
        "ExecShell": (903, "Launch failure sets the flag; a successful launch does not clear an old error."),
        "File": (510, "Extraction uses SetOverwrite; a fatal extraction error can abort, not just set the flag."),
        "FileClose": (1378, "Closing the handle does not clear an earlier open or write error."),
        "FileOpen": (1384, "Returns a handle, or an empty string and the error flag on failure."),
        "FileRead": (1440, "Returns the line; EOF with no characters or a failed read sets the flag."),
        "FileSeek": (1507, "Moves the step-log handle to the end; no position result is requested."),
        "FileWrite": (1401, "Write failure sets the flag. The step-log writes are best effort."),
        "FindClose": (1524, "Releases the search handle without consuming the error flag."),
        "FindFirst": (1547, "Returns a handle and name; on failure both are empty and the flag is set."),
        "FindNext": (1530, "Returns the next name, or an empty name and the flag at end or on error."),
        "GetDlgItem": (845, "Returns the HWND used to enable or disable a dialog button."),
        "Goto": (285, ""), "IfErrors": (342, "Branches on the old error flag and clears it on either path."),
        "IfFileExists": (418, ""), "IfSilent": (342, ""), "IntCmp": (711, ""),
        "IntFmt": (763, "Formats a number into the destination string."),
        "IntOp": (737, "Returns the arithmetic result; divide or remainder by zero sets the error flag."),
        "MessageBox": (617, "Uses the chosen or silent-default button ID for control flow."),
        "Pop": (771, "Consumes the top result string; popping an empty stack sets the flag."),
        "Push": (771, "Pass a string argument or result on the stack."), "Quit": (294, ""),
        "ReadRegDWORD": (1320, "Read the bias as a decimal string; missing or wrong type sets the flag."),
        "ReadRegStr": (1320, "Read the zone name; a missing value or type mismatch sets the flag."),
        "RMDir": (639, "Removal may set the flag; cleanup must not recurse through a reparse point."),
        "SendMessage": (812, "Set control limits; a timed send can set the flag on timeout."),
        "SetErrors": (321, "Set the flag so the caller can distinguish a miss from an empty value."),
        "SetErrorLevel": (321, "Sets the process exit code, not the error flag."),
        "SetRegView": (321, "Selects the registry view for subsequent accesses, independently of shell context."),
        "SetShellVarContext": (321, "Selects current-user or all-users shell folders for subsequent expansions."),
        "Sleep": (308, ""), "StrCmp": (680, ""), "StrCmpS": (680, ""),
        "StrCpy": (655, "Copies a string or substring into the destination variable."),
        "StrLen": (649, "Stores the string length in the destination variable."),
        "WriteRegStr": (1262, "Publishes an uninstall value in the selected view; failure sets the flag."),
        "WriteUninstaller": (1570, "Failure sets the flag; success does not clear a stale flag before IfErrors."),
    }
    for cmd, (line, note) in runtime.items():
        pages[cmd] = Page(pages[cmd].doc, f"Source/exehead/exec.c#L{line}", note)
    pages["SetOverwrite"] = Page(pages["SetOverwrite"].doc, "Source/exehead/exec.c#L510",
                                 "Selects extraction policy; a fatal File error need not return to IfErrors.")

    for name, line in (("AndIf", 459), ("Do", 643), ("Else", 512), ("ElseIf", 529), ("EndIf", 551),
                       ("ExitDo", 656), ("If", 437), ("IfNot", 439), ("Loop", 689), ("OrIf", 490)):
        pages["${" + name + "}"] = Page(f"docs/Includes/LogicLib/{name}.md", f"Include/LogicLib.nsh#L{line}")
    for name, cmd, line, note in (
        ("Errors", "IfErrors", 331, "LogicLib tests and consumes the flag via IfErrors."),
        ("Silent", "IfSilent", 346, "Test whether there is an interactive operator.")):
        pages["${" + name + "}"] = Page(pages[cmd].doc, f"Include/LogicLib.nsh#L{line}", note)
    for name, header, line, note in (
        ("GetTime", "FileFunc", 1082, "Returns separate date and time fields for the step log."),
        ("GetFileAttributes", "FileFunc", 1218, "Returns 1 or 0 for a tested attribute; empty and error on failure."),
        ("un.GetFileAttributes", "FileFunc", 1218, "Uninstaller form: same attribute result and error contract."),
        ("StrCase", "StrFunc", 158, "Returns the case-normalized field value."),
        ("StrStr", "StrFunc", 1063, "Returns the suffix starting at the match, or an empty string.")):
        pages["${" + name + "}"] = Page(f"docs/Includes/{header}/{name.removeprefix('un.')}.md",
                                        f"Include/{header}.nsh#L{line}", note)
    for item, doc, anchor, note in (
        ("nsExec::Exec", "docs/Plugins/nsExec.md", "Contrib/nsExec/nsexec.c#L49",
         "Pop one status string: decimal exit code, error, or timeout."),
        ("nsExec::ExecToStack", "docs/Plugins/nsExec.md", "Contrib/nsExec/nsexec.c#L489",
         "Pop status first, then captured output; error and timeout are strings, not exit codes."),
        ("nsDialogs::Create", "Contrib/nsDialogs/Readme.html", "Contrib/nsDialogs/nsDialogs.c#L265",
         "Pop the HWND or error; abort on error before creating controls."),
        ("nsDialogs::Show", "Contrib/nsDialogs/Readme.html", "Contrib/nsDialogs/nsDialogs.c#L590",
         "Shows the created page and handles interaction until it closes."),
        ("System::Call", "Contrib/System/System.html", "Contrib/System/Source/System.c#L370",
         "Calls a native function or constructs a struct; .s returns on the stack, .rN in register N."),
        ("System::Free", "Contrib/System/System.html", "Contrib/System/Source/System.c#L228",
         "Release the struct allocated by System::Call, not the Win32 security descriptor."),
        ("UserInfo::GetAccountType", "Contrib/UserInfo/UserInfo.nsi", "Contrib/UserInfo/UserInfo.c#L166",
         "Pop the account type string and compare with Admin; it is not an error-flag result.")):
        pages[item] = Page(doc, anchor, note)
    for name in ("Label", "Text", "Password", "Checkbox", "RadioButton", "FirstRadioButton", "AdditionalRadioButton", "DropList"):
        pages["${NSD_Create" + name + "}"] = Page("Contrib/nsDialogs/Readme.html", "Contrib/nsDialogs/nsDialogs.nsh#L407",
                                                  "The created control's HWND is returned on the stack.")
    for name, line, note in (("GetText", 590, "Copies the current text to the destination variable."),
                             ("GetState", 652, "Returns the check state for comparison with BST_CHECKED."),
                             ("Check", 663, "Sets the control to checked."),
                             ("CB_AddString", 680, "Appends one item to a drop-down list (CB_ADDSTRING; the list is not sorted)."),
                             ("OnChange", 477, "Calls the function when the selection changes, the control handle on the stack: Pop it.")):
        pages["${NSD_" + name + "}"] = Page("Contrib/nsDialogs/Readme.html", f"Contrib/nsDialogs/nsDialogs.nsh#L{line}", note)
    for name, line in (("EM_LIMITTEXT", 199), ("BST_CHECKED", 131), ("CB_RESETCONTENT", 161), ("CB_SETCURSEL", 163)):
        pages["${" + name + "}"] = Page("Include/WinMessages.nsh", f"Include/WinMessages.nsh#L{line}")

    for name in "CMDLINE EXEDIR EXEFILE EXEPATH HWNDPARENT SYSDIR PROGRAMFILES64 APPDATA LOCALAPPDATA".split():
        doc = name.removesuffix("64")
        if name in ("APPDATA", "LOCALAPPDATA"):
            pages["$" + name] = Page(f"docs/Variables/{doc}.md", "Source/exehead/util.c#L878",
                                     "Resolves in the active shell context; all users selects common application data.")
        else:
            pages["$" + name] = Page(f"docs/Variables/{doc}.md")
    for name in "0 1 2 3 4 5 7 9 R0 R1 R2 R3 R4 R5 R6 R7 R8 R9".split():
        pages["$" + name] = Page("Docs/src/var.but", "Docs/src/var.but#L30", "Shared scratch register; not function-local.")

    for name in """carried carry_args carry_bad carry_k carry_l carry_n carry_q carry_room carry_t carry_v
                   cl_c cl_eq cl_key cl_name cl_pos cl_q cl_qi cl_qv cl_raw cl_text cl_tok cl_val
                   ctl_allow_list ctl_dns_servers ctl_engine_licence_accepted ctl_github_token ctl_github_url
                   ctl_gitlab_token ctl_gitlab_url ctl_http_proxy ctl_image_variant ctl_image_year ctl_install_dir
                   ctl_labview_version ctl_mode_github ctl_mode_gitlab ctl_mode_local ctl_ni_licence_held
                   ctl_partner_id ctl_registry_password ctl_work_dir elev_isadmin ImgEngine ImgRef
                   in_allow_list in_dns_servers in_engine_licence_accepted in_github_token in_github_url
                   in_gitlab_token in_gitlab_url in_http_proxy in_image_variant in_image_year in_install_dir
                   in_labview_version in_mode in_ni_licence_held in_partner_id in_registry_password
                   InstallHandle in_work_dir LicHandle LogBias LogCommand LogD LogExistingOnly LogExit LogH
                   LogHandle LogMi LogMo LogPath LogS LogStepName LogT1 LogT2 LogT3 LogT4 LogY LogZone
                   MachineFolder runner_mode tree_depth TrustAsk TrustSigner TrustStored TrustStoreFile TrustText
                   TrustTyped unelev_isadmin
                   upd_a0 upd_a1 upd_a2 upd_acc upd_b0 upd_b1 upd_b2 upd_c upd_code upd_fhas upd_fval upd_h
                   upd_hay upd_i upd_json upd_k upd_line upd_mode upd_msg upd_n upd_needle upd_ok upd_old
                   upd_online upd_parts upd_pos upd_svc upd_t upd_ver vs_c vs_kind vs_name winsys_code
                   winsys_ok winsys_state""".split():
        pages["$" + name] = Page("docs/Commands/Var.md")
    for name in "ENGINE_EXE INSTALLER_VERSION OUTFILE RUNNER_PAYLOAD RUNNER_TEST_BUILD TREE_NSH TREE_ROOT".split():
        pages["${" + name + "}"] = Page("docs/Commands/!define.md")
    for name in "Dialog_Create LogUnpad LogWriteField ParseSilentKeys RefuseLongCommandLine RefuseSecretOptions Tree_Define ValidateSilentKeys P var".split():
        pages["${" + name + "}"] = Page("docs/Commands/!macro.md")
    pages[".onInit"] = Page("docs/Callbacks/onInit.md")
    pages["un.onInit"] = Page("docs/Callbacks/un.onInit.md")
    return pages


# Dollar escapes in an embedded PowerShell string are literals, not NSIS variable uses.
EXPANSION = re.compile(r"\$\$|\$\\.|(\$\{\$\{P\}(\w+)\})|(\$\{[^}]+\}|\$[A-Za-z0-9_]+)")


def code_lines(text):
    """Yield physical lines minus comments, retaining quoted text and source coordinates."""
    block = False
    quote = ""
    token_start = True
    more = False
    for number, line in enumerate(text.splitlines(), 1):
        if more:
            line = line.lstrip(" \t")
        chars = []
        i = 0
        while i < len(line):
            if block:
                end = line.find("*/", i)
                if end == -1:
                    break
                i, block = end + 2, False
            elif line.startswith(("$\\", "$$"), i):
                width = 3 if line[i + 1] == "\\" else 2
                chars.append(line[i:i + width])
                token_start = False
                i += width
            elif not quote and line.startswith("/*", i):
                chars.append(" ")
                block = True
                token_start = True
                i += 2
            elif not quote and line[i] in "#;":
                break
            else:
                char = line[i]
                if char == quote:
                    quote = ""
                    token_start = True
                # v310 Source/lineparse.cpp:344-350 tests for quotes before scanning a token.
                elif token_start and not quote and char in "'\"`":
                    quote = char
                    token_start = False
                elif char != "\\" or line[i + 1:].strip():
                    token_start = not quote and char in " \t"
                chars.append(char)
                i += 1
        code = "".join(chars).strip()
        more = code.endswith("\\")
        yield number, code[:-1].rstrip() if more else code, more
        if not more:
            quote = ""
            token_start = True


def collect(root):
    uses = defaultdict(set)
    for path in sorted(root.rglob("*")):
        if path.suffix.lower() not in {".nsi", ".nsh"} or not path.is_file():
            continue
        continuation = False
        for number, code, more in code_lines(path.read_text(encoding="utf-8-sig")):
            site = (path.relative_to(root).as_posix(), number)
            words = code.split()
            if not continuation:
                while words and words[0].endswith(":"):
                    words.pop(0)
                if words:
                    op = words[0]
                    if not op.startswith("${"):
                        uses[op].add(site)
                    if len(words) > 1:
                        if op.lower() in {"!ifdef", "!ifndef", "!define", "!insertmacro", "!macro"}:
                            uses["${" + words[1] + "}"].add(site)
                        elif op.lower() == "var":
                            uses["$" + words[-1]].add(site)
                        elif op.lower() == "function" and words[1].lower().startswith((".", "un.on")):
                            uses[words[1]].add(site)
            for match in EXPANSION.finditer(code):
                if match[1]:
                    # Tree_Define is instantiated for the installer and uninstaller.
                    for item in ("${P}", "${" + match[2] + "}", "${un." + match[2] + "}"):
                        uses[item].add(site)
                elif match[3]:
                    uses[match[3]].add(site)
            continuation = more
    return uses


def link(repo, revision, path):
    return f"[`{path}`](https://{repo}/blob/{revision}/{path})"


def render(root):
    table = catalogue()
    names = {name.casefold(): name for name in table}
    sites = defaultdict(set)
    for token, locations in collect(root).items():
        sites[names.get(token.casefold(), token)].update(locations)
    unknown = sites.keys() - table.keys()
    unused = table.keys() - sites.keys()
    if unknown or unused:
        problems = [f"unlisted {name} at {min(sites[name])}" for name in sorted(unknown)]
        problems.extend(f"unused {name}" for name in sorted(unused))
        raise ReferenceError("; ".join(problems))
    lines = [
        "# NSIS reference", "",
        "Generated by `python3 -m installer.reference build`. Do not edit by hand.", "",
        f"Documentation: `nsis-dev/Documentation@{DOC_COMMIT}`. Source: `nsis-dev/nsis@{SOURCE_TAG}`.",
        "When the docs omit an item, the page links to the upstream source manual, example or header instead.",
        "The source wins on behavior. Sites include declarations and both sides of compile-time conditionals.", "",
        "| Item | Doc page | v3.10 source | Our files and lines | What we rely on |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name in sorted(table, key=str.casefold):
        page = table[name]
        upstream = (DOC_REPO, DOC_COMMIT) if page.doc.startswith("docs/") else (SOURCE_REPO, SOURCE_TAG)
        locations = []
        for filename, group in groupby(sorted(sites[name]), key=lambda site: site[0]):
            numbers = ", ".join(str(n) for _, n in group)
            locations.append(f"[{filename}]({filename}): {numbers}")
        anchor = link(SOURCE_REPO, SOURCE_TAG, page.anchor) if page.anchor else "-"
        lines.append(f"| `{name}` | {link(*upstream, page.doc)} | {anchor} | {'; '.join(locations)} | {page.note} |")
    return "\n".join(lines) + "\n"


def row_paths():
    for name, page in catalogue().items():
        kind = "doc" if page.doc.startswith("docs/") else "source"
        yield name, f"{kind}\t{page.doc.partition('#')[0]}"
        if page.anchor:
            yield name, f"source\t{page.anchor.partition('#')[0]}"


def verify_paths(paths):
    for name, entry in row_paths():
        if entry not in paths:
            raise ReferenceError(f"{name}: missing pinned {entry}")


# v310 Include/LogicLib.nsh:328-331 (_Errors runs IfErrors), 343-346 (_Silent runs IfSilent).
LOGICLIB_COMMAND_STEMS = {"${Errors}": "IfErrors", "${Silent}": "IfSilent"}


def verify_command_pages():
    for name, page in catalogue().items():
        if not page.doc.startswith("docs/Commands/"):
            continue
        stems = {name}
        if name.startswith("${"):
            stems.update(("!define", "!macro"))
            if name in LOGICLIB_COMMAND_STEMS:
                stems.add(LOGICLIB_COMMAND_STEMS[name])
        elif name.startswith("$"):
            stems.add("Var")
        if Path(page.doc.partition("#")[0]).stem not in stems:
            raise ReferenceError(f"{name}: wrong Commands page {page.doc}")


def tree_paths(repo, revision, *paths):
    result = subprocess.run(["git", "-C", repo, "ls-tree", "-rz", "--name-only", revision, "--", *paths],
                            capture_output=True)
    if result.returncode:
        raise ReferenceError(f"cannot list pinned tree {revision} in {repo}")
    return result.stdout.decode("utf-8").split("\0")[:-1]


def pin(root, docs, source):
    verify_command_pages()
    paths = {f"doc\t{p}" for p in tree_paths(docs, DOC_COMMIT, "docs") if p.endswith(".md")}
    wanted = {entry for _, entry in row_paths() if entry.startswith("source\t")}
    paths.update(wanted.intersection(f"source\t{p}" for p in tree_paths(source, SOURCE_TAG)))
    verify_paths(paths)
    (root / MANIFEST).write_bytes(("\n".join(sorted(paths)) + "\n").encode("utf-8"))


def check(root=NSIS):
    verify_command_pages()
    verify_paths(set((root / MANIFEST).read_text(encoding="utf-8").splitlines()))
    expected = render(root).encode("utf-8")
    path = root / "REFERENCE.md"
    if not path.is_file() or path.read_bytes() != expected:
        raise ReferenceError("REFERENCE.md is stale; run python3 -m installer.reference build")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("build")
    actions.add_parser("check")
    pins = actions.add_parser("pin")
    pins.add_argument("--docs", required=True, type=Path)
    pins.add_argument("--source", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == "build":
            (NSIS / "REFERENCE.md").write_bytes(render(NSIS).encode("utf-8"))
        elif args.action == "pin":
            pin(NSIS, args.docs, args.source)
        else:
            check()
    except (ReferenceError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
