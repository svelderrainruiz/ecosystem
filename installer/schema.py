"""Input schema (ARCH-3) and host check (ARCH-4): one schema.json generates the interactive screens and the silent keys.

`python -m installer.schema generate` rewrites installer/nsis/screens.nsh; `check` fails when the committed file differs from the schema.
The silent mode never takes a secret (INST-REQ-023, 075, 098); every refusal is a typed error with its own exit code (INST-REQ-026).
Nothing here reads, stores or prints a secret value: error text carries the option NAME only."""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "schema.json"
SCREENS_PATH = HERE / "nsis" / "screens.nsh"
SILENT_FLAG = "/S"


class SchemaError(Exception):
    """Expected refusal; `kind` selects the exit code in schema.json."""
    kind = "bad-value"


class BadValue(SchemaError):
    kind = "bad-value"


class UnknownKey(SchemaError):
    kind = "unknown-key"


class SecretOnCommandLine(SchemaError):
    kind = "secret-on-command-line"


class SecretFromFileOrStdin(SchemaError):
    kind = "secret-from-file-or-stdin"


class EditionRefused(SchemaError):
    kind = "edition-refused"


class LicenceNotAccepted(SchemaError):
    kind = "licence-not-accepted"


class ImageNotPinned(SchemaError):
    kind = "image-not-pinned"


class StateNotWritable(SchemaError):
    kind = "state-not-writable"


class CommandLineTooLong(SchemaError):
    kind = "cmdline-too-long"


# NSD_GetText reads at most 1023 characters; a longer value would be cut and the cut value kept.
TEXT_LIMIT = 1023
# NSIS keeps at most 1023 characters of $CMDLINE (the cut is silent, REPORT L2 C10): a line of 1023 or more is refused with exit 50 (#136).
COMMAND_LINE_LIMIT = 1023
# A page with a help text (issue 329): the help label at the top holds two lines; then each field is a label at y (8u) and its box at y+9 (12u),
# and the next field starts at y+24, so nothing overlaps. A page without help keeps the old 18u pitch, where a box overlaps the next label by 2u.
HELP_HEIGHT = 20
FIELD_PITCH = 24

def load_schema(path=SCHEMA_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def exit_code(schema, error=None):
    codes = schema["exit_codes"]
    return codes["ok"] if error is None else codes[error.kind]


def silent_key(input_id):
    return "/" + input_id.upper()


def public_inputs(schema):
    return [i for i in schema["inputs"] if i["kind"] != "secret"]


def secret_inputs(schema):
    return [i for i in schema["inputs"] if i["kind"] == "secret"]


def screen_list(schema):
    """Screens in page order: each page with its input ids (what the interactive pages show)."""
    return [{"page": p["id"], "title": p["title"], "inputs": [i["id"] for i in schema["inputs"] if i["page"] == p["id"]]}
            for p in schema["pages"]]


def silent_keys(schema):
    """Silent keys: one per non-secret input; secrets have a screen only (D-R6-2)."""
    return {silent_key(i["id"]): i["id"] for i in public_inputs(schema)}


def wired_inputs(schema):
    """Inputs whose choice is acted on at once: typed value in $in_<id>, control handles in $ctl_<id>_<choice>, one setter function per choice."""
    return [i for i in schema["inputs"] if i.get("setter")]


def setter_name(spec, choice):
    return spec["setter"] + choice.capitalize()


def _wired_page(spec, schema, top=4):
    """Radio group, Leave callback (the choice calls its setter; no choice stays on the page) and the silent selection."""
    i, ctl = spec["id"], "ctl_%s_" % spec["id"]
    labels = spec.get("choice_labels", {})
    out = []
    for n, c in enumerate(spec["choices"]):
        macro = "${NSD_CreateFirstRadioButton}" if n == 0 else "${NSD_CreateAdditionalRadioButton}"
        out += ['  %s 0u %du 100%% 12u "%s"' % (macro, top + n * 16, labels.get(c, c).replace('"', "'")), "  Pop $%s%s" % (ctl, c)]
    out += ["  nsDialogs::Show", "FunctionEnd", "", "Function Page_%s_Leave" % i, '  StrCpy $in_%s ""' % i]
    for c in spec["choices"]:
        out += ["  ${NSD_GetState} $%s%s $0" % (ctl, c), "  ${If} $0 == ${BST_CHECKED}", '    StrCpy $in_%s "%s"' % (i, c), "  ${EndIf}"]
    out += ['  ${If} $in_%s == ""' % i,
            '    MessageBox MB_OK|MB_ICONEXCLAMATION "Choose what this PC does, then select Next." /SD IDOK', "    Abort", "  ${EndIf}",
            "  Call Runner_Clear"]
    for n, c in enumerate(spec["choices"]):
        out.append('  ${%s} $in_%s == "%s"' % ("If" if n == 0 else "ElseIf", i, c))
        out.append("    Call %s" % setter_name(spec, c))
    out += ["  ${EndIf}", "FunctionEnd", "", "; Silent run: no key leaves the mode alone; a value that is none of the choices ends with the bad-value exit before anything is written.",
            "Function %s_FromSilent" % i.capitalize(), '  Push "%s="' % silent_key(i), "  Call Cmdline_Get", "  Pop $0", "  ${If} ${Errors}", "    Return", "  ${EndIf}",
            '  ${StrCase} $in_%s $0 "L"' % i]
    for c in spec["choices"]:
        out += ['  ${If} $in_%s == "%s"' % (i, c), "    Call %s" % setter_name(spec, c), "    Return", "  ${EndIf}"]
    out += ['  Push "%s"' % silent_key(i), "  Call Carried_Box", '  Push "%s"' % i, '  Push "%s"' % silent_key(i), '  Push "%d"' % schema["exit_codes"]["bad-value"], "  Call LogStep",
            "  SetErrorLevel %d" % schema["exit_codes"]["bad-value"], "  Quit", "FunctionEnd"]
    return out


_BAD_TEXT = re.compile("[\\x00-\\x20\\x7f\"'`\\\\]")
PASS_THROUGH = ("/S", "/D", "/NCRC", "/ELEVATED", "/SIGNER")
TOGETHER = ("image_variant", "image_year")
TOGETHER_TEXT = "Choose both the NI docker image container type and year, or neither"
_Q = '"'


def _nl(v):
    return v.replace("\t", "$\\t").replace("\r", "$\\r").replace("\n", "$\\n")


def _helper_lines():
    """Fixed NSIS helpers: the value is in $R0, the answer in $R9 (empty means good, else the reason). Scratch: $R1 to $R7."""
    def bad(text, ret=True):
        return ['    StrCpy $R9 "%s"' % text] + (["    Return"] if ret else [])
    def stop(text):
        return ["  ${If} $R9 != \"\"", "    Return", "  ${EndIf}"]
    out = ["", "; One value at a time: $R0 in, $R9 out (empty = good). Control characters other than tab, CR and LF are not looked for.",
           "Function Val_Line", '  StrCpy $R9 ""', "  StrLen $R2 $R0", "  StrCpy $R3 0", "  StrCpy $R4 0", "  ${Do}", "    ${If} $R3 >= $R2", "      ${ExitDo}", "    ${EndIf}",
           "    StrCpy $R1 $R0 1 $R3", '    ${If} $R1 == "$\\t"', '    ${OrIf} $R1 == "$\\r"', '    ${OrIf} $R1 == "$\\n"'] + bad("must be on one line") + [
           "    ${EndIf}", '    ${If} $R1 != " "', "      StrCpy $R4 1", "    ${EndIf}", "    IntOp $R3 $R3 + 1", "  ${Loop}", "  ${If} $R4 == 0"] + bad("must not be blank", False) + ["  ${EndIf}", "FunctionEnd",
           "", "Function Val_NoQuote", '  StrCpy $R9 ""', "  StrCpy $R5 '\"'", "  ${StrStr} $R1 $R0 $R5", '  ${If} $R1 != ""'] + bad("must not contain a double quote", False) + ["  ${EndIf}", "FunctionEnd",
           "", "Function Val_NoBad", '  StrCpy $R9 ""']
    for needle in (" ", "$\\t", "$\\r", "$\\n", "'\"'", "\"'\"", "\"`\"", "\"\\\""):
        if needle in ("'\"'", "\"`\""):
            out.append("  StrCpy $R5 %s" % needle)
            n = "$R5"
        else:
            n = needle if needle[0] in "'\"" else '"%s"' % needle
        out += ["  ${StrStr} $R1 $R0 %s" % n, '  ${If} $R1 != ""'] + bad("must not hold a space, quote, backslash or control character") + ["  ${EndIf}"]
    out += ["FunctionEnd", "", "Function Val_Http", '  StrCpy $R9 ""', "  StrCpy $R1 $R0 8", '  ${If} $R1 S== "https://"', "    StrCpy $R2 8", "  ${Else}", "    StrCpy $R1 $R0 7",
            '    ${If} $R1 S== "http://"', "      StrCpy $R2 7", "    ${Else}"] + ["  " + x for x in bad("must start with http:// or https://")] + ["    ${EndIf}", "  ${EndIf}",
            "  StrCpy $R1 $R0 1 $R2", '  ${If} $R1 == ""', '  ${OrIf} $R1 == "/"', '  ${OrIf} $R1 == " "', '  ${OrIf} $R1 == "$\\t"', '  ${OrIf} $R1 == "$\\r"', '  ${OrIf} $R1 == "$\\n"'] + bad("needs a host after the scheme", False) + ["  ${EndIf}", "FunctionEnd",
            "", "; https only, a host, no user name or password, no brackets, an optional port of one to five digits (the same rule as installer.schema._https_problem).",
            "Function Val_Https", "  Call Val_NoBad"] + stop("") + ["  StrCpy $R1 $R0 8", '  ${If} $R1 != "https://"'] + bad("must start with https://") + [
            "  ${EndIf}", "  StrLen $R2 $R0", "  StrCpy $R3 8", '  StrCpy $R5 ""', "  ${Do}", "    ${If} $R3 >= $R2", "      ${ExitDo}", "    ${EndIf}", "    StrCpy $R1 $R0 1 $R3",
            '    ${If} $R1 == "/"', '    ${OrIf} $R1 == "?"', '    ${OrIf} $R1 == "#"', "      ${ExitDo}", "    ${EndIf}", '    StrCpy $R5 "$R5$R1"', "    IntOp $R3 $R3 + 1", "  ${Loop}",
            '  ${If} $R5 == ""'] + bad("needs a host after https://") + ["  ${EndIf}"]
    for ch in ("@", "[", "]"):
        out += ['  ${StrStr} $R4 $R5 "%s"' % ch, '  ${If} $R4 != ""'] + bad("must be a plain host name: no user name, password or brackets") + ["  ${EndIf}"]
    out += ["  StrCpy $R1 $R5 1", '  ${If} $R1 == ":"'] + bad("needs a host after https://") + ["  ${EndIf}", '  ${StrStr} $R4 $R5 ":"', '  ${If} $R4 != ""', '    StrCpy $R6 $R4 "" 1',
            "    StrLen $R7 $R6", "    ${If} $R7 == 0", "    ${OrIf} $R7 > 5"] + ["  " + x for x in bad("has a port that is not one to five digits")] + ["    ${EndIf}", "    StrCpy $R3 0", "    ${Do}",
            "      ${If} $R3 >= $R7", "        ${ExitDo}", "      ${EndIf}", "      StrCpy $R1 $R6 1 $R3", '      ${StrStr} $R4 "0123456789" $R1', '      ${If} $R4 == ""'] + ["    " + x for x in bad("has a port that is not one to five digits")] + [
            "      ${EndIf}", "      IntOp $R3 $R3 + 1", "    ${Loop}", "  ${EndIf}", "FunctionEnd",
            "", "Function Val_List", '  StrCpy $R9 ""', "  StrLen $R2 $R0", "  StrCpy $R3 0", "  StrCpy $R4 0", "  ${Do}", "    ${If} $R3 >= $R2", "      ${ExitDo}", "    ${EndIf}",
            "    StrCpy $R1 $R0 1 $R3", '    ${If} $R1 == ","', "      ${If} $R4 == 0"] + ["    " + x for x in bad("is a comma separated list with an empty item")] + ["      ${EndIf}", "      StrCpy $R4 0",
            '    ${ElseIf} $R1 != " "', "      StrCpy $R4 1", "    ${EndIf}", "    IntOp $R3 $R3 + 1", "  ${Loop}", "  ${If} $R4 == 0"] + bad("is a comma separated list with an empty item", False) + ["  ${EndIf}", "FunctionEnd"]
    return out


def _check_lines(i):
    """Check_<id>: the typed value of one input in $in_<id>; the reason (or empty) in $R9. Rules come from the kind and the attributes, as in validate_values."""
    k = i["kind"]
    out = ["", "Function Check_%s" % i["id"], "  StrCpy $R0 $in_%s" % i["id"]]
    if k == "secret":
        out.append("  Call Val_NoBad" if i.get("no_blank") else "  Call Val_Line")
        return out + ["FunctionEnd"]
    out += ["  Call Val_Line", '  ${If} $R9 != ""', "    Return", "  ${EndIf}"]
    if k in ("text", "path"):
        out.append("  Call Val_NoQuote")
    elif k == "url":
        out.append("  Call Val_Https" if i.get("https_only") else "  Call Val_Http")
    elif k == "list":
        out.append("  Call Val_List")
    else:
        words = i["choices"] if k == "choice" else ["yes", "no"]
        out.append('  ${StrCase} $R1 $R0 "L"')
        for n, c in enumerate(words):
            out += ['  ${%s} $R1 == "%s"' % ("If" if n == 0 else "ElseIf", c), '    StrCpy $in_%s "%s"' % (i["id"], c)]
        out += ["  ${Else}", '    StrCpy $R9 "must be one of %s"' % ", ".join(words), "  ${EndIf}"]
    return out + ["FunctionEnd"]


def _together_lines():
    a, b = TOGETHER
    return ["", "Function Check_together", '  StrCpy $R9 ""', '  ${If} $in_%s == ""' % a, '  ${AndIf} $in_%s != ""' % b, '    StrCpy $R9 "%s"' % TOGETHER_TEXT,
            '  ${ElseIf} $in_%s != ""' % a, '  ${AndIf} $in_%s == ""' % b, '    StrCpy $R9 "%s"' % TOGETHER_TEXT, "  ${EndIf}", "FunctionEnd"]


PIN_TEXT = "This NI docker image container type and year are not in the pinned list"
LICENCE_TEXT = "Tick both licence boxes to continue"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_REPOSITORY = re.compile(r"(?=.{1,255}\Z)[a-z0-9][a-z0-9._/-]*")


def _image_lines(schema):
    """Image_Known (the pair is pinned: listed with BOTH a digest and a repository; empty means both unset) and Image_Ref (repository@digest of the pair, empty while either is not recorded).
    Both are tables built from the schema, never from typed text. Pair in $in_image_variant and $in_image_year; the answer in $R9 and $R8."""
    entries = schema["images"]["list"]
    out = ["", "Function Image_Known", '  StrCpy $R9 ""', '  ${If} $in_image_variant == ""', "    Return", "  ${EndIf}"]
    for e in entries:
        if e.get("digest") and e.get("repository"):
            out += ['  ${If} $in_image_variant == "%s"' % e["variant"], '  ${AndIf} $in_image_year == "%s"' % e["year"], "    Return", "  ${EndIf}"]
    out += ['  StrCpy $R9 "%s"' % PIN_TEXT, "FunctionEnd", "", "Function Image_Ref", '  StrCpy $R8 ""']
    for e in entries:
        if e.get("digest") and e.get("repository"):
            out += ['  ${If} $in_image_variant == "%s"' % e["variant"], '  ${AndIf} $in_image_year == "%s"' % e["year"],
                    '    StrCpy $R8 "%s@%s"' % (e["repository"], e["digest"]), "  ${EndIf}"]
    return out + ["FunctionEnd"]


def _leave_lines(page, fields):
    """Page_<page>_Leave: read the fields, check each given one, show ONE message and stay on the page when a value is bad."""
    out = ["", "Function Page_%s_Leave" % page]
    licences = []
    for i in fields:
        if i["kind"] == "licence":
            out += ["  ${NSD_GetState} $ctl_%s $0" % i["id"], '  StrCpy $in_%s "no"' % i["id"], "  ${If} $0 == ${BST_CHECKED}", '    StrCpy $in_%s "yes"' % i["id"], "  ${EndIf}"]
            licences.append(i["id"])
        else:
            out.append("  ${NSD_GetText} $ctl_%s $in_%s" % (i["id"], i["id"]))
    for i in fields:
        if i["kind"] == "licence":
            continue
        lab = i["label"].replace('"', "'")
        out += ['  ${If} $in_%s != ""' % i["id"], "    Call Check_%s" % i["id"], '    ${If} $R9 != ""',
                '      MessageBox MB_OK|MB_ICONEXCLAMATION "%s: $R9." /SD IDOK' % lab, "      Abort", "    ${EndIf}", "  ${EndIf}"]
    if all(t in [f["id"] for f in fields] for t in TOGETHER):
        out += ["  Call Check_together", '  ${If} $R9 != ""', '    MessageBox MB_OK|MB_ICONEXCLAMATION "$R9." /SD IDOK', "    Abort", "  ${EndIf}",
                "  Call Image_Known", '  ${If} $R9 != ""', '    MessageBox MB_OK|MB_ICONEXCLAMATION "$R9." /SD IDOK', "    Abort", "  ${EndIf}"]
    for n, lid in enumerate(licences):
        out.append('  ${%s} $in_%s != "yes"' % ("If" if n == 0 else "OrIf", lid))
    if licences:
        out += ['    MessageBox MB_OK|MB_ICONEXCLAMATION "%s." /SD IDOK' % LICENCE_TEXT, "    Abort", "  ${EndIf}"]
    return out + ["FunctionEnd"]


def _silent_lines(schema):
    """ValidateSilentKeys (silent runs, after the mode): the names first (31, or 30 for a key with no value), then every given value (30)."""
    c30, c31 = schema["exit_codes"]["bad-value"], schema["exit_codes"]["unknown-key"]
    keys = [silent_key(i["id"]) for i in public_inputs(schema)]
    out = ["", "; Exit %d for a bad value and %d for an unknown key, after the step is logged with the key NAME only; nothing is written before them." % (c30, c31),
           "Function Silent_Bad", "  Pop $R0", "  Pop $R1", "  Push $R0", "  Call Carried_Box", "  Push $R1", "  Push $R0", '  Push "%d"' % c30, "  Call LogStep", "  SetErrorLevel %d" % c30, "  Quit", "FunctionEnd", "", "; Reads the parameters, not the program path (see RefuseSecretOptions).",
           "; The first check is the quote: a command line that ends inside a double quote hides what follows from every key check, so it exits %d. The log holds fixed words, never the" % c30,
           "; swallowed text (it may be a secret).", "!macro ValidateSilentKeys",
           "  Call Cmdline_EndsInQuote", "  Pop $vs_c", "  ${If} $vs_c == 1", '    Push "bad-value"', '    Push "command-line"', "    Call Silent_Bad", "  ${EndIf}",
           "  Call Cmdline_Begin", "  ${Do}", "    Call Cmdline_Next", "    ${If} ${Errors}", "      ${ExitDo}", "    ${EndIf}",
           "    StrCpy $vs_c $cl_name 1", '    ${If} $vs_c == "/"', '      ${StrCase} $vs_name $cl_name "U"', '      StrCpy $vs_kind ""']
    for n, name in enumerate(PASS_THROUGH):
        out.append('      ${%s} $vs_name == "%s"' % ("If" if n == 0 else "OrIf", name))
    out.append("        StrCpy $vs_kind pass")
    for n, name in enumerate(keys):
        out.append('      ${%s} $vs_name == "%s"' % ("ElseIf" if n == 0 else "OrIf", name))
    out += ["        StrCpy $vs_kind key", "      ${EndIf}", '      ${If} $vs_kind == ""', '        Push "$vs_name"', "        Call Carried_Box", '        Push "unknown-key"', '        Push "$vs_name"', '        Push "%d"' % c31, "        Call LogStep",
            "        SetErrorLevel %d" % c31, "        Quit", "      ${EndIf}", '      ${If} $vs_kind == "key"', '      ${AndIf} $cl_val == ""',
            '        Push "bad-value"', '        Push "$vs_name"', "        Call Silent_Bad", "      ${EndIf}", "    ${EndIf}", "  ${Loop}", "  ClearErrors"]
    for i in public_inputs(schema):
        if i.get("setter"):
            continue
        out += ['  ${If} $in_%s != ""' % i["id"], "    Call Check_%s" % i["id"], '    ${If} $R9 != ""', '      Push "%s"' % i["id"], '      Push "%s"' % silent_key(i["id"]), "      Call Silent_Bad", "    ${EndIf}", "  ${EndIf}"]
    a, b = TOGETHER
    out += ["  Call Check_together", '  ${If} $R9 != ""', '    Push "%s"' % a, '    Push "%s"' % silent_key(a), "    Call Silent_Bad", "  ${EndIf}", "!macroend"]
    return out


def _carry_lines(schema):
    """Carry_Answers: one Carry_One call per non-secret answer that is not blank (label, key with its "=", value). The secrets have no line here: they never go on a command line."""
    out = ["", "; What the first window hands to the elevated copy: the non-blank answers, one token each (Carry_One, elevate.nsh). The three secrets are not here and never go on a command line.",
           "Function Carry_Answers"]
    for i in public_inputs(schema):
        out += ['  ${If} $in_%s != ""' % i["id"], '    Push "%s"' % i["label"].replace('"', "'"), '    Push "%s="' % silent_key(i["id"]), "    Push $in_%s" % i["id"],
                "    Call Carry_One", "  ${EndIf}"]
    return out + ["FunctionEnd"]


def validate_schema(schema):
    ids = [i["id"] for i in schema["inputs"]]
    if len(ids) != len(set(ids)):
        raise SchemaError("duplicate input id")
    pages = {p["id"] for p in schema["pages"]}
    for i in schema["inputs"]:
        if i["page"] not in pages:
            raise SchemaError("input %s is on an unknown page" % i["id"])
        if i["kind"] == "choice" and not i.get("choices"):
            raise SchemaError("choice input %s has no choices" % i["id"])
    pattern = re.compile(schema["secret_refusal"]["name_pattern"])
    for i in wired_inputs(schema):
        if i["kind"] != "choice" or [p for p in schema["pages"] if p["id"] == i["page"] and p.get("only_when")] \
                or len([j for j in schema["inputs"] if j["page"] == i["page"]]) != 1:
            raise SchemaError("input %s has a setter: it must be a choice alone on an unconditional page" % i["id"])
    for i in schema["inputs"]:
        if i["kind"] == "secret":
            if any(k in i for k in ("default", "value", "choices")):
                raise SchemaError("secret input %s must not carry a default, value or choices (INST-REQ-024)" % i["id"])
            if not pattern.search(silent_key(i["id"])):
                raise SchemaError("secret input %s would not be recognised as a secret option" % i["id"])
        elif pattern.search(silent_key(i["id"])):
            raise SchemaError("input %s has a secret-looking silent key" % i["id"])
    for e in schema["images"]["list"]:
        if e.get("digest") is not None and not _DIGEST.fullmatch(e["digest"]):
            raise SchemaError("an image digest is not a sha256 digest")
        if e.get("repository") is not None and not _REPOSITORY.fullmatch(e["repository"]):
            raise SchemaError("an image repository name is not valid")
    pairs = [(e["variant"], e["year"]) for e in schema["images"]["list"]]
    if len(set(pairs)) != len(pairs):
        raise SchemaError("images.list holds a variant and year pair twice")
    if "digest" in "".join(ids):
        raise SchemaError("the image digest is never an input (INST-REQ-021)")
    if len(set(schema["exit_codes"].values())) != len(schema["exit_codes"]):
        raise SchemaError("exit codes must be distinct (INST-REQ-026)")


def generate_nsh(schema):
    """The committed screens include: variables, silent parsing, the secret refusal and one page function per page."""
    out = ["; GENERATED from installer/schema.json by `python -m installer.schema generate`; do not edit (drift is checked in CI).",
           '; The pages and macros are wired in by later slices; until then their functions are unreferenced.', "!pragma warning disable 6010", '!include "LogicLib.nsh"', '!include "nsDialogs.nsh"', '!include "FileFunc.nsh"',
           '!include "StrFunc.nsh"', "${StrStr}", "${StrCase}", ""]
    for i in schema["inputs"]:
        out.append("Var in_%s" % i["id"])
    for i in wired_inputs(schema):
        out += ["Var ctl_%s_%s" % (i["id"], c) for c in i["choices"]]
    for i in schema["inputs"]:
        if not i.get("setter"):
            out.append("Var ctl_%s" % i["id"])
    out += ["Var vs_c", "Var vs_name", "Var vs_kind", "; 1 in the elevated copy that got its answers from the first window (Carried_Detect, elevate.nsh): the pages those answers are for are skipped.", "Var carried"]
    out += ["", "; The command line is read by ONE reader, installer/nsis/cmdline.nsh (Cmdline_Begin, Cmdline_Next, Cmdline_Get).", "!macro ParseSilentKeys"]
    for i in public_inputs(schema):
        out += ['  Push "%s="' % silent_key(i["id"]), "  Call Cmdline_Get", "  Pop $in_%s" % i["id"]]
    out.append("!macroend")
    code_long = schema["exit_codes"]["cmdline-too-long"]
    out += ["", "; Exit %d (#136): NSIS keeps at most %d characters of $CMDLINE and cuts the rest without a word, so a line of %d or more may have lost a key." % (code_long, COMMAND_LINE_LIMIT, COMMAND_LINE_LIMIT),
            "; This is the first command-line check, before the secret refusal. It logs fixed words only (the log is appended to only when it already exists) and writes nothing else.",
            "!macro RefuseLongCommandLine", "  StrLen $vs_c $CMDLINE", "  ${If} $vs_c >= %d" % COMMAND_LINE_LIMIT, "    Call Log_InitPaths", "    StrCpy $LogExistingOnly 1",
            '    Push "cmdline-too-long"', '    Push "command-line"', '    Push "%d"' % code_long, "    Call LogStep", "    SetErrorLevel %d" % code_long, "    Quit", "  ${EndIf}", "!macroend"]
    out += ["", "; INST-REQ-023, 075, 098: a secret on the command line, in a file or on standard input is a typed exit.",
            "; Both command-line loops read the parameters through the one reader, never $CMDLINE: $CMDLINE starts with the program path, and a dash, a slash or a secret-looking word in that path is not an option.",
            "; Refuse_Pass is ONE pass over the words the reader gives after Cmdline_Begin or Cmdline_BeginRaw: the one copy of the refusal rules.",
            "Function Refuse_Pass"]
    sr = schema["secret_refusal"]
    code_cl = schema["exit_codes"]["secret-on-command-line"]
    code_file = schema["exit_codes"]["secret-from-file-or-stdin"]
    out += ["  ${Do}", "    Call Cmdline_Next", "    ${If} ${Errors}", "      ${ExitDo}", "    ${EndIf}",
            "    StrCpy $R2 $cl_name 1", '    ${If} $cl_tok == "-"', "      SetErrorLevel %d" % code_file, "      Quit",
            '    ${ElseIf} $R2 == "/"', '      ${StrCase} $R3 $cl_name "U"']
    for o in sr["file_or_stdin_options"]:
        out += ['      ${If} $R3 == "/%s"' % o, "        SetErrorLevel %d" % code_file, "        Quit", "      ${EndIf}"]
    for word in sr["name_pattern"].split("|"):
        out += ['      ${StrStr} $R4 $R3 "%s"' % word, '      ${If} $R4 != ""', "        SetErrorLevel %d" % code_cl, "        Quit", "      ${EndIf}"]
    out += ["    ${EndIf}", "  ${Loop}", "  ClearErrors", "FunctionEnd"]
    out += ["", "; An unclosed double quote hides every later word from the quote-aware pass, so the words are read twice: grouped by quotes, then RAW (a quote opens no group).",
            "!macro RefuseSecretOptions", "  Call Cmdline_Begin", "  Call Refuse_Pass", "  Call Cmdline_BeginRaw", "  Call Refuse_Pass", "!macroend"]
    out += _helper_lines()
    for i in schema["inputs"]:
        if not i.get("setter"):
            out += _check_lines(i)
    out += _together_lines()
    out += _image_lines(schema)
    out += _silent_lines(schema)
    out += _carry_lines(schema)
    for p in schema["pages"]:
        fields = [i for i in schema["inputs"] if i["page"] == p["id"]]
        out += ["", "Function Page_%s" % p["id"]]
        if not any(i["kind"] == "secret" for i in fields):
            out += ["  ${If} $carried == 1", "    Abort", "  ${EndIf}"]
        if p.get("only_when") == "image_chosen":
            out.append('  ${If} $in_image_variant == ""')
            out.append("    Abort")
            out.append("  ${EndIf}")
        out.append("  !insertmacro Dialog_Create")
        if any(i["kind"] == "secret" for i in fields):
            out += ["  ; the elevated copy shows nothing before this page, and Back from the first page ends the installer window: the button is off there",
                    "  ${If} $carried == 1", "    GetDlgItem $0 $HWNDPARENT 3", "    EnableWindow $0 0", "  ${EndIf}"]
        top, pitch, gap = 4, 18, 8
        if p.get("help"):
            out.append('  ${NSD_CreateLabel} 0u 0u 100%% %du "%s"' % (HELP_HEIGHT, p["help"].replace('"', "'")))
            top, pitch, gap = HELP_HEIGHT + 4, FIELD_PITCH, 9
        if any(i.get("setter") for i in fields):
            out += _wired_page(fields[0], schema, top)
            continue
        for n, i in enumerate(fields):
            y = top + n * pitch
            lab = i["label"].replace('"', "'")
            if i["kind"] == "licence":
                out.append('  ${NSD_CreateCheckbox} 0u %du 100%% 12u "%s"' % (y, lab))
            else:
                out.append('  ${NSD_CreateLabel} 0u %du 100%% 8u "%s"' % (y, lab))
                create = "${NSD_CreatePassword}" if i["kind"] == "secret" else "${NSD_CreateText}"
                out.append("  %s 0u %du 100%% 12u \"\"" % (create, y + gap))
            out.append("  Pop $ctl_%s" % i["id"])
            if i["kind"] != "licence":
                out.append("  SendMessage $ctl_%s ${EM_LIMITTEXT} %d 0" % (i["id"], TEXT_LIMIT))
        out.append("  nsDialogs::Show")
        out.append("FunctionEnd")
        out += _leave_lines(p["id"], fields)
    out.append("")
    return "\n".join(out)


def check_drift(schema, path=SCREENS_PATH):
    p = Path(path)
    return p.exists() and p.read_text(encoding="utf-8") == generate_nsh(schema)


def scan_command_line(text, raw=False):
    """The command-line reader of installer/nsis/cmdline.nsh (Cmdline_Next) in Python: (tokens, ends_in_quote). A double quote toggles a quote state and is dropped,
    a blank or a tab outside quotes ends a token, everything else (apostrophe, backtick, backslash) is ordinary, an unclosed quote runs to the end of the text.
    raw=True is the RAW mode (Cmdline_BeginRaw): a double quote is still dropped but toggles nothing, so a blank or a tab always ends a token and the text never
    ends inside a quote. The blanks at the end of the text are cut first, as Cmdline_Begin does (it only shows inside an unclosed quote). The text is what follows the program name: Cmdline_Begin skips the name itself, so a one-letter name hides nothing (#136)."""
    text = text.rstrip(" ")
    tokens, i, n, quoted = [], 0, len(text), False
    while True:
        while i < n and text[i] in " \t":
            i += 1
        if i >= n:
            return tokens, quoted
        token, quoted = [], False
        while i < n:
            c = text[i]
            i += 1
            if c == '"':
                if not raw:
                    quoted = not quoted
            elif not quoted and c in " \t":
                break
            else:
                token.append(c)
        tokens.append("".join(token))


def split_command_line(text, raw=False):
    """The tokens of scan_command_line."""
    return scan_command_line(text, raw)[0]


def parse_silent(schema, argv, stdin_is_secret=False, command_line_length=None):
    """Reference parse of silent-mode arguments (without the program name): a list of tokens, or the command-line text, which scan_command_line splits.
    Returns {input id: value}; raises a typed error. Two passes, as .onInit does: the secret refusal first (RefuseSecretOptions), then the names and the missing
    values (ValidateSilentKeys). Only a token starting with / is an option; the first token with a key wins. A text gets two refusal passes, its quote-aware tokens
    and then its RAW words (so an unclosed quote hides no secret key), and a text that ends inside a double quote is exit 30, the first check of the second pass
    (after 32 and 33, before 31); the error names no text of the command line. A token list has neither: there is no text to scan.
    The first check is the length: NSIS keeps at most COMMAND_LINE_LIMIT characters of $CMDLINE, program path included, and refuses a line of COMMAND_LINE_LIMIT or more with exit 50
    (RefuseLongCommandLine). This reader never sees the program path Windows puts in front, so the caller gives the length of the FULL line as command_line_length (None: not checked)."""
    if command_line_length is not None and command_line_length >= COMMAND_LINE_LIMIT:
        raise CommandLineTooLong("the command line is %d characters or more" % COMMAND_LINE_LIMIT)
    text = argv if isinstance(argv, str) else None
    open_quote = False
    if text is not None:
        argv, open_quote = scan_command_line(text)
    keys = silent_keys(schema)
    secret_names = {silent_key(i["id"]) for i in secret_inputs(schema)}
    pattern = re.compile(schema["secret_refusal"]["name_pattern"])
    file_opts = {"/" + o for o in schema["secret_refusal"]["file_or_stdin_options"]}
    values = {}
    if stdin_is_secret:
        raise SecretFromFileOrStdin("silent mode takes no secret on standard input")
    for arg in argv + (split_command_line(text, raw=True) if text is not None else []):
        name = arg.partition("=")[0].upper()
        if arg == "-" or (arg[:1] == "/" and name in file_opts):
            raise SecretFromFileOrStdin("silent mode takes no secret from a file or standard input (%s)" % name)
        if arg[:1] == "/" and (name in secret_names or pattern.search(name)):
            raise SecretOnCommandLine("silent mode never takes a secret on the command line (%s)" % name)
    if open_quote:
        raise BadValue("the command line ends inside a double quote")
    for arg in argv:
        name, _, value = arg.partition("=")
        name = name.upper()
        if arg[:1] != "/" or name in PASS_THROUGH:
            continue
        if name not in keys:
            raise UnknownKey("unknown silent key %s" % name)
        if not value:
            raise BadValue("silent key %s needs a value" % name)
        values.setdefault(keys[name], value)
    return values



def _https_problem(v):
    """The https-only address rule, written the same way in the NSIS Val_Https: a reason, or None when the address is good."""
    if _BAD_TEXT.search(v):
        return "must not hold a space, quote, backslash or control character"
    if v[:8].lower() != "https://":
        return "must start with https://"
    authority = re.split(r"[/?#]", v[8:], maxsplit=1)[0]
    host, colon, port = authority.partition(":")
    if not host or re.search(r"[@\[\]]", authority):
        return "needs a plain host name"
    if colon and not re.fullmatch(r"[0-9]{1,5}", port):
        return "has a port that is not one to five digits"
    return None


def validate_values(schema, values):
    by_id = {i["id"]: i for i in schema["inputs"]}
    for k in values:
        if k not in by_id:
            raise UnknownKey("unknown input %s" % k)
    for i in schema["inputs"]:
        if i.get("required") and not values.get(i["id"]):
            raise BadValue("%s is required" % silent_key(i["id"]))
    if bool(values.get("image_variant")) != bool(values.get("image_year")):
        raise BadValue("/IMAGE_VARIANT and /IMAGE_YEAR must be given together")
    for k, v in values.items():
        spec = by_id[k]
        key = silent_key(k)
        if not v.strip() or re.search(r"[\x00-\x1f]", v):
            raise BadValue("%s must be a non-empty single-line value" % key)
        if spec["kind"] in ("text", "path") and '"' in v:
            raise BadValue("%s must not contain a double quote" % key)
        if spec["kind"] == "choice" and v.lower() not in spec["choices"]:
            raise BadValue("%s must be one of %s" % (key, ", ".join(spec["choices"])))
        if spec["kind"] == "url" and spec.get("https_only"):
            problem = _https_problem(v)
            if problem:
                raise BadValue("%s %s" % (key, problem))
        elif spec["kind"] == "url" and not re.match(r"^https?://[^ \t\r\n/]", v):
            raise BadValue("%s must be an http or https address" % key)
        if spec.get("no_blank") and _BAD_TEXT.search(v):
            raise BadValue("%s must not hold a space, quote, backslash or control character" % key)
        if spec["kind"] == "licence" and v.lower() not in ("yes", "no"):
            raise BadValue("%s must be yes or no" % key)
        if spec["kind"] == "list" and not all(x.strip() for x in v.split(",")):
            raise BadValue("%s must be a comma separated list without empty items" % key)
        if spec["kind"] in ("licence", "choice"):
            values[k] = v.lower()


def normalise_edition(caption):
    c = re.sub(r"^\s*microsoft\s+", "", (caption or "").strip(), flags=re.I)
    return re.sub(r"\s+", " ", c)


def check_edition(schema, caption):
    """Edition gate (INST-REQ-016, 017). Returns the normalised edition or raises EditionRefused with a plain reason."""
    name = normalise_edition(caption)
    low = name.lower()
    table = schema["editions"]
    if "ltsc" not in low and any(low == e.lower() for e in table["accepted_exact"]):
        return name
    if "ltsc" not in low and any(low == p.lower() or low.startswith(p.lower() + " ") for p in table["accepted_prefix"]):
        return name
    accepted = ", ".join(table["accepted_exact"] + table["accepted_prefix"])
    raise EditionRefused("%s is not supported: this installer runs only on %s." % (name or "an unknown Windows edition", accepted))


def pinned_digest(schema, variant, year):
    """The digest always comes from the pinned list, never from the user (INST-REQ-021, 022)."""
    for e in schema["images"]["list"]:
        if e["variant"] == variant and e["year"] == year:
            if not e["digest"] or not e.get("repository"):
                raise ImageNotPinned("no digest and repository are pinned yet for the %s %s image" % (year, variant))
            return e["digest"]
    raise ImageNotPinned("there is no %s image for %s" % (variant, year))


def image_chosen(values):
    return bool(values.get("image_variant") or values.get("image_year"))


def run_silent(schema, argv, caption, state_dir, now, stdin_is_secret=False, log=None, command_line_length=None):
    """Reference silent run: returns the exit code and appends one reason line per failure to `log` (a list)."""
    from installer import licences
    try:
        values = parse_silent(schema, argv, stdin_is_secret, command_line_length)
        validate_values(schema, values)
        check_edition(schema, caption)
        if image_chosen(values):
            pinned_digest(schema, values.get("image_variant"), values.get("image_year"))
            licences.require_both(values)
            licences.write_record(state_dir, now)
    except SchemaError as e:
        if log is not None:
            log.append("%s: %s" % (e.kind, e))
        return exit_code(schema, e)
    return exit_code(schema)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    schema = load_schema()
    validate_schema(schema)
    if argv == ["generate"]:
        SCREENS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SCREENS_PATH.write_text(generate_nsh(schema), encoding="utf-8")
        return 0
    if argv == ["check"]:
        if check_drift(schema):
            return 0
        print("installer/nsis/screens.nsh differs from installer/schema.json: run `python -m installer.schema generate`")
        return 2
    print("usage: python -m installer.schema generate|check")
    return 2


if __name__ == "__main__":
    sys.exit(main())
