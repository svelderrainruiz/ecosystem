; ONE reader of the command line (SL-16e, #114). Everything that looks at the options goes through here: the secret refusal, the silent-key check,
; the 14 keys, every choice's silent selection, the trust signer and, since SL-21b (#117), the flags of the elevated copy (Cmdline_Has) and the
; answers the first window hands over (Cmdline_Quote, the producer side). Real ${GetOptions} and ${WordFind} are not used: GetOptions ends an unquoted
; value at the next "/" (an unquoted URL was cut) and keeps a quote state for ' and ` (a lone apostrophe hid every later key).
;
; Rules. The text is $CMDLINE without the program name, which Cmdline_Begin skips itself in plain NSIS; it replaces ${GetParameters} (#136, REPORT L3). ${GetParameters} starts its
; search for the end of the name at the THIRD character, so after a one-letter unquoted name ("s /FOO /S") the blank at the second character was not seen and the first
; parameter was dropped unless cmd had added a second blank (measured on Windows 11: through cmd /FOO was read, exit 31; by CreateProcess it was dropped, exit 3), and it
; did not take a tab as a separator. Now: a name that starts with a double quote ends at the next double quote (at the end of the text when there is none); any other name
; ends at the first blank or tab; the text is the rest, with the blanks at its end cut as ${GetParameters} did. Leading blanks and tabs are skipped by the scan below.
; Scanned left to right with a quote flag:
;   - a double quote toggles the flag and is dropped from the token; there are no escapes (a backslash before a quote is an ordinary backslash);
;   - a blank or a tab outside quotes ends a token; apostrophe and backtick are ordinary characters; an unclosed quote runs to the end of the text;
;   - a key is the token text up to its first "=" (slash included), compared without case; the value is the rest, quotes already removed, and may be empty;
;   - the first token with a key wins, and a key never matches the start of a longer key (the "=" is part of the match).
; A RAW pass (Cmdline_BeginRaw, $cl_raw) is the same scan with the toggle off: a double quote is still dropped but opens no group, so a blank or a tab always ends a
; word. An unclosed quote hides every later key from the quote-aware pass and cannot hide it from the raw one: the secret refusal walks both. Cmdline_EndsInQuote
; tells whether the text ends inside a quote (an odd number of double quotes); the names pass refuses that with exit 30.
; installer/schema.py scan_command_line, split_command_line and parse_silent give the same answers (tests/test_installer_sl16e.py compares them).
!include "LogicLib.nsh"
!include "FileFunc.nsh"

Var cl_text
Var cl_pos
Var cl_c
Var cl_q
Var cl_raw
Var cl_tok
Var cl_name
Var cl_val
Var cl_eq
Var cl_key
Var cl_qv
Var cl_qi

; Starts a quote-aware pass over the parameters: $cl_text is $CMDLINE after the program name (see the rules above).
Function Cmdline_Begin
  StrCpy $cl_c $CMDLINE 1
  ${If} $cl_c == '"'
    StrCpy $cl_pos 1
    ${Do}
      StrCpy $cl_c $CMDLINE 1 $cl_pos
      ${If} $cl_c == ""
        ${ExitDo}
      ${EndIf}
      IntOp $cl_pos $cl_pos + 1
      ${If} $cl_c == '"'
        ${ExitDo}
      ${EndIf}
    ${Loop}
  ${Else}
    StrCpy $cl_pos 0
    ${Do}
      StrCpy $cl_c $CMDLINE 1 $cl_pos
      ${If} $cl_c == ""
      ${OrIf} $cl_c == " "
      ${OrIf} $cl_c == "$\t"
        ${ExitDo}
      ${EndIf}
      IntOp $cl_pos $cl_pos + 1
    ${Loop}
  ${EndIf}
  StrCpy $cl_text $CMDLINE "" $cl_pos
  ${Do}
    StrCpy $cl_c $cl_text 1 -1
    ${If} $cl_c != " "
      ${ExitDo}
    ${EndIf}
    StrCpy $cl_text $cl_text -1
  ${Loop}
  StrCpy $cl_pos 0
  StrCpy $cl_q 0
  StrCpy $cl_raw 0
FunctionEnd

; Starts a RAW pass: the same scan, a double quote opens no group.
Function Cmdline_BeginRaw
  Call Cmdline_Begin
  StrCpy $cl_raw 1
FunctionEnd

; Next token: $cl_tok, split at its first "=" into $cl_name and $cl_val ($cl_eq is 1 when there is an "="). The error flag is set when no token is left.
; $cl_q is 1 while a double quote is open and stays as the last token left it when the end is reported.
Function Cmdline_Next
  ${Do}
    StrCpy $cl_c $cl_text 1 $cl_pos
    ${If} $cl_c == ""
      SetErrors
      Return
    ${EndIf}
    ${If} $cl_c != " "
    ${AndIf} $cl_c != "$\t"
      ${ExitDo}
    ${EndIf}
    IntOp $cl_pos $cl_pos + 1
  ${Loop}
  ClearErrors
  StrCpy $cl_tok ""
  StrCpy $cl_name ""
  StrCpy $cl_val ""
  StrCpy $cl_eq 0
  StrCpy $cl_q 0
  ${Do}
    StrCpy $cl_c $cl_text 1 $cl_pos
    ${If} $cl_c == ""
      ${ExitDo}
    ${EndIf}
    IntOp $cl_pos $cl_pos + 1
    ${If} $cl_c == '"'
      ${If} $cl_raw == 0
        IntOp $cl_q $cl_q ^ 1
      ${EndIf}
    ${Else}
      ${If} $cl_q == 0
        ${If} $cl_c == " "
        ${OrIf} $cl_c == "$\t"
          ${ExitDo}
        ${EndIf}
      ${EndIf}
      StrCpy $cl_tok "$cl_tok$cl_c"
      ${If} $cl_eq == 1
        StrCpy $cl_val "$cl_val$cl_c"
      ${ElseIf} $cl_c == "="
        StrCpy $cl_eq 1
      ${Else}
        StrCpy $cl_name "$cl_name$cl_c"
      ${EndIf}
    ${EndIf}
  ${Loop}
FunctionEnd

; Push 1 when the text ends inside a double quote (the last token ran to the end with its group open), else 0: a walk of the quote-aware pass.
Function Cmdline_EndsInQuote
  Call Cmdline_Begin
  ${Do}
    Call Cmdline_Next
    ${If} ${Errors}
      ${ExitDo}
    ${EndIf}
  ${Loop}
  Push $cl_q
FunctionEnd

; Push the key with its "=" (for example "/MODE="), Call Cmdline_Get, Pop the value: empty and the error flag set when no token has the key, else
; the value of the first token that has it and the flag clear. ${If} ${Errors} is IfErrors, which CLEARS the flag it tests, so the end sets it again.
Function Cmdline_Get
  Pop $cl_key
  Call Cmdline_Begin
  ${Do}
    Call Cmdline_Next
    ${If} ${Errors}
      Push ""
      SetErrors
      Return
    ${EndIf}
    ${If} $cl_eq == 1
    ${AndIf} "$cl_name=" == $cl_key
      Push $cl_val
      Return
    ${EndIf}
  ${Loop}
FunctionEnd

; Push a flag that has no value (for example "/ELEVATED"), Call Cmdline_Has, Pop 1 when a token is exactly that flag (a "=" makes it a key, not a flag), else 0. ${If} ${Errors} clears the flag it tests.
Function Cmdline_Has
  Pop $cl_key
  Call Cmdline_Begin
  ${Do}
    Call Cmdline_Next
    ${If} ${Errors}
      Push 0
      Return
    ${EndIf}
    ${If} $cl_eq == 0
    ${AndIf} $cl_name == $cl_key
      Push 1
      Return
    ${EndIf}
  ${Loop}
FunctionEnd

; Producer side: Push a value, Call Cmdline_Quote, Pop the text to put on a command line so that the reader gives the value back. A value with a
; blank or a tab gets double quotes. There are no escapes, so a value that holds a double quote cannot be written back: the text and path screens refuse
; one, the url and list screens do not, and the caller must not pass it (Carry_One in elevate.nsh refuses to carry such a value, #117).
Function Cmdline_Quote
  Pop $cl_qv
  StrCpy $cl_qi 0
  ${Do}
    StrCpy $cl_c $cl_qv 1 $cl_qi
    ${If} $cl_c == ""
      ${ExitDo}
    ${EndIf}
    ${If} $cl_c == " "
    ${OrIf} $cl_c == "$\t"
      StrCpy $cl_qv '"$cl_qv"'
      ${ExitDo}
    ${EndIf}
    IntOp $cl_qi $cl_qi + 1
  ${Loop}
  Push $cl_qv
FunctionEnd
